"""Rate limiting, spend accounting, and the answer cache.

The service scales to several instances, so counters cannot live in process memory. They
live in Firestore, behind a small interface that the tests replace with a dictionary —
no emulator, no credentials, no network.

Counters are incremented *before* the model is called, so the system fails closed: a
crash mid-request costs a counted query, never an uncounted one.
"""

from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

from server.config import Settings


class Ledger(Protocol):
    """The persistence the guard needs. Deliberately tiny."""

    def bump(self, key: str, amount: int, expires_at: datetime) -> int: ...

    def read(self, key: str) -> int: ...

    def cache_get(self, key: str) -> dict[str, Any] | None: ...

    def cache_put(self, key: str, value: dict[str, Any], expires_at: datetime) -> None: ...


class MemoryLedger:
    """In-process ledger for tests and single-instance local runs."""

    def __init__(self) -> None:
        self.counters: dict[str, int] = {}
        self.cache: dict[str, tuple[float, dict[str, Any]]] = {}

    def bump(self, key: str, amount: int, expires_at: datetime) -> int:
        self.counters[key] = self.counters.get(key, 0) + amount
        return self.counters[key]

    def read(self, key: str) -> int:
        return self.counters.get(key, 0)

    def cache_get(self, key: str) -> dict[str, Any] | None:
        entry = self.cache.get(key)
        if not entry:
            return None
        expires, value = entry
        if expires < time.time():
            del self.cache[key]
            return None
        return value

    def cache_put(self, key: str, value: dict[str, Any], expires_at: datetime) -> None:
        self.cache[key] = (expires_at.timestamp(), value)


class FirestoreLedger:
    """Firestore-backed ledger.

    Increment-then-read rather than a transaction: the counters can overshoot by a query
    or two when instances race, which at a fraction of a cent per query is far cheaper
    than the contention a transaction would add. ``expires_at`` is stored so a Firestore
    TTL policy on the collection reclaims old documents without a cleanup job.
    """

    def __init__(self, project: str, collection: str = "insightnet_ask") -> None:
        from google.cloud import firestore

        self._db = firestore.Client(project=project or None)
        self._increment = firestore.Increment
        self._collection = collection

    def _doc(self, key: str):
        return self._db.collection(self._collection).document(key)

    def bump(self, key: str, amount: int, expires_at: datetime) -> int:
        doc = self._doc(key)
        doc.set({"count": self._increment(amount), "expires_at": expires_at}, merge=True)
        snapshot = doc.get()
        return int((snapshot.to_dict() or {}).get("count", amount))

    def read(self, key: str) -> int:
        snapshot = self._doc(key).get()
        return int((snapshot.to_dict() or {}).get("count", 0))

    def cache_get(self, key: str) -> dict[str, Any] | None:
        snapshot = self._doc(f"cache_{key}").get()
        payload = (snapshot.to_dict() or {}).get("payload")
        return json.loads(payload) if payload else None

    def cache_put(self, key: str, value: dict[str, Any], expires_at: datetime) -> None:
        self._doc(f"cache_{key}").set(
            {"payload": json.dumps(value), "expires_at": expires_at}
        )


@dataclass(frozen=True)
class Denial:
    status: int
    body: dict[str, Any]


def hash_ip(address: str, salt: str) -> str:
    """Store a salted hash. The raw address is never written anywhere."""

    return hashlib.sha256(f"{salt}:{address}".encode()).hexdigest()[:32]


class Guard:
    """Rate limits and the monthly budget, checked cheapest-first."""

    def __init__(self, settings: Settings, ledger: Ledger, now: Callable[[], datetime] | None = None):
        self.settings = settings
        self.ledger = ledger
        self.now = now or (lambda: datetime.now(UTC))

    def check(self, address: str) -> Denial | None:
        settings, now = self.settings, self.now()
        month, day, minute = now.strftime("%Y-%m"), now.strftime("%Y-%m-%d"), now.strftime("%Y-%m-%dT%H:%M")

        spent = self.ledger.read(f"spend_{month}")
        if spent >= settings.monthly_budget_micros:
            resets = (now.replace(day=1) + timedelta(days=32)).replace(day=1)
            return Denial(
                503,
                {
                    "error": "budget_exhausted",
                    "resetsAt": resets.strftime("%Y-%m-01T00:00:00Z"),
                    "fallback": "keyword",
                },
            )

        if self.ledger.read(f"global_{day}") >= settings.daily_query_cap:
            return Denial(
                503,
                {"error": "budget_exhausted", "resetsAt": f"{day}T24:00:00Z", "fallback": "keyword"},
            )

        digest = hash_ip(address, settings.ip_salt)
        per_minute = self.ledger.bump(f"ip_{digest}_{minute}", 1, now + timedelta(minutes=5))
        if per_minute > settings.ip_minute_limit:
            return Denial(
                429,
                {"error": "rate_limited", "scope": "ip", "retryAfterSeconds": 60, "fallback": "keyword"},
            )

        per_day = self.ledger.bump(f"ip_{digest}_{day}", 1, now + timedelta(days=2))
        if per_day > settings.ip_day_limit:
            return Denial(
                429,
                {
                    "error": "rate_limited",
                    "scope": "ip_day",
                    "retryAfterSeconds": 3600,
                    "fallback": "keyword",
                },
            )

        # Counted before the model runs, so the system fails closed.
        self.ledger.bump(f"global_{day}", 1, now + timedelta(days=2))
        return None

    def record_spend(self, input_tokens: int, output_tokens: int) -> int:
        """Charge actual usage against the monthly budget."""

        settings, now = self.settings, self.now()
        micros = round(
            input_tokens * settings.price_in_micros_per_mtok / 1_000_000
            + output_tokens * settings.price_out_micros_per_mtok / 1_000_000
        )
        return self.ledger.bump(
            f"spend_{now.strftime('%Y-%m')}", micros, now + timedelta(days=70)
        )

    def cache_key(self, question: str, index_generated_at: str) -> str:
        """Key on the index version too, so a rebuild invalidates every cached answer."""

        normalized = " ".join(question.lower().split())
        return hashlib.sha256(f"{normalized}|{index_generated_at}".encode()).hexdigest()[:40]

    def cached(self, key: str) -> dict[str, Any] | None:
        return self.ledger.cache_get(key)

    def remember(self, key: str, payload: dict[str, Any]) -> None:
        self.ledger.cache_put(
            key, payload, self.now() + timedelta(days=self.settings.cache_ttl_days)
        )
