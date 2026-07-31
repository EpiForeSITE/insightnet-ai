(function () {
  "use strict";

  const DATA_URL = "./data/insightnet.json";
  const VIEWS = ["overview", "activity", "centers", "experts", "health"];
  const PROFILE_LABELS = {
    website: "Website",
    linkedin: "LinkedIn",
    github: "GitHub",
    twitter: "X / Twitter",
    bluesky: "Bluesky",
    google_scholar: "Google Scholar",
  };

  let snapshot = null;
  let organizationsById = new Map();

  const byId = (id) => document.getElementById(id);

  function escapeHtml(value) {
    return String(value ?? "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#039;");
  }

  function safeUrl(value) {
    if (typeof value !== "string" || !value.trim()) return "";
    try {
      const url = new URL(value, window.location.href);
      return ["http:", "https:"].includes(url.protocol) ? url.href : "";
    } catch (_error) {
      return "";
    }
  }

  function formatDate(value, includeTime = false) {
    if (!value) return "Date not supplied";
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return String(value);
    return new Intl.DateTimeFormat("en", {
      dateStyle: "medium",
      ...(includeTime ? { timeStyle: "short", timeZone: "UTC" } : {}),
    }).format(date);
  }

  function tagList(values = [], limit = 8) {
    if (!values.length) return "";
    return `<div class="tag-list">${values
      .slice(0, limit)
      .map((value) => `<span class="tag">${escapeHtml(value)}</span>`)
      .join("")}</div>`;
  }

  function profileLinks(record = {}) {
    const links = Object.entries(PROFILE_LABELS)
      .map(([field, label]) => {
        const url = safeUrl(record[field]);
        return url
          ? `<a href="${escapeHtml(url)}" target="_blank" rel="noopener noreferrer">${label}</a>`
          : "";
      })
      .filter(Boolean);
    return links.length ? `<div class="profile-links">${links.join("")}</div>` : "";
  }

  function centerName(id) {
    return organizationsById.get(id)?.name || "Unknown center";
  }

  function activityCard(item, compact = false) {
    const url = safeUrl(item.url);
    const title = escapeHtml(item.title || "Untitled update");
    const linkedTitle = url
      ? `<a href="${escapeHtml(url)}" target="_blank" rel="noopener noreferrer">${title}</a>`
      : title;
    return `
      <article class="${compact ? "card" : "activity-record"}">
        <div class="${compact ? "card-meta" : "record-meta"}">
          ${escapeHtml(centerName(item.organization_id))} ·
          ${escapeHtml(item.source_label || item.source_type || "Source")} ·
          ${escapeHtml(formatDate(item.published_at))}
        </div>
        <h3>${linkedTitle}</h3>
        ${item.summary ? `<p>${escapeHtml(item.summary)}</p>` : ""}
        ${tagList(item.keywords, compact ? 4 : 7)}
      </article>`;
  }

  function centerCard(org) {
    const label = org.acronym || org.location || "Network center";
    return `
      <article class="card">
        <div class="card-meta">${escapeHtml(label)}</div>
        <h3>${escapeHtml(org.name)}</h3>
        <p>${escapeHtml(org.summary || "Center profile")}</p>
        ${tagList(org.focus_areas, 5)}
        <div class="card-footer">
          <span class="card-meta">${org.researchers?.length || 0} researchers · ${org.activity_count || 0} records</span>
          <button type="button" data-open-center="${escapeHtml(org.id)}">Explore →</button>
        </div>
      </article>`;
  }

  function researcherCard(person, organizationName = "") {
    const role = [person.role, organizationName].filter(Boolean).join(" · ") || "Researcher";
    return `
      <article class="card researcher-card">
        <div class="researcher-role">${escapeHtml(role)}</div>
        <h3>${escapeHtml(person.full_name || "Unnamed researcher")}</h3>
        ${person.bio ? `<p>${escapeHtml(person.bio)}</p>` : ""}
        ${tagList(person.expertise?.length ? person.expertise : person.keywords, 7)}
        ${profileLinks(person)}
      </article>`;
  }

  function populateOverview() {
    const organizations = snapshot.organizations || [];
    const items = snapshot.items || [];
    byId("overview-empty").hidden = organizations.length > 0;
    byId("latest-activity").innerHTML = items.slice(0, 6).map((item) => activityCard(item, true)).join("");
    byId("center-grid").innerHTML = organizations.map(centerCard).join("");
  }

  function populateFilters() {
    const organizations = snapshot.organizations || [];
    const centerOptions = organizations
      .map((org) => `<option value="${escapeHtml(org.id)}">${escapeHtml(org.name)}</option>`)
      .join("");
    byId("activity-center").insertAdjacentHTML("beforeend", centerOptions);
    byId("center-select").innerHTML = centerOptions || '<option value="">No centers configured</option>';

    const sourceTypes = [...new Set((snapshot.items || []).map((item) => item.source_type).filter(Boolean))].sort();
    byId("activity-source").insertAdjacentHTML(
      "beforeend",
      sourceTypes
        .map((source) => `<option value="${escapeHtml(source)}">${escapeHtml(source.replaceAll("_", " "))}</option>`)
        .join(""),
    );
  }

  function renderActivity() {
    const query = byId("activity-query").value.trim().toLowerCase();
    const organizationId = byId("activity-center").value;
    const sourceType = byId("activity-source").value;
    const filtered = (snapshot.items || []).filter((item) => {
      const text = [item.title, item.summary, ...(item.keywords || [])].join(" ").toLowerCase();
      return (
        (!query || text.includes(query)) &&
        (!organizationId || item.organization_id === organizationId) &&
        (!sourceType || item.source_type === sourceType)
      );
    });
    byId("activity-count").textContent = `${filtered.length} record${filtered.length === 1 ? "" : "s"}`;
    byId("activity-list").innerHTML = filtered.length
      ? filtered.slice(0, 200).map((item) => activityCard(item)).join("")
      : '<div class="empty-state compact"><h3>No activity matches.</h3><p>Try a broader term or a different source.</p></div>';
  }

  function renderCenter(organizationId) {
    const org = organizationsById.get(organizationId);
    if (!org) {
      byId("center-detail").innerHTML =
        '<div class="empty-state"><h3>No centers configured yet.</h3><p>Add a center profile and run the daily refresh to populate this directory.</p></div>';
      return;
    }
    const social = { website: org.website, ...(org.social || {}) };
    const researchers = org.researchers || [];
    byId("center-detail").innerHTML = `
      <article class="center-hero">
        <p class="kicker">${escapeHtml(org.acronym || org.location || "InsightNet center")}</p>
        <h3>${escapeHtml(org.name)}</h3>
        ${org.location ? `<p class="record-meta">${escapeHtml(org.location)}</p>` : ""}
        <p class="center-summary">${escapeHtml(org.summary || "")}</p>
        ${tagList(org.focus_areas, 12)}
        ${profileLinks(social)}
      </article>
      <section class="researcher-section">
        <div class="section-heading">
          <div><p class="kicker">Research directory</p><h2>People at ${escapeHtml(org.name)}</h2></div>
          <span class="result-count">${researchers.length} profile${researchers.length === 1 ? "" : "s"}</span>
        </div>
        ${
          researchers.length
            ? `<div class="researcher-grid">${researchers.map((person) => researcherCard(person)).join("")}</div>`
            : '<div class="empty-state compact"><h3>No researchers added yet.</h3><p>Researcher profiles will appear here when they are added to this center.</p></div>'
        }
      </section>`;
  }

  function searchableText(...parts) {
    return parts
      .flat(Infinity)
      .filter(Boolean)
      .map(String)
      .join(" \n ");
  }

  function keywordTerms(query) {
    const trimmed = query.trim();
    if (!trimmed) throw new Error("Enter a topic to search.");
    if (trimmed.length > 120) throw new Error("Search terms are limited to 120 characters.");
    const terms = trimmed.toLowerCase().match(/[a-z0-9][a-z0-9-]*/g) || [];
    if (!terms.length) throw new Error("Enter at least one letter or number.");
    return [...new Set(terms)];
  }

  function keywordScore(terms, text, boosts = []) {
    const normalized = String(text || "").toLowerCase();
    if (!terms.every((term) => normalized.includes(term))) return 0;
    let score = terms.reduce((total, term) => total + normalized.split(term).length - 1, 0);
    for (const [value, weight] of boosts) {
      const boostText = String(value || "").toLowerCase();
      if (terms.every((term) => boostText.includes(term))) score += weight;
    }
    return score;
  }

  function searchExperts(query) {
    const terms = keywordTerms(query);
    const researchers = [];
    const organizations = [];
    const items = [];

    for (const org of snapshot.organizations || []) {
      const orgText = searchableText(
        org.name,
        org.acronym,
        org.summary,
        org.focus_areas,
        org.keywords,
        org.collected_overview,
      );
      const organizationScore = keywordScore(terms, orgText, [[org.name, 8]]);
      if (organizationScore) {
        organizations.push({ ...org, score: organizationScore });
      }
      for (const person of org.researchers || []) {
        const personText = searchableText(
          person.full_name,
          person.role,
          person.bio,
          person.expertise,
          person.keywords,
          org.name,
          org.focus_areas,
        );
        const researcherScore = keywordScore(terms, personText, [
          [person.full_name, 10],
          [searchableText(person.expertise), 6],
        ]);
        if (researcherScore) {
          researchers.push({
            ...person,
            organization_name: org.name,
            score: researcherScore,
          });
        }
      }
    }

    for (const item of snapshot.items || []) {
      const itemText = searchableText(item.title, item.summary, item.keywords, item.source_label);
      const itemScore = keywordScore(terms, itemText, [[item.title, 5]]);
      if (itemScore) {
        items.push({ ...item, score: itemScore });
      }
    }
    const sorter = (a, b) => b.score - a.score || String(a.full_name || a.name || a.title).localeCompare(String(b.full_name || b.name || b.title));
    return {
      researchers: researchers.sort(sorter),
      organizations: organizations.sort(sorter),
      items: items.sort(sorter),
    };
  }

  function renderExpertResults(results) {
    const total = results.researchers.length + results.organizations.length + results.items.length;
    byId("expert-summary").textContent = `${total} total match${total === 1 ? "" : "es"}`;
    byId("expert-results").innerHTML = `
      <section class="expert-group">
        <h3>Researchers <span class="count-pill">${results.researchers.length}</span></h3>
        ${
          results.researchers.length
            ? `<div class="researcher-grid">${results.researchers
                .slice(0, 40)
                .map((person) => researcherCard(person, person.organization_name))
                .join("")}</div>`
            : "<p class='result-count'>No researcher profiles match yet.</p>"
        }
      </section>
      <section class="expert-group">
        <h3>Centers <span class="count-pill">${results.organizations.length}</span></h3>
        ${
          results.organizations.length
            ? `<div class="center-grid">${results.organizations.slice(0, 20).map(centerCard).join("")}</div>`
            : "<p class='result-count'>No centers match this topic.</p>"
        }
      </section>
      <section class="expert-group">
        <h3>Activity <span class="count-pill">${results.items.length}</span></h3>
        ${
          results.items.length
            ? `<div class="activity-list">${results.items.slice(0, 40).map((item) => activityCard(item)).join("")}</div>`
            : "<p class='result-count'>No collected activity matches this topic.</p>"
        }
      </section>`;
  }

  function renderHealth() {
    const rows = snapshot.health || [];
    byId("health-empty").hidden = rows.length > 0;
    byId("health-body").innerHTML = rows
      .map(
        (row) => `
          <tr>
            <td>${escapeHtml(centerName(row.organization_id))}</td>
            <td>${escapeHtml(row.source_label)}</td>
            <td><span class="status-badge status-${escapeHtml(row.status)}">${escapeHtml(row.status)}</span></td>
            <td>${Number(row.items_found || 0)}</td>
            <td>${escapeHtml(row.message || "")}</td>
          </tr>`,
      )
      .join("");
  }

  function showView(view, updateHash = true) {
    const selected = VIEWS.includes(view) ? view : "overview";
    document.querySelectorAll("[data-view-panel]").forEach((panel) => {
      const active = panel.dataset.viewPanel === selected;
      panel.hidden = !active;
      panel.classList.toggle("is-active", active);
    });
    document.querySelectorAll("[data-view]").forEach((button) => {
      const active = button.dataset.view === selected;
      button.classList.toggle("is-active", active);
      button.setAttribute("aria-current", active ? "page" : "false");
    });
    if (updateHash && window.location.hash !== `#${selected}`) {
      window.history.pushState(null, "", `#${selected}`);
    }
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  function openCenter(organizationId) {
    byId("center-select").value = organizationId;
    renderCenter(organizationId);
    showView("centers");
  }

  function setMetadata() {
    const network = snapshot.network || {};
    const stats = snapshot.stats || {};
    document.title = "InsightNet Explorer";
    byId("network-title").textContent = "InsightNet Explorer";
    byId("network-description").textContent = network.description || "Scientific activity across the network.";
    byId("metric-centers").textContent = stats.organizations ?? snapshot.organizations?.length ?? 0;
    byId("metric-researchers").textContent = stats.researchers ?? 0;
    byId("metric-items").textContent = stats.items ?? snapshot.items?.length ?? 0;
    byId("metric-sources").textContent = stats.sources_ok ?? 0;

    const generated = new Date(snapshot.generated_at);
    const ageHours = (Date.now() - generated.getTime()) / 3_600_000;
    const freshness = byId("freshness");
    freshness.classList.add(ageHours <= 48 ? "is-current" : "is-stale");
    freshness.querySelector("span:last-child").textContent = Number.isNaN(ageHours)
      ? "Snapshot date unavailable"
      : `${ageHours <= 48 ? "Current snapshot" : "Snapshot may be stale"} · refreshed ${formatDate(snapshot.generated_at, true)}`;
    byId("last-updated").textContent = `Last checked ${formatDate(snapshot.generated_at, true)}`;
    byId("footer-generated").textContent = `Snapshot ${formatDate(snapshot.generated_at, true)}`;
  }

  function bindEvents() {
    document.addEventListener("click", (event) => {
      const viewButton = event.target.closest("[data-view]");
      if (viewButton) showView(viewButton.dataset.view);
      const goToButton = event.target.closest("[data-go-to]");
      if (goToButton) showView(goToButton.dataset.goTo);
      const centerButton = event.target.closest("[data-open-center]");
      if (centerButton) openCenter(centerButton.dataset.openCenter);
    });
    window.addEventListener("hashchange", () => showView(window.location.hash.slice(1), false));
    byId("activity-filters").addEventListener("input", renderActivity);
    byId("activity-filters").addEventListener("change", renderActivity);
    byId("center-select").addEventListener("change", (event) => renderCenter(event.target.value));
    byId("expert-form").addEventListener("submit", (event) => {
      event.preventDefault();
      const errorBox = byId("expert-error");
      errorBox.hidden = true;
      try {
        renderExpertResults(searchExperts(byId("expert-query").value));
      } catch (error) {
        errorBox.textContent = error.message;
        errorBox.hidden = false;
        byId("expert-summary").textContent = "";
        byId("expert-results").innerHTML = "";
      }
    });
  }

  async function initialize() {
    bindEvents();
    try {
      const response = await fetch(DATA_URL, { cache: "no-store" });
      if (!response.ok) throw new Error(`Data request returned ${response.status}`);
      snapshot = await response.json();
      organizationsById = new Map((snapshot.organizations || []).map((org) => [org.id, org]));
      setMetadata();
      populateOverview();
      populateFilters();
      renderActivity();
      renderCenter(snapshot.organizations?.[0]?.id || "");
      renderHealth();
      showView(window.location.hash.slice(1) || "overview", false);
    } catch (error) {
      const message = byId("app-message");
      message.textContent = `The network snapshot could not be loaded. ${error.message}`;
      message.hidden = false;
      byId("freshness").querySelector("span:last-child").textContent = "Snapshot unavailable";
    }
  }

  initialize();
})();
