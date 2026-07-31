from pathlib import Path

import pytest

from insightnet.config import ProfileError, load_profiles


def test_loads_network_settings_and_per_center_profiles(tmp_path: Path) -> None:
    central = tmp_path / "network.toml"
    fragments = tmp_path / "organizations"
    fragments.mkdir()
    central.write_text(
        """
        [network]
        name = "Test network"
        """,
        encoding="utf-8",
    )
    (fragments / "alpha.toml").write_text(
        """
        [organization]
        id = "alpha"
        name = "Alpha Center"
        focus_areas = ["epidemiology"]
        """,
        encoding="utf-8",
    )
    (fragments / "beta.toml").write_text(
        """
        [organization]
        id = "beta"
        name = "Beta Center"

        [[organization.researchers]]
        full_name = "Grace Hopper"
        expertise = ["computer science"]
        """,
        encoding="utf-8",
    )

    profiles = load_profiles(central, fragments)

    assert profiles["network"]["name"] == "Test network"
    assert [org["id"] for org in profiles["organizations"]] == ["alpha", "beta"]
    assert profiles["organizations"][1]["researchers"][0]["id"] == "grace-hopper"


def test_rejects_duplicate_center_ids(tmp_path: Path) -> None:
    network = tmp_path / "network.toml"
    profiles = tmp_path / "organizations"
    profiles.mkdir()
    network.write_text("[network]\nname = 'Test'\n", encoding="utf-8")
    (profiles / "one.toml").write_text(
        """
        [organization]
        id = "duplicate"
        name = "One"
        """,
        encoding="utf-8",
    )
    (profiles / "two.toml").write_text(
        """
        [organization]
        id = "duplicate"
        name = "Two"
        """,
        encoding="utf-8",
    )

    with pytest.raises(ProfileError, match="unique"):
        load_profiles(network, profiles)


def test_rejects_non_http_profile_links(tmp_path: Path) -> None:
    network = tmp_path / "network.toml"
    profiles = tmp_path / "organizations"
    profiles.mkdir()
    (profiles / "unsafe.toml").write_text(
        """
        [organization]
        name = "Unsafe Center"
        website = "javascript:alert(1)"
        """,
        encoding="utf-8",
    )

    with pytest.raises(ProfileError, match="http"):
        load_profiles(network, profiles)


def test_rejects_multiple_organizations_in_one_profile_file(tmp_path: Path) -> None:
    profiles = tmp_path / "organizations"
    profiles.mkdir()
    (profiles / "invalid.toml").write_text(
        """
        [[organizations]]
        name = "Not allowed"
        """,
        encoding="utf-8",
    )

    with pytest.raises(ProfileError, match="exactly one"):
        load_profiles(tmp_path / "network.toml", profiles)
