(function () {
  "use strict";

  const PROFILES_URL = "./data/profiles.json";
  const WORKS_URL = "./data/works.json";
  // Abstracts and coauthor lists are most of the corpus by size and matter only once a
  // reader is looking at publications, so they arrive in a second document that is
  // fetched after the page is already usable.
  const WORKS_DETAILS_URL = "./data/works-details.json";
  const VIEWS = ["overview", "works", "health"];
  // Public by design: this endpoint appears in every visitor's browser and holds no
  // secret. Setting it to an empty string routes the ask bar to the keyword search
  // instead, which is how the feature stays shippable while the service is down.
  const ASK_URL = "https://insightnet-ask-ckn3l2i5pq-uc.a.run.app/ask";
  const ASK_MARKER = /\[\[[^\]\s]{1,64}\]\]/g;
  const ASK_FRAME_MS = 80;
  // Retrieval finding nothing is a normal outcome, not a failure, so it gets its own
  // wording rather than the one used when the service is unreachable.
  const ASK_NO_MATCH =
    "Couldn't find any researchers or publications relevant to your question.";
  const WORKS_PAGE_SIZE = 40;
  const OFFICIAL_SITE = "https://insightnet.us";
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
  let works = null;
  let worksPromise = null;
  let detailsPromise = null;
  let detailsLoaded = false;
  let organizationsById = new Map();
  let researchersById = new Map();
  let researcherByOrcid = new Map();
  let worksVisible = WORKS_PAGE_SIZE;
  let worksFiltered = [];
  let worksById = new Map();
  let askController = null;
  let askFrame = 0;

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
            : work.has_abstract && !detailsLoaded
              ? '<p class="work-abstract is-missing">Loading abstract…</p>'
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

  // People and the papers they wrote are the whole site, so the search covers those two
  // and nothing else. A center's name and focus areas still count toward its members'
  // scores, which is how a center-shaped query ("Utah", "wastewater") reaches people.
  function searchExperts(query) {
    const terms = keywordTerms(query);
    const researchers = [];
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

    const sorter = (a, b) =>
      b.score - a.score ||
      String(a.full_name || a.title).localeCompare(String(b.full_name || b.title));
    return {
      researchers: researchers.sort(sorter),
      works: matchedWorks.sort(sorter),
    };
  }

  function renderExpertResults(results) {
    const total = results.researchers.length + results.works.length;
    byId("expert-summary").textContent =
      `${total.toLocaleString()} total match${total === 1 ? "" : "es"}`;
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
      </section>`;
    return total;
  }

  // The assistant and the keyword box are two ways into the same corpus, so a fallback
  // and a typed search run through here and land in the same results area.
  async function runKeywordSearch(query) {
    const errorBox = byId("expert-error");
    errorBox.hidden = true;
    byId("expert-summary").textContent = "Searching…";
    // Publications load in the background; wait for them so a search never silently
    // returns a partial answer.
    await worksPromise;
    await loadWorkDetails();
    try {
      return renderExpertResults(searchExperts(query));
    } catch (error) {
      // The ask bar accepts 300 characters and the keyword index only reads 120, so a
      // long question arriving here by fallback lands on a real message rather than an
      // exception with nothing on screen.
      errorBox.textContent = error.message;
      errorBox.hidden = false;
      byId("expert-summary").textContent = "";
      byId("expert-results").innerHTML = "";
      return 0;
    }
  }

  // ----------------------------------------------------------------------------------
  // Assisted answers
  // ----------------------------------------------------------------------------------

  function askEndpoint() {
    // A local override keeps the deployed endpoint out of development, and is limited to
    // https or localhost so a stray value cannot redirect questions somewhere hostile.
    let override = "";
    try {
      override = window.localStorage.getItem("insightnet-ask-url") || "";
    } catch (_error) {
      override = "";
    }
    const candidate = override || ASK_URL;
    if (!candidate) return "";
    const url = safeUrl(candidate);
    if (!url) return "";
    return url.startsWith("https://") || url.startsWith("http://localhost") ? url : "";
  }

  function setAskStatus(text) {
    byId("ask-status").textContent = text;
  }

  function showAskNotice(text) {
    const notice = byId("ask-notice");
    notice.textContent = text;
    notice.hidden = !text;
  }

  // Every failure lands here: rate limited, over budget, offline, or not yet deployed.
  // The visitor still gets an answer, just a keyword one, so the page is never a dead end.
  // The keyword box below the assistant is filled in with the question, so the fallback
  // shows its work rather than producing results from nowhere.
  async function askFallback(query, notice) {
    showAskNotice(notice);
    setAskStatus("Showing keyword matches instead.");
    byId("expert-query").value = query;
    await runKeywordSearch(query);
  }

  function citationCard(document_) {
    const url = safeUrl(document_.url);
    const title = escapeHtml(document_.title || "Untitled");
    const heading = url
      ? `<a href="${escapeHtml(url)}" target="_blank" rel="noopener noreferrer">${title}</a>`
      : title;
    const detail = [document_.subtitle, document_.venue, document_.year]
      .filter(Boolean)
      .map((part) => escapeHtml(String(part)))
      .join(" · ");
    return `<article class="card ask-citation">
        <h4>${heading}</h4>
        ${detail ? `<p class="result-count">${detail}</p>` : ""}
      </article>`;
  }

  function renderAskCitations(citations) {
    // A cited publication is rendered by the same card the Publications view uses, so
    // its DOI, PMID, and arXiv links are identical wherever a reader meets it.
    const cards = citations
      .map((entry) => {
        const work = entry.work_id ? worksById.get(entry.work_id) : null;
        return work ? workCard(work) : citationCard(entry);
      })
      .join("");
    byId("ask-citations").innerHTML = cards
      ? `<h3 class="ask-citations-heading">Sources</h3>${cards}`
      : "";
  }

  // Retrieval offers the model far more documents than it ends up citing, so numbering
  // by position in that list produces footnotes that start at 7 and jump around. These
  // are numbered by order of first appearance, and only the cited ones are listed.
  function citedInOrder(text, citations) {
    return citations
      .map((entry) => ({ entry, at: text.indexOf(`[[${entry.id}]]`) }))
      .filter((item) => item.at !== -1)
      .sort((a, b) => a.at - b.at)
      .map((item) => item.entry);
  }

  // The answer arrives as a lead sentence followed by one "- " bullet per researcher.
  // Bullets are the only markup the model is allowed to emit, and this runs over text
  // that is already escaped and already carries its citation links, so the only HTML it
  // can produce is the list scaffolding written here.
  function answerHtml(escaped) {
    const blocks = [];
    let items = null;
    let paragraph = [];
    const flushParagraph = () => {
      if (paragraph.length) blocks.push(`<p>${paragraph.join(" ")}</p>`);
      paragraph = [];
    };
    const flushItems = () => {
      if (items) blocks.push(`<ul class="ask-people">${items.join("")}</ul>`);
      items = null;
    };
    for (const line of escaped.split("\n")) {
      const trimmed = line.trim();
      const bullet = trimmed.match(/^[-*•]\s+(.+)$/);
      if (bullet) {
        flushParagraph();
        items = items || [];
        items.push(`<li>${bullet[1]}</li>`);
      } else if (!trimmed) {
        flushParagraph();
        flushItems();
      } else {
        flushItems();
        paragraph.push(trimmed);
      }
    }
    flushParagraph();
    flushItems();
    return blocks.join("");
  }

  function renderAskAnswer(text, citations) {
    const cited = citedInOrder(text, citations);
    let html = escapeHtml(text);
    cited.forEach((entry, position) => {
      const url = safeUrl(entry.url);
      const number = position + 1;
      const label = url
        ? `<a href="${escapeHtml(url)}" target="_blank" rel="noopener noreferrer">${number}</a>`
        : String(number);
      // Literal substitution over the ids the service actually offered. Nothing is
      // parsed out of the model's text, so a marker it invented cannot become a link.
      html = html.replaceAll(`[[${entry.id}]]`, `<sup class="ask-cite">${label}</sup>`);
    });
    html = html.replace(ASK_MARKER, "");
    renderAskCitations(cited);
    byId("ask-answer").innerHTML = answerHtml(html);
  }

  async function readAskStream(response, onEvent) {
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      let split = buffer.indexOf("\n\n");
      while (split !== -1) {
        const frame = buffer.slice(0, split);
        buffer = buffer.slice(split + 2);
        const name = frame.match(/^event: (.*)$/m)?.[1] || "";
        const data = frame.match(/^data: (.*)$/m)?.[1] || "{}";
        try {
          onEvent(name, JSON.parse(data));
        } catch (_error) {
          // A frame that arrives malformed is skipped rather than ending the answer.
        }
        split = buffer.indexOf("\n\n");
      }
    }
  }

  async function askQuestion(query) {
    const question = String(query || "").trim();
    if (!question) return;
    askController?.abort();
    askController = new AbortController();

    byId("ask-query").value = question;
    byId("ask-echo").textContent = `“${question}”`;
    byId("ask-error").hidden = true;
    byId("ask-answer").innerHTML = "";
    byId("ask-answer-sr").textContent = "";
    byId("ask-citations").innerHTML = "";
    showAskNotice("");
    showView("overview");

    if (question.length > 300) {
      const error = byId("ask-error");
      error.textContent = "Please shorten the question to 300 characters or fewer.";
      error.hidden = false;
      return;
    }

    const endpoint = askEndpoint();
    if (!endpoint) {
      await askFallback(question, "The assisted answer service is not configured yet.");
      return;
    }

    setAskStatus("Thinking…");
    byId("ask-answer").setAttribute("aria-busy", "true");
    let citations = [];
    let answer = "";
    let refusal = "";

    const paint = () => {
      askFrame = 0;
      renderAskAnswer(answer, citations);
    };
    const schedule = () => {
      if (askFrame) return;
      askFrame = window.setTimeout(paint, ASK_FRAME_MS);
    };

    try {
      const response = await fetch(endpoint, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ question }),
        signal: askController.signal,
      });
      if (!response.ok || !response.body) {
        const detail = await response.json().catch(() => ({}));
        if (response.status === 400 || response.status === 422) {
          const error = byId("ask-error");
          error.textContent = detail.detail || "That question could not be read.";
          error.hidden = false;
          setAskStatus("");
          return;
        }
        // The service returns a no-answer as a normal 200, so anything else means the
        // assistant is unavailable rather than merely unsure.
        await askFallback(question, noticeFor(detail, response.status));
        return;
      }
      // Retrieval that matched nothing answers with a plain JSON body rather than a
      // stream. Feeding that to the SSE reader happens to produce no events, but then a
      // real no-match is indistinguishable from a stream that died early, so it is
      // recognised by content type instead of by the absence of output.
      if (!(response.headers.get("content-type") || "").includes("text/event-stream")) {
        await askFallback(question, ASK_NO_MATCH);
        return;
      }
      await readAskStream(response, (name, payload) => {
        if (name === "meta") {
          // Sources arrive before the prose and stay client-side, so a citation never
          // costs a second request; they appear as the answer cites them.
          citations = payload.citations || [];
          setAskStatus("Reading the network…");
        } else if (name === "token") {
          answer += payload.t || "";
          schedule();
        } else if (name === "no_match") {
          refusal = "no_match";
        } else if (name === "error") {
          refusal = "error";
        }
      });
    } catch (error) {
      if (error.name === "AbortError") return;
      await askFallback(question, "The assisted answer could not be reached.");
      return;
    } finally {
      byId("ask-answer").setAttribute("aria-busy", "false");
      window.clearTimeout(askFrame);
      askFrame = 0;
    }

    if (refusal || !answer.trim()) {
      // A stream can fail after some prose has already painted — an upstream quota being
      // exhausted mid-answer does exactly that. Half a sentence above "showing keyword
      // matches instead" reads like a broken page, so it is cleared rather than left.
      byId("ask-answer").innerHTML = "";
      byId("ask-answer-sr").textContent = "";
      byId("ask-citations").innerHTML = "";
      await askFallback(
        question,
        refusal === "error"
          ? "The assisted answer stopped before it could finish."
          : ASK_NO_MATCH,
      );
      return;
    }
    paint();
    // Count what the answer actually cites, not everything retrieval offered the model.
    const cited = citedInOrder(answer, citations).length;
    setAskStatus(`Answer ready${cited ? ` · ${cited} source${cited === 1 ? "" : "s"}` : ""}.`);
    // Screen readers cannot follow a region that mutates on every frame, so the finished
    // answer is announced once here instead.
    byId("ask-answer-sr").textContent = answer.trim();
  }

  function noticeFor(detail, status) {
    if (detail.error === "rate_limited") {
      return "That is a lot of questions at once. Showing keyword matches instead.";
    }
    if (detail.error === "budget_exhausted") {
      return "The assistant has reached its monthly budget. Showing keyword matches instead.";
    }
    return `The assistant is unavailable right now (${status}).`;
  }

  // The deployment stamps the real number into the footer link. Anything that is not a
  // version — the un-substituted placeholder in a local checkout — is relabelled rather
  // than shown raw, and the link still reaches the release notes either way.
  function renderVersion() {
    const link = byId("app-version");
    if (!/^v\d+\.\d+\.\d+$/.test(link.textContent.trim())) link.textContent = "dev build";
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
    // Both searches read abstracts, and so does the publication list, so the second fetch
    // starts the moment a reader heads for either rather than making them wait for it.
    if (selected === "works" || selected === "overview") loadWorkDetails();
    window.scrollTo({ top: 0, behavior: "smooth" });
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

  // What this site is, in one quiet line: whose profiles it holds and how many papers
  // came with them. The publication count arrives with the second fetch, so this runs
  // again once that lands rather than holding the sentence back.
  function renderSummary() {
    const stats = snapshot?.stats || {};
    // Coerced to numbers because the sentence is written with innerHTML for the sake of
    // one link: whatever the snapshot holds, only digits can reach the page.
    const centers = Number(stats.organizations ?? snapshot?.organizations?.length ?? 0);
    const researchers = Number(stats.researchers ?? researchersById.size);
    const publications = works
      ? Number(works.stats?.works ?? works.works?.length ?? 0)
      : null;
    byId("network-description").innerHTML =
      `This site contains academic profiles for the ${centers} centers' ` +
      `${researchers.toLocaleString()} affiliated members. The latest version includes ` +
      `${publications === null ? "…" : publications.toLocaleString()} publications. ` +
      "You can learn more about the work across InsightNet on the official website " +
      `<a href="${OFFICIAL_SITE}" target="_blank" rel="noopener noreferrer">insightnet.us</a>.`;
  }

  function setMetadata() {
    document.title = "InsightNet Explorer";
    byId("network-title").textContent = "InsightNet Explorer";
    renderSummary();

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
      const askButton = event.target.closest("[data-ask]");
      if (askButton) askQuestion(askButton.dataset.ask);
      const viewButton = event.target.closest("[data-view]");
      if (viewButton && !askButton) showView(viewButton.dataset.view);
      const goToButton = event.target.closest("[data-go-to]");
      if (goToButton) showView(goToButton.dataset.goTo);
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
    byId("works-filters").addEventListener("input", () => renderWorks());
    byId("works-filters").addEventListener("change", () => renderWorks());
    byId("works-filters").addEventListener("submit", (event) => event.preventDefault());
    byId("works-more").addEventListener("click", () => {
      worksVisible += WORKS_PAGE_SIZE;
      renderWorks(false);
    });
    byId("ask-form").addEventListener("submit", (event) => {
      event.preventDefault();
      askQuestion(byId("ask-query").value);
    });
    byId("expert-form").addEventListener("submit", (event) => {
      event.preventDefault();
      runKeywordSearch(byId("expert-query").value);
    });
  }

  async function fetchJson(url) {
    const response = await fetch(url, { cache: "no-store" });
    if (!response.ok) throw new Error(`${url} returned ${response.status}`);
    return response.json();
  }

  // Fold the abstracts and coauthor lists back onto the work records, so everything
  // downstream keeps seeing one whole object. Runs at most once.
  function loadWorkDetails() {
    if (detailsPromise) return detailsPromise;
    // A reader can land straight on a view that wants abstracts — #works, or the home
    // page's own searches — before the works fetch has been started, so there may be
    // nothing to chain onto yet. Initialisation warms the details itself once works is in
    // flight, so returning early defers the work rather than skipping it.
    if (!worksPromise) return Promise.resolve();
    detailsPromise = worksPromise
      .then(() => fetchJson(WORKS_DETAILS_URL))
      .then((payload) => {
        const byWorkId = payload.details || {};
        for (const work of works?.works || []) {
          const detail = byWorkId[work.id];
          if (detail) Object.assign(work, detail);
          // The cached search blob was built without the abstract; drop it so the next
          // search rebuilds over the full text.
          delete work._text;
        }
        detailsLoaded = true;
        if (byId("view-works")?.classList.contains("is-active")) renderWorks();
      })
      .catch(() => {
        // A missing detail document is not fatal: titles, keywords, and every filter
        // still work, and the cards say so rather than pretending the abstract is absent.
        detailsLoaded = false;
      });
    return detailsPromise;
  }

  function loadWorks() {
    return fetchJson(WORKS_URL)
      .then((payload) => {
        works = payload;
        // Citation markers arrive as work ids, so the ask view can render them with the
        // same card the Publications view uses.
        worksById = new Map((works.works || []).map((work) => [work.id, work]));
        renderSummary();
        populateWorksFilters();
        renderWorks();
        renderHealth();
      })
      .catch((error) => {
        works = { works: [], health: [], works_per_researcher: {} };
        renderSummary();
        byId("works-count").textContent =
          `Publications are not available yet. ${error.message}. Run "uv run insightnet-works" to build them.`;
        byId("works-list").innerHTML = "";
      });
  }

  async function initialize() {
    bindEvents();
    // The version describes the code, not the data, so it is settled before the snapshot
    // is fetched and survives a snapshot that never arrives.
    renderVersion();
    try {
      snapshot = await fetchJson(PROFILES_URL);
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
      renderHealth();
      // The publication corpus is the largest payload, so it loads after first paint:
      // first the searchable index, then the abstracts and coauthor lists once the
      // browser is idle. A reader who never searches never pays for the latter until
      // then, and one who does usually finds it already there. The fetch starts before
      // routing because a view restored from the hash may ask for it immediately.
      worksPromise = loadWorks();
      showView(window.location.hash.slice(1) || "overview", false);
      const warmDetails = () => worksPromise.then(loadWorkDetails);
      if (typeof window.requestIdleCallback === "function") {
        window.requestIdleCallback(warmDetails, { timeout: 5000 });
      } else {
        window.setTimeout(warmDetails, 2000);
      }
    } catch (error) {
      const message = byId("app-message");
      message.textContent = `The network snapshot could not be loaded. ${error.message}`;
      message.hidden = false;
      byId("freshness").querySelector("span:last-child").textContent = "Snapshot unavailable";
      // Otherwise the page sits on "Loading the latest snapshot…" forever, contradicting
      // the error directly above it.
      byId("network-description").textContent =
        "The profiles behind this site could not be loaded, so its searches have nothing to read.";
    }
  }

  initialize();
})();
