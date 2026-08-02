(function () {
  "use strict";

  const PROFILES_URL = "./data/profiles.json";
  const ACTIVITY_URL = "./data/activity.json";
  const WORKS_URL = "./data/works.json";
  const VIEWS = ["overview", "tools", "works", "activity", "centers", "experts", "health"];
  const TOOL_CATEGORY_LABELS = {
    dashboard: "Dashboard",
    package: "Software package",
    platform: "Platform",
    model: "Model",
    dataset: "Dataset",
    application: "Application",
    other: "Resource",
  };
  const WORKS_PAGE_SIZE = 40;
  const CAROUSEL_DELAY = 6000;
  const PARTNER_TYPE_LABELS = {
    state: "State health agency",
    local: "Local health department",
    tribal: "Tribal health agency",
    federal: "Federal health agency",
    healthcare: "Health system",
    other: "Health partner",
  };
  const PROFILE_LABELS = {
    website: "Website",
    linkedin: "LinkedIn",
    github: "GitHub",
    twitter: "X / Twitter",
    bluesky: "Bluesky",
    google_scholar: "Google Scholar",
    orcid: "ORCID",
    pubmed: "PubMed",
    europepmc: "Europe PMC",
    arxiv: "arXiv",
    medrxiv: "medRxiv",
  };

  let snapshot = null;
  let activity = { items: [] };
  let works = null;
  let worksPromise = null;
  let organizationsById = new Map();
  let researchersById = new Map();
  let researcherByOrcid = new Map();
  let worksVisible = WORKS_PAGE_SIZE;
  let worksFiltered = [];
  let carouselIndex = 0;
  let carouselScrollTimer = 0;
  let partnerRoster = null;
  let carouselTimer = 0;
  let carouselStopped = false;
  let carouselHeld = false;

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

  // ----------------------------------------------------------------------------------
  // Tools and products
  // ----------------------------------------------------------------------------------

  function allTools() {
    return (snapshot?.organizations || []).flatMap((org) =>
      (org.tools || []).map((tool) => ({ ...tool, organization_id: org.id })),
    );
  }

  function toolText(tool) {
    return [tool.name, tool.summary, tool.category, ...(tool.keywords || [])]
      .filter(Boolean)
      .join(" ")
      .toLowerCase();
  }

  function toolCard(tool) {
    const url = safeUrl(tool.url);
    const name = escapeHtml(tool.name || "Unnamed tool");
    const linkedName = url
      ? `<a href="${escapeHtml(url)}" target="_blank" rel="noopener noreferrer">${name}</a>`
      : name;
    const repository = safeUrl(tool.repository);
    return `
      <article class="card tool-card">
        <div class="card-meta tool-meta">
          <span class="tool-category">${escapeHtml(
            TOOL_CATEGORY_LABELS[tool.category] || "Resource",
          )}</span>
          ${
            tool.status === "in-development"
              ? '<span class="tool-status">In development</span>'
              : ""
          }
        </div>
        <h3>${linkedName}</h3>
        ${tool.summary ? `<p>${escapeHtml(tool.summary)}</p>` : ""}
        ${tagList(tool.keywords, 5)}
        <div class="card-footer tool-footer">
          <span class="card-meta">${escapeHtml(centerName(tool.organization_id))}</span>
          ${
            repository && repository !== url
              ? `<a class="tool-repo" href="${escapeHtml(repository)}" target="_blank" rel="noopener noreferrer">Source ↗</a>`
              : ""
          }
        </div>
      </article>`;
  }

  function populateToolFilters() {
    byId("tools-center").insertAdjacentHTML(
      "beforeend",
      (snapshot.organizations || [])
        .filter((org) => (org.tools || []).length)
        .map((org) => `<option value="${escapeHtml(org.id)}">${escapeHtml(org.name)}</option>`)
        .join(""),
    );
    const categories = [...new Set(allTools().map((tool) => tool.category))]
      .map((category) => [category, TOOL_CATEGORY_LABELS[category] || category])
      .sort((a, b) => a[1].localeCompare(b[1]));
    byId("tools-category").insertAdjacentHTML(
      "beforeend",
      categories
        .map(
          ([category, label]) =>
            `<option value="${escapeHtml(category)}">${escapeHtml(label)}</option>`,
        )
        .join(""),
    );
  }

  function renderTools() {
    const query = byId("tools-query").value.trim().toLowerCase();
    const organizationId = byId("tools-center").value;
    const category = byId("tools-category").value;
    const filtered = allTools().filter(
      (tool) =>
        (!organizationId || tool.organization_id === organizationId) &&
        (!category || tool.category === category) &&
        (!query || toolText(tool).includes(query)),
    );
    byId("tools-count").textContent = `${filtered.length} tool${filtered.length === 1 ? "" : "s"}`;
    byId("tools-list").innerHTML = filtered.length
      ? filtered.map(toolCard).join("")
      : '<div class="empty-state compact"><h3>No tools match.</h3><p>Try a broader term, or clear the center and category filters.</p></div>';
  }

  // ----------------------------------------------------------------------------------
  // Publications
  // ----------------------------------------------------------------------------------

  function authorLine(work) {
    const authors = work.authors || [];
    if (!authors.length) return "";
    const shown = authors.slice(0, 10).map((author) => {
      const name = escapeHtml(author.name || "");
      return researcherByOrcid.has(author.orcid)
        ? `<strong class="network-author">${name}</strong>`
        : name;
    });
    const remaining = (work.author_count || authors.length) - shown.length;
    return `<p class="work-authors">${shown.join(", ")}${
      remaining > 0 ? ` <span class="muted">+${remaining} more</span>` : ""
    }</p>`;
  }

  // A DOI's own slashes are part of the identifier and must stay readable, so they are
  // restored after escaping everything else.
  const encodeDoi = (doi) => encodeURIComponent(doi).replaceAll("%2F", "/");

  function identifierLinks(work) {
    const badges = [];
    if (work.doi) {
      badges.push(
        `<a href="https://doi.org/${encodeDoi(work.doi)}" target="_blank" rel="noopener noreferrer">DOI</a>`,
      );
    }
    if (work.pmid) {
      badges.push(
        `<a href="https://pubmed.ncbi.nlm.nih.gov/${encodeURIComponent(work.pmid)}/" target="_blank" rel="noopener noreferrer">PMID ${escapeHtml(work.pmid)}</a>`,
      );
    }
    if (work.pmcid) {
      badges.push(
        `<a href="https://www.ncbi.nlm.nih.gov/pmc/articles/${encodeURIComponent(work.pmcid)}/" target="_blank" rel="noopener noreferrer">${escapeHtml(work.pmcid)}</a>`,
      );
    }
    if (work.arxiv_id) {
      badges.push(
        `<a href="https://arxiv.org/abs/${encodeURIComponent(work.arxiv_id)}" target="_blank" rel="noopener noreferrer">arXiv ${escapeHtml(work.arxiv_id)}</a>`,
      );
    }
    return badges.length ? `<div class="work-ids">${badges.join("")}</div>` : "";
  }

  function workCard(work) {
    const url = safeUrl(work.url);
    const title = escapeHtml(work.title || "Untitled work");
    const linkedTitle = url
      ? `<a href="${escapeHtml(url)}" target="_blank" rel="noopener noreferrer">${title}</a>`
      : title;
    const centers = (work.organization_ids || []).map(centerName).filter(Boolean);
    const people = (work.researcher_ids || [])
      .map((id) => researchersById.get(id)?.full_name)
      .filter(Boolean);
    const venue = work.preprint_server || work.venue;
    const meta = [
      work.published_at ? formatDate(work.published_at) : String(work.year || ""),
      venue,
      centers.join(", "),
    ]
      .filter(Boolean)
      .map(escapeHtml)
      .join(" · ");

    return `
      <article class="work-record">
        <div class="record-meta">
          <span class="work-type work-type-${escapeHtml(work.type || "article")}">${
            work.type === "preprint" ? "Preprint" : "Article"
          }</span>
          ${meta}
        </div>
        <h3>${linkedTitle}</h3>
        ${authorLine(work)}
        ${
          work.abstract
            ? `<p class="work-abstract">${escapeHtml(work.abstract)}</p>
               <button class="text-action work-toggle" type="button" data-toggle-abstract>Show full abstract</button>`
            : '<p class="work-abstract is-missing">No abstract was published for this record.</p>'
        }
        ${tagList(work.keywords, 8)}
        ${identifierLinks(work)}
        ${
          people.length
            ? `<p class="work-people">In this network: ${escapeHtml(people.join(", "))}</p>`
            : ""
        }
      </article>`;
  }

  function populateWorksFilters() {
    const researcherOptions = [...researchersById.values()]
      .filter((person) => (works.works_per_researcher || {})[person.id])
      .sort((a, b) => a.full_name.localeCompare(b.full_name))
      .map(
        (person) =>
          `<option value="${escapeHtml(person.id)}">${escapeHtml(person.full_name)} (${
            works.works_per_researcher[person.id]
          })</option>`,
      )
      .join("");
    byId("works-researcher").insertAdjacentHTML("beforeend", researcherOptions);

    byId("works-center").insertAdjacentHTML(
      "beforeend",
      (snapshot.organizations || [])
        .map((org) => `<option value="${escapeHtml(org.id)}">${escapeHtml(org.name)}</option>`)
        .join(""),
    );

    const currentYear = new Date().getFullYear();
    byId("works-year").insertAdjacentHTML(
      "beforeend",
      [currentYear - 1, currentYear - 3, currentYear - 5, currentYear - 10]
        .map((year) => `<option value="${year}">${year} or later</option>`)
        .join(""),
    );
  }

  function renderWorks(reset = true) {
    if (!works) return;
    if (reset) {
      const query = byId("works-query").value.trim().toLowerCase();
      const organizationId = byId("works-center").value;
      const researcherId = byId("works-researcher").value;
      const type = byId("works-type").value;
      const since = Number(byId("works-year").value) || 0;
      worksVisible = WORKS_PAGE_SIZE;
      worksFiltered = (works.works || []).filter((work) => {
        if (organizationId && !(work.organization_ids || []).includes(organizationId)) return false;
        if (researcherId && !(work.researcher_ids || []).includes(researcherId)) return false;
        if (type && work.type !== type) return false;
        if (since && Number(work.year || 0) < since) return false;
        if (!query) return true;
        return workText(work).includes(query);
      });
    }

    const page = worksFiltered.slice(0, worksVisible);
    byId("works-count").textContent = `${worksFiltered.length.toLocaleString()} publication${
      worksFiltered.length === 1 ? "" : "s"
    }${worksFiltered.length > page.length ? ` · showing ${page.length}` : ""}`;
    byId("works-list").innerHTML = page.length
      ? page.map(workCard).join("")
      : '<div class="empty-state compact"><h3>No publications match.</h3><p>Try a broader term, a different center, or a wider year range.</p></div>';
    byId("works-more").hidden = worksFiltered.length <= worksVisible;
  }

  function workText(work) {
    if (!work._text) {
      work._text = [
        work.title,
        work.abstract,
        work.venue,
        work.preprint_server,
        ...(work.keywords || []),
        ...(work.authors || []).map((author) => author.name),
      ]
        .filter(Boolean)
        .join(" ")
        .toLowerCase();
    }
    return work._text;
  }

  // ----------------------------------------------------------------------------------
  // Directory rendering
  // ----------------------------------------------------------------------------------

  function plural(count, noun) {
    return `${count} ${noun}${count === 1 ? "" : "s"}`;
  }

  function centerCard(org) {
    const label = org.acronym || org.location || "Network center";
    const counts = [
      plural(org.researchers?.length || 0, "researcher"),
      plural(org.tools?.length || 0, "tool"),
      plural(org.partners?.length || 0, "partner"),
    ].join(" · ");
    return `
      <article class="card">
        <div class="card-meta">${escapeHtml(label)}</div>
        <h3>${escapeHtml(org.name)}</h3>
        <p>${escapeHtml(org.summary || "Center profile")}</p>
        ${tagList(org.focus_areas, 5)}
        <div class="card-footer">
          <span class="card-meta">${counts}</span>
          <button type="button" data-open-center="${escapeHtml(org.id)}">Explore →</button>
        </div>
      </article>`;
  }

  // ----------------------------------------------------------------------------------
  // Centers carousel
  // ----------------------------------------------------------------------------------

  // The track is a real scroller, so pointer, trackpad, and button navigation all move
  // the same scrollLeft. How many cards fit changes with the viewport, so the controls
  // work in pages of whatever is currently visible rather than in fixed card counts.
  function carouselSlides() {
    return [...byId("center-carousel").querySelectorAll(".carousel-slide")];
  }

  function carouselMetrics() {
    const track = byId("center-carousel");
    const slides = carouselSlides();
    const stride =
      slides.length > 1 ? slides[1].offsetLeft - slides[0].offsetLeft : slides[0]?.offsetWidth || 0;
    const perView = stride ? Math.max(1, Math.round(track.clientWidth / stride)) : 1;
    return {
      track,
      pageStride: stride * perView,
      pageCount: Math.max(1, Math.ceil(slides.length / perView)),
      perView,
    };
  }

  // The final page is usually a partial one, so its scroll position is the end of the
  // track rather than a whole number of pages. Treating "scrolled to the end" as the
  // last page keeps the final dot reachable.
  function currentPage(metrics) {
    const { track, pageStride, pageCount } = metrics;
    if (!pageStride) return 0;
    if (track.scrollLeft >= track.scrollWidth - track.clientWidth - 2) return pageCount - 1;
    return Math.min(pageCount - 1, Math.round(track.scrollLeft / pageStride));
  }

  function renderDots(pageCount, perView) {
    const total = carouselSlides().length;
    byId("carousel-dots").innerHTML = Array.from({ length: pageCount }, (_, page) => {
      const first = page * perView + 1;
      const last = Math.min((page + 1) * perView, total);
      const label = first === last ? `center ${first}` : `centers ${first} to ${last}`;
      return `<button class="carousel-dot" type="button" data-slide="${page}">
                <span class="sr-only">Show ${label} of ${total}</span>
              </button>`;
    }).join("");
  }

  function updateIndicators(page, metrics) {
    byId("carousel-dots")
      .querySelectorAll("button")
      .forEach((dot, position) => {
        const active = position === page;
        dot.classList.toggle("is-active", active);
        dot.setAttribute("aria-current", active ? "true" : "false");
      });
    byId("carousel-previous").disabled = page <= 0;
    byId("carousel-next").disabled = page >= metrics.pageCount - 1;
  }

  function syncCarousel() {
    const metrics = carouselMetrics();
    if (byId("carousel-dots").childElementCount !== metrics.pageCount) {
      renderDots(metrics.pageCount, metrics.perView);
    }
    carouselIndex = currentPage(metrics);
    updateIndicators(carouselIndex, metrics);
  }

  function goToPage(page) {
    const metrics = carouselMetrics();
    if (!carouselSlides().length) return;
    const target = Math.max(0, Math.min(page, metrics.pageCount - 1));
    // The indicators follow the request rather than the animation, so rapid clicks keep
    // advancing instead of re-reading a scroll position that is still in flight.
    carouselIndex = target;
    updateIndicators(target, metrics);
    metrics.track.scrollTo({ left: target * metrics.pageStride });
    // Navigating by hand restarts the countdown, so the next automatic move is never
    // half a beat behind the reader's own click.
    if (carouselTimer) startCarousel();
  }

  function renderCarousel() {
    const organizations = snapshot.organizations || [];
    byId("center-carousel").innerHTML = organizations
      .map(
        (org) =>
          `<div class="carousel-slide" role="group" aria-roledescription="slide" aria-label="${escapeHtml(
            org.name,
          )}">${centerCard(org)}</div>`,
      )
      .join("");
    byId("carousel-dots").innerHTML = "";
    byId("center-carousel-region").hidden = !organizations.length;
    syncCarousel();
    startCarousel();
  }

  // Rotation ------------------------------------------------------------------------
  //
  // The banner advances on its own, but never while someone is reading or working with
  // it: hovering, focusing, dragging the track, switching views or tabs all hold it, and
  // the toggle stops it for good. A reduced-motion preference opts out entirely.
  const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)");

  function carouselCanRun() {
    return (
      !carouselStopped &&
      !carouselHeld &&
      !reducedMotion.matches &&
      !document.hidden &&
      !byId("center-carousel-region").hidden &&
      !byId("view-overview").hidden &&
      carouselMetrics().pageCount > 1
    );
  }

  function stopCarousel() {
    window.clearInterval(carouselTimer);
    carouselTimer = 0;
  }

  function startCarousel() {
    stopCarousel();
    if (!carouselCanRun()) return;
    carouselTimer = window.setInterval(() => {
      if (!carouselCanRun()) {
        stopCarousel();
        return;
      }
      const { pageCount } = carouselMetrics();
      goToPage(carouselIndex + 1 >= pageCount ? 0 : carouselIndex + 1);
    }, CAROUSEL_DELAY);
  }

  // Holding is for transient reasons (a hover, a keyboard focus); the toggle is the
  // reader's explicit choice and outlives them.
  function holdCarousel(held) {
    carouselHeld = held;
    if (held) stopCarousel();
    else startCarousel();
  }

  function carouselParts() {
    return [byId("center-carousel-region"), byId("carousel-toggle").parentElement];
  }

  // Leaving one part of the carousel is not leaving the carousel: a reader can tab into
  // the track and then move the mouse away, or hover the buttons while the track holds
  // focus. Rotation only resumes once neither the pointer nor the keyboard is on it.
  function releaseCarousel() {
    holdCarousel(
      carouselParts().some(
        (part) => part.matches(":hover") || part.contains(document.activeElement),
      ),
    );
  }

  function setCarouselStopped(stopped) {
    carouselStopped = stopped;
    const toggle = byId("carousel-toggle");
    toggle.setAttribute(
      "aria-label",
      stopped ? "Play the centers carousel" : "Pause the centers carousel",
    );
    byId("carousel-toggle-icon").textContent = stopped ? "▶" : "❙❙";
    // A stopped banner is safe to announce; a moving one would interrupt constantly.
    byId("center-carousel-region").setAttribute("aria-live", stopped ? "polite" : "off");
    if (stopped) stopCarousel();
    else startCarousel();
  }

  // ----------------------------------------------------------------------------------
  // Health partners
  // ----------------------------------------------------------------------------------

  // A health department can partner with more than one center, so partners are merged by
  // identity and every center that named them is listed on the card. The merged roster is
  // built once, which also lets each entry keep its own search text.
  function allPartners() {
    if (partnerRoster) return partnerRoster;
    const merged = new Map();
    for (const org of snapshot?.organizations || []) {
      for (const partner of org.partners || []) {
        const key = (partner.website || partner.name).toLowerCase();
        const existing = merged.get(key);
        if (existing) {
          existing.organization_ids.push(org.id);
        } else {
          merged.set(key, { ...partner, organization_ids: [org.id] });
        }
      }
    }
    partnerRoster = [...merged.values()].sort((a, b) => a.name.localeCompare(b.name));
    return partnerRoster;
  }

  function partnerCard(partner, showCenters = true) {
    const url = safeUrl(partner.website);
    const name = escapeHtml(partner.name);
    const linkedName = url
      ? `<a href="${escapeHtml(url)}" target="_blank" rel="noopener noreferrer">${name}</a>`
      : name;
    const place = [partner.acronym, partner.location].filter(Boolean).join(" · ");
    return `
      <article class="partner-card">
        <span class="partner-type partner-type-${escapeHtml(partner.type || "other")}">${escapeHtml(
          PARTNER_TYPE_LABELS[partner.type] || PARTNER_TYPE_LABELS.other,
        )}</span>
        <h3>${linkedName}</h3>
        ${place ? `<p>${escapeHtml(place)}</p>` : ""}
        ${partner.summary ? `<p>${escapeHtml(partner.summary)}</p>` : ""}
        ${
          showCenters
            ? `<p class="partner-centers">Works with ${escapeHtml(
                (partner.organization_ids || [])
                  .map((id) => organizationsById.get(id)?.acronym || centerName(id))
                  .join(", "),
              )}</p>`
            : ""
        }
      </article>`;
  }

  // Readers look for partners by place as often as by name — "Utah", "county health",
  // "Kaiser" — so the searchable text carries the partner's own location, and the type is
  // matched by its label rather than its stored keyword. Centers contribute their name
  // but not their location: a center working across two states would otherwise make each
  // of its partners answer to a state it has nothing to do with.
  function partnerText(partner) {
    if (!partner._text) {
      partner._text = [
        partner.name,
        partner.acronym,
        partner.location,
        partner.summary,
        PARTNER_TYPE_LABELS[partner.type] || "",
        ...(partner.organization_ids || []).flatMap((id) => {
          const org = organizationsById.get(id);
          return [org?.name, org?.acronym];
        }),
      ]
        .filter(Boolean)
        .join(" ")
        .toLowerCase();
    }
    return partner._text;
  }

  function populatePartnerFilters() {
    const partners = allPartners();
    const types = [...new Set(partners.map((partner) => partner.type))]
      .map((type) => [type, PARTNER_TYPE_LABELS[type] || type])
      .sort((a, b) => a[1].localeCompare(b[1]));
    byId("partners-type").insertAdjacentHTML(
      "beforeend",
      types
        .map(([type, label]) => `<option value="${escapeHtml(type)}">${escapeHtml(label)}</option>`)
        .join(""),
    );
    byId("partners-center").insertAdjacentHTML(
      "beforeend",
      (snapshot.organizations || [])
        .filter((org) => (org.partners || []).length)
        .map((org) => `<option value="${escapeHtml(org.id)}">${escapeHtml(org.name)}</option>`)
        .join(""),
    );
  }

  function renderPartners() {
    const query = byId("partners-query").value.trim().toLowerCase();
    const type = byId("partners-type").value;
    const organizationId = byId("partners-center").value;
    const partners = allPartners().filter(
      (partner) =>
        (!type || partner.type === type) &&
        (!organizationId || partner.organization_ids.includes(organizationId)) &&
        (!query || partnerText(partner).includes(query)),
    );
    byId("partners-count").textContent = plural(partners.length, "partner");
    byId("partners-list").innerHTML = partners.length
      ? partners.map((partner) => partnerCard(partner)).join("")
      : '<div class="empty-state compact"><h3>No partners match.</h3><p>Try a broader term, a different type, or clear the center filter.</p></div>';
  }

  function researcherCard(person, organizationName = "") {
    const role = [person.role, organizationName].filter(Boolean).join(" · ") || "Researcher";
    const count = works?.works_per_researcher?.[person.id] || 0;
    return `
      <article class="card researcher-card">
        <div class="researcher-role">${escapeHtml(role)}</div>
        <h3>${escapeHtml(person.full_name || "Unnamed researcher")}</h3>
        ${
          person.matched_via_works_only
            ? '<p class="match-reason">Matched through their publications rather than their profile.</p>'
            : ""
        }
        ${person.bio ? `<p>${escapeHtml(person.bio)}</p>` : ""}
        ${tagList(person.expertise?.length ? person.expertise : person.keywords, 7)}
        ${
          count
            ? `<button class="text-action" type="button" data-open-works="${escapeHtml(person.id)}">${count} publication${count === 1 ? "" : "s"} →</button>`
            : ""
        }
        ${profileLinks(person)}
      </article>`;
  }

  function populateOverview() {
    const organizations = snapshot.organizations || [];
    const items = activity.items || [];
    byId("overview-empty").hidden = organizations.length > 0;
    byId("latest-activity").innerHTML = items
      .slice(0, 6)
      .map((item) => activityCard(item, true))
      .join("");
    renderCarousel();
  }

  function populateFilters() {
    const organizations = snapshot.organizations || [];
    const centerOptions = organizations
      .map((org) => `<option value="${escapeHtml(org.id)}">${escapeHtml(org.name)}</option>`)
      .join("");
    byId("activity-center").insertAdjacentHTML("beforeend", centerOptions);
    byId("center-select").innerHTML =
      centerOptions || '<option value="">No centers configured</option>';

    const sourceTypes = [
      ...new Set((activity.items || []).map((item) => item.source_type).filter(Boolean)),
    ].sort();
    byId("activity-source").insertAdjacentHTML(
      "beforeend",
      sourceTypes
        .map(
          (source) =>
            `<option value="${escapeHtml(source)}">${escapeHtml(source.replaceAll("_", " "))}</option>`,
        )
        .join(""),
    );
  }

  function renderActivity() {
    const query = byId("activity-query").value.trim().toLowerCase();
    const organizationId = byId("activity-center").value;
    const sourceType = byId("activity-source").value;
    const filtered = (activity.items || []).filter((item) => {
      const text = [item.title, item.summary, ...(item.keywords || [])].join(" ").toLowerCase();
      return (
        (!query || text.includes(query)) &&
        (!organizationId || item.organization_id === organizationId) &&
        (!sourceType || item.source_type === sourceType)
      );
    });
    byId("activity-count").textContent = `${filtered.length} record${filtered.length === 1 ? "" : "s"}`;
    byId("activity-list").innerHTML = filtered.length
      ? filtered
          .slice(0, 200)
          .map((item) => activityCard(item))
          .join("")
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
      ${
        (org.tools || []).length
          ? `<section class="researcher-section">
              <div class="section-heading">
                <div><p class="kicker">Built here</p><h2>Tools &amp; products</h2></div>
                <span class="result-count">${org.tools.length} tool${org.tools.length === 1 ? "" : "s"}</span>
              </div>
              <div class="tools-grid">${org.tools
                .map((tool) => toolCard({ ...tool, organization_id: org.id }))
                .join("")}</div>
            </section>`
          : ""
      }
      ${
        (org.partners || []).length
          ? `<section class="researcher-section">
              <div class="section-heading">
                <div><p class="kicker">Working together</p><h2>Health partners</h2></div>
                <span class="result-count">${plural(org.partners.length, "partner")}</span>
              </div>
              <div class="partner-grid">${org.partners
                .map((partner) => partnerCard(partner, false))
                .join("")}</div>
            </section>`
          : ""
      }
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

  // ----------------------------------------------------------------------------------
  // Expertise search
  // ----------------------------------------------------------------------------------

  function searchableText(...parts) {
    return parts.flat(Infinity).filter(Boolean).map(String).join(" \n ");
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
    const matchedWorks = [];
    const worksByResearcher = new Map();

    for (const work of works?.works || []) {
      const score = keywordScore(terms, workText(work), [
        [work.title, 6],
        [searchableText(work.keywords), 4],
      ]);
      if (score) {
        matchedWorks.push({ ...work, score });
        for (const researcherId of work.researcher_ids || []) {
          worksByResearcher.set(researcherId, (worksByResearcher.get(researcherId) || 0) + score);
        }
      }
    }

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
        // Publications count toward a researcher's score, so someone who has published
        // on a topic surfaces even when their written profile never mentions it.
        const profileScore = keywordScore(terms, personText, [
          [person.full_name, 10],
          [searchableText(person.expertise), 6],
        ]);
        const publicationScore = worksByResearcher.get(person.id) || 0;
        const researcherScore = profileScore + Math.min(publicationScore, 40);
        if (researcherScore) {
          researchers.push({
            ...person,
            organization_name: org.name,
            matched_via_works_only: !profileScore && publicationScore > 0,
            score: researcherScore,
          });
        }
      }
    }

    const tools = [];
    for (const tool of allTools()) {
      const score = keywordScore(terms, toolText(tool), [
        [tool.name, 8],
        [searchableText(tool.keywords), 5],
      ]);
      if (score) {
        tools.push({ ...tool, score });
      }
    }

    const partners = [];
    for (const partner of allPartners()) {
      const score = keywordScore(terms, partnerText(partner), [
        [partner.name, 8],
        [partner.location, 5],
      ]);
      if (score) {
        partners.push({ ...partner, score });
      }
    }

    for (const item of activity.items || []) {
      const itemText = searchableText(item.title, item.summary, item.keywords, item.source_label);
      const itemScore = keywordScore(terms, itemText, [[item.title, 5]]);
      if (itemScore) {
        items.push({ ...item, score: itemScore });
      }
    }

    const sorter = (a, b) =>
      b.score - a.score ||
      String(a.full_name || a.name || a.title).localeCompare(String(b.full_name || b.name || b.title));
    return {
      researchers: researchers.sort(sorter),
      organizations: organizations.sort(sorter),
      tools: tools.sort(sorter),
      partners: partners.sort(sorter),
      works: matchedWorks.sort(sorter),
      items: items.sort(sorter),
    };
  }

  function renderExpertResults(results) {
    const total =
      results.researchers.length +
      results.organizations.length +
      results.tools.length +
      results.partners.length +
      results.works.length +
      results.items.length;
    byId("expert-summary").textContent = `${total.toLocaleString()} total match${total === 1 ? "" : "es"}`;
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
        <h3>Tools &amp; products <span class="count-pill">${results.tools.length}</span></h3>
        ${
          results.tools.length
            ? `<div class="tools-grid">${results.tools.slice(0, 12).map(toolCard).join("")}</div>`
            : "<p class='result-count'>No tools match this topic.</p>"
        }
      </section>
      <section class="expert-group">
        <h3>Publications <span class="count-pill">${results.works.length}</span></h3>
        ${
          results.works.length
            ? `<div class="works-list">${results.works.slice(0, 25).map(workCard).join("")}</div>
               ${
                 results.works.length > 25
                   ? `<p class="result-count">Showing 25 of ${results.works.length}. <button class="text-action" type="button" data-go-to="works">Browse all publications →</button></p>`
                   : ""
               }`
            : `<p class='result-count'>${
                works ? "No publications match this topic." : "Publications are still loading…"
              }</p>`
        }
      </section>
      <section class="expert-group">
        <h3>Health partners <span class="count-pill">${results.partners.length}</span></h3>
        ${
          results.partners.length
            ? `<div class="partner-grid">${results.partners
                .slice(0, 12)
                .map((partner) => partnerCard(partner))
                .join("")}</div>`
            : "<p class='result-count'>No health partners match this topic.</p>"
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
            ? `<div class="activity-list">${results.items
                .slice(0, 40)
                .map((item) => activityCard(item))
                .join("")}</div>`
            : "<p class='result-count'>No collected activity matches this topic.</p>"
        }
      </section>`;
  }

  const HEALTH_ORDER = { error: 0, blocked: 1, ok: 2, skipped: 3 };

  function renderHealth() {
    // One row per researcher and source runs into the hundreds, so anything needing
    // attention is listed first rather than buried among healthy and skipped checks.
    const rows = [...(snapshot.health || []), ...(works?.health || [])].sort(
      (a, b) =>
        (HEALTH_ORDER[a.status] ?? 9) - (HEALTH_ORDER[b.status] ?? 9) ||
        String(a.source_label).localeCompare(String(b.source_label)),
    );
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

  // ----------------------------------------------------------------------------------
  // Navigation and wiring
  // ----------------------------------------------------------------------------------

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
    // Slide widths are only measurable once the panel is on screen, so the carousel
    // indicators are recalculated whenever the overview becomes visible.
    if (selected === "overview" && snapshot) {
      syncCarousel();
      startCarousel();
    } else {
      stopCarousel();
    }
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  function openCenter(organizationId) {
    byId("center-select").value = organizationId;
    renderCenter(organizationId);
    showView("centers");
  }

  async function openResearcherWorks(researcherId) {
    showView("works");
    await worksPromise;
    byId("works-researcher").value = researcherId;
    byId("works-query").value = "";
    byId("works-center").value = "";
    byId("works-type").value = "";
    byId("works-year").value = "";
    renderWorks();
  }

  function setMetadata() {
    const network = snapshot.network || {};
    const stats = snapshot.stats || {};
    document.title = "InsightNet Explorer";
    byId("network-title").textContent = "InsightNet Explorer";
    byId("network-description").textContent =
      network.description || "Scientific activity across the network.";
    byId("metric-centers").textContent = stats.organizations ?? snapshot.organizations?.length ?? 0;
    byId("metric-researchers").textContent = stats.researchers ?? 0;
    // Counted after merging, so a department two centers both work with counts once.
    byId("metric-partners").textContent = allPartners().length;
    byId("metric-tools").textContent = stats.tools ?? allTools().length;

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
      const worksButton = event.target.closest("[data-open-works]");
      if (worksButton) openResearcherWorks(worksButton.dataset.openWorks);
      const abstractToggle = event.target.closest("[data-toggle-abstract]");
      if (abstractToggle) {
        const record = abstractToggle.closest(".work-record");
        const expanded = record.classList.toggle("is-expanded");
        abstractToggle.textContent = expanded ? "Hide full abstract" : "Show full abstract";
      }
    });
    window.addEventListener("hashchange", () => showView(window.location.hash.slice(1), false));
    byId("carousel-previous").addEventListener("click", () => goToPage(carouselIndex - 1));
    byId("carousel-next").addEventListener("click", () => goToPage(carouselIndex + 1));
    byId("carousel-dots").addEventListener("click", (event) => {
      const dot = event.target.closest("[data-slide]");
      if (dot) goToPage(Number(dot.dataset.slide));
    });
    byId("center-carousel").addEventListener("scroll", () => {
      window.clearTimeout(carouselScrollTimer);
      carouselScrollTimer = window.setTimeout(syncCarousel, 90);
    });
    byId("center-carousel").addEventListener("keydown", (event) => {
      if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
      event.preventDefault();
      goToPage(carouselIndex + (event.key === "ArrowRight" ? 1 : -1));
    });
    byId("carousel-toggle").addEventListener("click", () => setCarouselStopped(!carouselStopped));
    for (const element of carouselParts()) {
      element.addEventListener("mouseenter", () => holdCarousel(true));
      element.addEventListener("focusin", () => holdCarousel(true));
      element.addEventListener("mouseleave", releaseCarousel);
      // focusout runs before focus lands on the next element, so the check waits for it.
      element.addEventListener("focusout", () => window.setTimeout(releaseCarousel, 0));
    }
    document.addEventListener("visibilitychange", () =>
      document.hidden ? stopCarousel() : startCarousel(),
    );
    reducedMotion.addEventListener("change", startCarousel);
    window.addEventListener("resize", () => {
      syncCarousel();
      startCarousel();
    });
    byId("partners-filters").addEventListener("input", renderPartners);
    byId("partners-filters").addEventListener("change", renderPartners);
    byId("partners-filters").addEventListener("submit", (event) => event.preventDefault());
    byId("activity-filters").addEventListener("input", renderActivity);
    byId("activity-filters").addEventListener("change", renderActivity);
    byId("tools-filters").addEventListener("input", renderTools);
    byId("tools-filters").addEventListener("change", renderTools);
    byId("tools-filters").addEventListener("submit", (event) => event.preventDefault());
    byId("works-filters").addEventListener("input", () => renderWorks());
    byId("works-filters").addEventListener("change", () => renderWorks());
    byId("works-filters").addEventListener("submit", (event) => event.preventDefault());
    byId("works-more").addEventListener("click", () => {
      worksVisible += WORKS_PAGE_SIZE;
      renderWorks(false);
    });
    byId("center-select").addEventListener("change", (event) => renderCenter(event.target.value));
    byId("expert-form").addEventListener("submit", async (event) => {
      event.preventDefault();
      const errorBox = byId("expert-error");
      errorBox.hidden = true;
      const query = byId("expert-query").value;
      try {
        keywordTerms(query);
      } catch (error) {
        errorBox.textContent = error.message;
        errorBox.hidden = false;
        byId("expert-summary").textContent = "";
        byId("expert-results").innerHTML = "";
        return;
      }
      // Publications load in the background; wait for them so a search never silently
      // returns a partial answer.
      byId("expert-summary").textContent = "Searching…";
      await worksPromise;
      renderExpertResults(searchExperts(query));
    });
  }

  async function fetchJson(url) {
    const response = await fetch(url, { cache: "no-store" });
    if (!response.ok) throw new Error(`${url} returned ${response.status}`);
    return response.json();
  }

  function loadWorks() {
    return fetchJson(WORKS_URL)
      .then((payload) => {
        works = payload;
        byId("metric-works").textContent = (works.stats?.works ?? works.works?.length ?? 0).toLocaleString();
        populateWorksFilters();
        renderWorks();
        renderHealth();
        // Publication counts appear on researcher cards, so redraw the open center.
        renderCenter(byId("center-select").value || snapshot.organizations?.[0]?.id || "");
      })
      .catch((error) => {
        works = { works: [], health: [], works_per_researcher: {} };
        byId("metric-works").textContent = "0";
        byId("works-count").textContent =
          `Publications are not available yet. ${error.message}. Run "uv run insightnet-works" to build them.`;
        byId("works-list").innerHTML = "";
      });
  }

  async function initialize() {
    bindEvents();
    try {
      const [profiles, activityPayload] = await Promise.all([
        fetchJson(PROFILES_URL),
        fetchJson(ACTIVITY_URL).catch(() => ({ items: [] })),
      ]);
      snapshot = profiles;
      activity = activityPayload;
      organizationsById = new Map((snapshot.organizations || []).map((org) => [org.id, org]));
      researchersById = new Map();
      researcherByOrcid = new Map();
      for (const org of snapshot.organizations || []) {
        for (const person of org.researchers || []) {
          researchersById.set(person.id, { ...person, organization_id: org.id });
          if (person.orcid_id) researcherByOrcid.set(person.orcid_id, person.id);
        }
      }
      setMetadata();
      populateOverview();
      populateFilters();
      populateToolFilters();
      populatePartnerFilters();
      renderTools();
      renderPartners();
      renderActivity();
      renderCenter(snapshot.organizations?.[0]?.id || "");
      renderHealth();
      showView(window.location.hash.slice(1) || "overview", false);
      // The publication corpus is the largest payload, so it loads after first paint.
      worksPromise = loadWorks();
    } catch (error) {
      const message = byId("app-message");
      message.textContent = `The network snapshot could not be loaded. ${error.message}`;
      message.hidden = false;
      byId("freshness").querySelector("span:last-child").textContent = "Snapshot unavailable";
    }
  }

  initialize();
})();
