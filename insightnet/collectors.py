"""Public-source collectors used by the scheduled snapshot builder.

The collectors deliberately avoid private APIs and browser automation. Sources that
need credentials are skipped with a visible health message unless their optional
credential is present in the environment.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from time import mktime
from typing import Any
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser

import feedparser
import requests
from bs4 import BeautifulSoup
from dateutil import parser as date_parser
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from insightnet.text import clean_text, extract_keywords

USER_AGENT = "InsightNet-Research-Monitor/0.1 (+public scientific metadata aggregator)"


@dataclass
class CollectionResult:
    status: str = "ok"
    message: str = ""
    items: list[dict[str, Any]] = field(default_factory=list)
    overview: str = ""


def _datetime(value: Any) -> str:
    if not value:
        return ""
    try:
        if hasattr(value, "tm_year"):
            parsed = datetime.fromtimestamp(mktime(value), tz=UTC)
        elif isinstance(value, datetime):
            parsed = value
        else:
            parsed = date_parser.parse(str(value))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return parsed.astimezone(UTC).isoformat().replace("+00:00", "Z")
    except (TypeError, ValueError, OverflowError):
        return ""


def _item(
    *,
    title: str,
    url: str,
    summary: str = "",
    published_at: Any = "",
    authors: list[str] | None = None,
    keywords: list[str] | None = None,
) -> dict[str, Any]:
    title = clean_text(title, 300)
    summary = clean_text(summary, 800)
    parsed_url = urlparse(url)
    url = url if parsed_url.scheme in {"http", "https"} and parsed_url.netloc else ""
    return {
        "title": title or "Untitled update",
        "url": url,
        "summary": summary,
        "published_at": _datetime(published_at),
        "authors": authors or [],
        "keywords": extract_keywords([title, summary], keywords or []),
    }


class SourceClient:
    """HTTP client with retries, timeouts, and a cached robots.txt policy."""

    def __init__(self, timeout: int | None = None) -> None:
        self.timeout = timeout or int(os.getenv("INSIGHTNET_HTTP_TIMEOUT", "20"))
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": USER_AGENT,
                "Accept": "application/json, application/rss+xml, application/atom+xml, text/html;q=0.9, */*;q=0.5",
            }
        )
        retries = Retry(
            total=2,
            backoff_factor=0.6,
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=("GET",),
        )
        self.session.mount("https://", HTTPAdapter(max_retries=retries))
        self.session.mount("http://", HTTPAdapter(max_retries=retries))
        self._robots: dict[str, RobotFileParser | None] = {}

    def allowed(self, url: str) -> bool:
        parsed = urlparse(url)
        origin = f"{parsed.scheme}://{parsed.netloc}"
        if origin not in self._robots:
            robots_url = f"{origin}/robots.txt"
            try:
                response = self.session.get(robots_url, timeout=self.timeout)
                if response.status_code in {401, 403}:
                    policy = RobotFileParser(robots_url)
                    policy.disallow_all = True
                    self._robots[origin] = policy
                elif 400 <= response.status_code < 500:
                    self._robots[origin] = None
                else:
                    response.raise_for_status()
                    policy = RobotFileParser(robots_url)
                    policy.parse(response.text.splitlines())
                    self._robots[origin] = policy
            except requests.RequestException:
                # A missing robots file is not interpreted as a site-wide prohibition.
                self._robots[origin] = None
        policy = self._robots[origin]
        return policy is None or policy.can_fetch(USER_AGENT, url)

    def get(self, url: str, *, respect_robots: bool = True, **kwargs: Any) -> requests.Response:
        if respect_robots and not self.allowed(url):
            raise PermissionError(f"robots.txt does not allow collection from {url}")
        response = self.session.get(url, timeout=self.timeout, **kwargs)
        response.raise_for_status()
        return response


def collect_website(client: SourceClient, source: dict[str, Any]) -> CollectionResult:
    url = source.get("url", "")
    if not url:
        return CollectionResult(status="skipped", message="No website URL configured")
    response = client.get(url)
    soup = BeautifulSoup(response.text, "html.parser")
    for element in soup(["script", "style", "noscript", "svg"]):
        element.decompose()

    description_tag = soup.find("meta", attrs={"name": re.compile("description", re.IGNORECASE)})
    description = description_tag.get("content", "") if description_tag else ""
    main = soup.find("main") or soup.find("body")
    main_text = clean_text(main.get_text(" ", strip=True) if main else "", 1800)
    overview = clean_text(f"{description} {main_text}", 2000)

    items: list[dict[str, Any]] = []
    max_items = int(source.get("max_items", 20))
    for article in soup.find_all("article", limit=max_items):
        heading = article.find(["h1", "h2", "h3"]) or article.find("a")
        if not heading:
            continue
        anchor = heading if heading.name == "a" else heading.find("a")
        link = urljoin(response.url, anchor.get("href", "")) if anchor else response.url
        paragraph = article.find("p")
        time_tag = article.find("time")
        items.append(
            _item(
                title=heading.get_text(" ", strip=True),
                url=link,
                summary=paragraph.get_text(" ", strip=True) if paragraph else "",
                published_at=(time_tag.get("datetime") or time_tag.get_text(strip=True))
                if time_tag
                else "",
            )
        )
    return CollectionResult(
        items=items,
        overview=overview,
        message=f"Read page metadata and found {len(items)} article element(s)",
    )


def collect_rss(client: SourceClient, source: dict[str, Any]) -> CollectionResult:
    url = source.get("url", "")
    if not url:
        return CollectionResult(status="skipped", message="No RSS/Atom URL configured")
    response = client.get(url)
    feed = feedparser.parse(response.content)
    if feed.bozo and not feed.entries:
        raise ValueError(f"Feed could not be parsed: {feed.bozo_exception}")
    items = []
    for entry in feed.entries[: int(source.get("max_items", 20))]:
        published = (
            entry.get("published_parsed")
            or entry.get("updated_parsed")
            or entry.get("published", "")
        )
        authors = [author.get("name", "") for author in entry.get("authors", [])]
        items.append(
            _item(
                title=entry.get("title", "Untitled update"),
                url=entry.get("link", url),
                summary=entry.get("summary", entry.get("description", "")),
                published_at=published,
                authors=[author for author in authors if author],
                keywords=source.get("keywords", []),
            )
        )
    return CollectionResult(items=items, message=f"Read {len(items)} feed item(s)")


def collect_bluesky(client: SourceClient, source: dict[str, Any]) -> CollectionResult:
    handle = str(source.get("handle", "")).removeprefix("@").strip()
    if not handle:
        return CollectionResult(status="skipped", message="No Bluesky handle configured")
    endpoint = "https://public.api.bsky.app/xrpc/app.bsky.feed.getAuthorFeed"
    response = client.get(
        endpoint,
        respect_robots=False,
        params={"actor": handle, "limit": min(int(source.get("max_items", 20)), 100)},
    )
    items = []
    for row in response.json().get("feed", []):
        post = row.get("post", {})
        record = post.get("record", {})
        author = post.get("author", {})
        uri = post.get("uri", "")
        post_id = uri.rsplit("/", 1)[-1] if uri else ""
        profile_handle = author.get("handle", handle)
        text = record.get("text", "")
        items.append(
            _item(
                title=clean_text(text, 180) or "Bluesky post",
                url=f"https://bsky.app/profile/{profile_handle}/post/{post_id}",
                summary=text,
                published_at=record.get("createdAt", post.get("indexedAt", "")),
                authors=[author.get("displayName") or profile_handle],
                keywords=source.get("keywords", []),
            )
        )
    return CollectionResult(items=items, message=f"Read {len(items)} public post(s)")


def collect_github(client: SourceClient, source: dict[str, Any]) -> CollectionResult:
    owner = str(source.get("organization", source.get("owner", ""))).strip()
    if not owner:
        return CollectionResult(status="skipped", message="No GitHub organization/owner configured")
    headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
    token = os.getenv("GITHUB_TOKEN", "").strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    response = client.get(
        f"https://api.github.com/users/{owner}/repos",
        respect_robots=False,
        params={
            "sort": "pushed",
            "direction": "desc",
            "per_page": min(int(source.get("max_items", 20)), 100),
        },
        headers=headers,
    )
    items = []
    for repo in response.json():
        if repo.get("fork") and not source.get("include_forks", False):
            continue
        topics = repo.get("topics", [])
        items.append(
            _item(
                title=repo.get("name", "GitHub repository"),
                url=repo.get("html_url", f"https://github.com/{owner}"),
                summary=repo.get("description", ""),
                published_at=repo.get("pushed_at", repo.get("updated_at", "")),
                authors=[owner],
                keywords=list(source.get("keywords", [])) + topics,
            )
        )
    return CollectionResult(
        items=items, message=f"Read {len(items)} recently updated repository/repositories"
    )


def collect_google_scholar(client: SourceClient, source: dict[str, Any]) -> CollectionResult:
    """Collect a Scholar author profile through SerpAPI when configured.

    Google Scholar does not offer an official general-purpose API. The profile URL
    remains visible in the dashboard even when this optional collector is skipped.
    """

    author_id = str(source.get("author_id", "")).strip()
    if not author_id:
        return CollectionResult(status="skipped", message="No Google Scholar author id configured")
    api_key = os.getenv("SERPAPI_API_KEY", "").strip()
    if not api_key:
        return CollectionResult(
            status="skipped",
            message="SERPAPI_API_KEY is not set; Scholar profile link is still available",
        )
    response = client.get(
        "https://serpapi.com/search.json",
        respect_robots=False,
        params={
            "engine": "google_scholar_author",
            "author_id": author_id,
            "api_key": api_key,
            "num": min(int(source.get("max_items", 20)), 100),
            "sort": "pubdate",
        },
    )
    payload = response.json()
    if payload.get("error"):
        raise ValueError(payload["error"])
    items = []
    for article in payload.get("articles", [])[: int(source.get("max_items", 20))]:
        publication = article.get("publication", "")
        year = article.get("year", "")
        items.append(
            _item(
                title=article.get("title", "Publication"),
                url=article.get("link", article.get("cited_by", {}).get("link", "")),
                summary=publication,
                published_at=f"{year}-01-01" if str(year).isdigit() else "",
                authors=[source.get("researcher_name", "")],
                keywords=source.get("keywords", []),
            )
        )
    return CollectionResult(
        items=items, message=f"Read {len(items)} Scholar publication(s) via SerpAPI"
    )


COLLECTORS = {
    "website": collect_website,
    "rss": collect_rss,
    "atom": collect_rss,
    "bluesky": collect_bluesky,
    "github": collect_github,
    "google_scholar": collect_google_scholar,
}


def collect_source(client: SourceClient, source: dict[str, Any]) -> CollectionResult:
    source_type = source.get("type", "")
    if not source.get("enabled", True):
        return CollectionResult(status="skipped", message="Source is disabled in configuration")
    if source_type in {"twitter", "x", "linkedin"}:
        return CollectionResult(
            status="skipped",
            message=f"{source_type.title()} collection needs an approved API or RSS bridge; profile link only",
        )
    collector = COLLECTORS.get(source_type)
    if not collector:
        return CollectionResult(status="skipped", message=f"Unsupported source type: {source_type}")
    try:
        return collector(client, source)
    except PermissionError as exc:
        return CollectionResult(status="blocked", message=str(exc))
    except (requests.RequestException, ValueError, TypeError, KeyError) as exc:
        return CollectionResult(status="error", message=clean_text(str(exc), 300))
