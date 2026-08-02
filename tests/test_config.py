from pathlib import Path

import pytest

from insightnet.config import ProfileError, load_profiles, orcid_id


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
        orcid = "https://orcid.org/0000-0002-1825-0097"
        """,
        encoding="utf-8",
    )

    profiles = load_profiles(central, fragments)

    assert profiles["network"]["name"] == "Test network"
    assert [org["id"] for org in profiles["organizations"]] == ["alpha", "beta"]
    researcher = profiles["organizations"][1]["researchers"][0]
    assert researcher["id"] == "grace-hopper"
    assert researcher["orcid"] == "https://orcid.org/0000-0002-1825-0097"
    assert researcher["orcid_id"] == "0000-0002-1825-0097"
    assert researcher["google_scholar"] == ""


def test_orcid_drives_the_derived_publication_profile_links(tmp_path: Path) -> None:
    profiles_dir = tmp_path / "organizations"
    profiles_dir.mkdir()
    (profiles_dir / "alpha.toml").write_text(
        """
        [organization]
        name = "Alpha"

        [[organization.researchers]]
        full_name = "With Orcid"
        orcid = "https://orcid.org/0000-0002-1825-0097"

        [[organization.researchers]]
        full_name = "Without Orcid"

        [[organization.researchers]]
        full_name = "Explicit Link"
        orcid = "https://orcid.org/0000-0002-1825-0098"
        pubmed = "https://pubmed.ncbi.nlm.nih.gov/?term=custom"
        """,
        encoding="utf-8",
    )

    researchers = load_profiles(tmp_path / "network.toml", profiles_dir)["organizations"][0][
        "researchers"
    ]
    derived, bare, explicit = researchers

    # Each derived link is an exact identifier lookup, never a name search.
    assert "0000-0002-1825-0097%5Bauid%5D" in derived["pubmed"]
    assert derived["europepmc"] == "https://europepmc.org/authors/0000-0002-1825-0097"
    assert "searchtype=orcid" in derived["arxiv"]
    # No ORCID means no derived links, because a name search is not this person.
    assert (bare["pubmed"], bare["europepmc"], bare["arxiv"]) == ("", "", "")
    # A hand-written link is never overwritten.
    assert explicit["pubmed"] == "https://pubmed.ncbi.nlm.nih.gov/?term=custom"


def test_rejects_an_unrecognizable_orcid(tmp_path: Path) -> None:
    profiles_dir = tmp_path / "organizations"
    profiles_dir.mkdir()
    (profiles_dir / "alpha.toml").write_text(
        """
        [organization]
        name = "Alpha"

        [[organization.researchers]]
        full_name = "Typo"
        orcid = "https://orcid.org/not-an-orcid"
        """,
        encoding="utf-8",
    )

    with pytest.raises(ProfileError, match="recognizable ORCID"):
        load_profiles(tmp_path / "network.toml", profiles_dir)


def test_works_collection_settings_default_and_validate(tmp_path: Path) -> None:
    network = tmp_path / "network.toml"
    profiles_dir = tmp_path / "organizations"
    profiles_dir.mkdir()
    network.write_text("[network]\nname = 'Test'\n", encoding="utf-8")

    settings = load_profiles(network, profiles_dir)["network"]

    assert settings["max_works_per_researcher"] == 100
    assert settings["works_retention_years"] == 15
    assert settings["abstract_max_chars"] == 1500

    network.write_text("[network]\nmax_works_per_researcher = 0\n", encoding="utf-8")
    with pytest.raises(ProfileError, match="at least 1"):
        load_profiles(network, profiles_dir)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("https://orcid.org/0000-0002-1825-0097", "0000-0002-1825-0097"),
        ("0000-0002-1825-009x", "0000-0002-1825-009X"),
        ("", ""),
        ("https://example.org/profile", ""),
    ],
)
def test_orcid_extraction(value: str, expected: str) -> None:
    assert orcid_id(value) == expected


def _tools_profile(tmp_path: Path, body: str) -> Path:
    profiles_dir = tmp_path / "organizations"
    profiles_dir.mkdir(exist_ok=True)
    (profiles_dir / "alpha.toml").write_text(
        f'[organization]\nname = "Alpha"\n{body}', encoding="utf-8"
    )
    return profiles_dir


def test_loads_tools_with_defaults_and_generated_ids(tmp_path: Path) -> None:
    profiles_dir = _tools_profile(
        tmp_path,
        """
        [[organization.tools]]
        name = "RespiLens"
        summary = "Dashboard for respiratory disease trends."
        url = "https://www.respilens.com/"
        category = "dashboard"
        keywords = ["Respiratory Disease", "Forecasting"]

        [[organization.tools]]
        name = "Planned Platform"
        status = "in-development"
        """,
    )

    tools = load_profiles(tmp_path / "network.toml", profiles_dir)["organizations"][0]["tools"]

    assert [tool["id"] for tool in tools] == ["respilens", "planned-platform"]
    assert tools[0]["category"] == "dashboard"
    assert tools[0]["status"] == "available"
    assert tools[0]["keywords"] == ["respiratory disease", "forecasting"]
    # A tool with no released URL is still a valid entry.
    assert (tools[1]["category"], tools[1]["status"], tools[1]["url"]) == (
        "other",
        "in-development",
        "",
    )


def test_rejects_an_unknown_tool_category(tmp_path: Path) -> None:
    profiles_dir = _tools_profile(
        tmp_path,
        '\n[[organization.tools]]\nname = "Thing"\ncategory = "widget"\n',
    )

    with pytest.raises(ProfileError, match="tool.category"):
        load_profiles(tmp_path / "network.toml", profiles_dir)


def test_rejects_a_nameless_tool(tmp_path: Path) -> None:
    profiles_dir = _tools_profile(tmp_path, '\n[[organization.tools]]\nsummary = "No name"\n')

    with pytest.raises(ProfileError, match="missing name"):
        load_profiles(tmp_path / "network.toml", profiles_dir)


def test_rejects_a_non_http_tool_link(tmp_path: Path) -> None:
    profiles_dir = _tools_profile(
        tmp_path,
        '\n[[organization.tools]]\nname = "Thing"\nurl = "javascript:alert(1)"\n',
    )

    with pytest.raises(ProfileError, match="http"):
        load_profiles(tmp_path / "network.toml", profiles_dir)


def test_rejects_duplicate_tool_ids(tmp_path: Path) -> None:
    profiles_dir = _tools_profile(
        tmp_path,
        """
        [[organization.tools]]
        name = "Same Tool"

        [[organization.tools]]
        name = "same tool"
        """,
    )

    with pytest.raises(ProfileError, match="Duplicate tool id"):
        load_profiles(tmp_path / "network.toml", profiles_dir)


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


def test_loads_partners_with_defaults_and_generated_ids(tmp_path: Path) -> None:
    profiles_dir = _tools_profile(
        tmp_path,
        """
        [[organization.partners]]
        name = "Utah Department of Health and Human Services"
        acronym = "UDHHS"
        type = "state"
        website = "https://dhhs.utah.gov/"
        location = "Utah"

        [[organization.partners]]
        name = "Tribal Health Directors"
        """,
    )

    partners = load_profiles(tmp_path / "network.toml", profiles_dir)["organizations"][0][
        "partners"
    ]

    assert [partner["id"] for partner in partners] == [
        "utah-department-of-health-and-human-services",
        "tribal-health-directors",
    ]
    assert partners[0]["type"] == "state"
    assert partners[0]["location"] == "Utah"
    # A partner with no public website is still a valid entry.
    assert (partners[1]["type"], partners[1]["website"], partners[1]["acronym"]) == (
        "other",
        "",
        "",
    )


def test_rejects_an_unknown_partner_type(tmp_path: Path) -> None:
    profiles_dir = _tools_profile(
        tmp_path,
        '\n[[organization.partners]]\nname = "Somewhere"\ntype = "municipal"\n',
    )

    with pytest.raises(ProfileError, match="partner.type"):
        load_profiles(tmp_path / "network.toml", profiles_dir)


def test_rejects_a_nameless_partner(tmp_path: Path) -> None:
    profiles_dir = _tools_profile(tmp_path, '\n[[organization.partners]]\ntype = "state"\n')

    with pytest.raises(ProfileError, match="missing name"):
        load_profiles(tmp_path / "network.toml", profiles_dir)


def test_rejects_a_non_http_partner_website(tmp_path: Path) -> None:
    profiles_dir = _tools_profile(
        tmp_path,
        '\n[[organization.partners]]\nname = "Somewhere"\nwebsite = "javascript:alert(1)"\n',
    )

    with pytest.raises(ProfileError, match="http"):
        load_profiles(tmp_path / "network.toml", profiles_dir)


def test_rejects_duplicate_partner_ids(tmp_path: Path) -> None:
    profiles_dir = _tools_profile(
        tmp_path,
        """
        [[organization.partners]]
        name = "Same Agency"

        [[organization.partners]]
        name = "same agency"
        """,
    )

    with pytest.raises(ProfileError, match="Duplicate partner id"):
        load_profiles(tmp_path / "network.toml", profiles_dir)


def test_every_configured_center_records_a_health_partner() -> None:
    """Every InsightNet center works with health partners, so none should be empty."""

    profiles = load_profiles()

    missing = [org["id"] for org in profiles["organizations"] if not org["partners"]]
    assert not missing, f"centers without health partners: {missing}"
