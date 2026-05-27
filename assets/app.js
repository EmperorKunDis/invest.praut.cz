const state = {
  data: null,
  contacts: null,
  view: "funds",
  query: "",
  visibleRows: [],
};

const els = {
  reportMeta: document.querySelector("#reportMeta"),
  statInvestors: document.querySelector("#statInvestors"),
  statSources: document.querySelector("#statSources"),
  statChanged: document.querySelector("#statChanged"),
  statUpdated: document.querySelector("#statUpdated"),
  tldrCards: document.querySelector("#tldrCards"),
  pipelineBoard: document.querySelector("#pipelineBoard"),
  dataView: document.querySelector("#dataView"),
  findings: document.querySelector("#findings"),
  sourceSummary: document.querySelector("#sourceSummary"),
  sourceList: document.querySelector("#sourceList"),
  contactSummary: document.querySelector("#contactSummary"),
  contactList: document.querySelector("#contactList"),
  caveatList: document.querySelector("#caveatList"),
  searchInput: document.querySelector("#searchInput"),
  clearSearch: document.querySelector("#clearSearch"),
  exportInvestors: document.querySelector("#exportInvestors"),
  exportSources: document.querySelector("#exportSources"),
  exportContacts: document.querySelector("#exportContacts"),
  entityDialog: document.querySelector("#entityDialog"),
  closeDialog: document.querySelector("#closeDialog"),
  dialogContent: document.querySelector("#dialogContent"),
  tabs: [...document.querySelectorAll(".tab")],
};

const fieldLabels = {
  stage: "Stage / ticket",
  focus: "Focus",
  people: "Klíčoví lidé",
  contact: "Kontakt",
  deals: "Recent dealy",
  background: "Pozadí",
  ticket: "Ticket / sektor",
  channel: "Kanál",
  amount: "Částka",
  fit: "Vhodnost",
  sector: "Sektor",
};

const priorityNames = [
  "Look AI Ventures",
  "DEPO Ventures",
  "Credo Ventures",
  "Tensor Ventures",
  "Presto Ventures",
  "J&T Ventures",
  "CzechInvest Technology Incubation",
  "StartupYard",
  "Czech Founders VC",
];

function escapeHtml(value = "") {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function formatDate(value) {
  if (!value) return "-";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat("cs-CZ", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(date);
}

function shortDate(value) {
  if (!value) return "-";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat("cs-CZ", {
    day: "2-digit",
    month: "2-digit",
  }).format(date);
}

function includesQuery(item) {
  if (!state.query) return true;
  return JSON.stringify(item).toLocaleLowerCase("cs-CZ").includes(state.query);
}

function compactEntity(raw, type) {
  const item = { ...raw };
  if (type === "fund") {
    return {
      name: item.Fond,
      stage: item["Stage / Ticket"],
      focus: item["AI/Auto focus"] || item.Sector,
      people: item["Klíčoví partneři"] || item["Klíčoví lidé"],
      contact: item.Kontakt,
      deals: item["Recent dealy 2024–25"],
      raw,
      type,
    };
  }
  if (type === "angel") {
    return {
      name: item.Angel,
      background: item["Pozadí"],
      ticket: item["Ticket / sektor"],
      channel: item["Nejlepší kanál"],
      raw,
      type,
    };
  }
  if (type === "grant") {
    return {
      name: item.Program,
      amount: item["Částka"],
      fit: item["Vhodnost pro Praut"],
      raw,
      type,
    };
  }
  return { ...raw, raw, type };
}

function scoreEntity(entity) {
  const haystack = JSON.stringify(entity).toLocaleLowerCase("cs-CZ");
  let score = 30;
  const reasons = [];

  if (priorityNames.some((name) => entity.name?.includes(name))) {
    score += 22;
    reasons.push("explicitně doporučeno v reportu");
  }
  if (haystack.includes("pre-seed")) {
    score += 14;
    reasons.push("sedí na pre-seed");
  }
  if (haystack.includes("ai")) {
    score += 13;
    reasons.push("AI focus");
  }
  if (haystack.includes("health")) {
    score += 9;
    reasons.push("healthcare relevance");
  }
  if (haystack.includes("automation") || haystack.includes("saas")) {
    score += 8;
    reasons.push("SaaS/automation fit");
  }
  if (haystack.includes("@") || haystack.includes("apply") || haystack.includes("contact")) {
    score += 6;
    reasons.push("má použitelný vstupní kanál");
  }
  if (haystack.includes("growth") || haystack.includes("series a")) {
    score -= 8;
  }

  return {
    score: Math.max(0, Math.min(100, score)),
    reasons: reasons.length ? reasons.slice(0, 3) : ["sekundární relevance"],
  };
}

function allEntities(data) {
  return [
    ...data.funds.map((item) => compactEntity(item, "fund")),
    ...data.specialized_funds.map((item) => compactEntity(item, "fund")),
    ...data.angels.map((item) => compactEntity(item, "angel")),
    ...data.grants.map((item) => compactEntity(item, "grant")),
  ].map((entity) => ({ ...entity, ...scoreEntity(entity) }));
}

function renderStats(data) {
  const investorCount = data.funds.length + data.specialized_funds.length + data.angels.length;
  const changedSources = data.sources.filter((source) => source.changed).length;
  els.statInvestors.textContent = investorCount;
  els.statSources.textContent = data.sources.length;
  els.statChanged.textContent = changedSources;
  els.statUpdated.textContent = shortDate(data.generated_at);
  els.reportMeta.textContent = `${data.report_meta || "Investor mapping"} / aktualizováno ${formatDate(
    data.generated_at,
  )}`;
}

function renderTldr(data) {
  els.tldrCards.innerHTML = data.tldr
    .slice(0, 3)
    .map(
      (text, index) => `
        <article class="insight-card">
          <p class="eyebrow">Point ${index + 1}</p>
          <p>${escapeHtml(text)}</p>
        </article>
      `,
    )
    .join("");
}

function renderPipelineBoard(data) {
  const top = allEntities(data)
    .filter((entity) => entity.type !== "angel" || entity.score >= 60)
    .sort((a, b) => b.score - a.score)
    .slice(0, 8);

  els.pipelineBoard.innerHTML = `
    <div class="pipeline-table">
      ${top
        .map(
          (entity, index) => `
            <button class="pipeline-row" type="button" data-board-id="${index}">
              <span class="rank">${index + 1}</span>
              <span>
                <strong>${escapeHtml(entity.name)}</strong>
                <small>${escapeHtml(entity.reasons.join(" / "))}</small>
              </span>
              <span class="score">
                <i style="width: ${entity.score}%"></i>
              </span>
              <span class="score-number">${entity.score}</span>
            </button>
          `,
        )
        .join("")}
    </div>
  `;

  els.pipelineBoard.querySelectorAll("[data-board-id]").forEach((button) => {
    button.addEventListener("click", () => openEntity(top[Number(button.dataset.boardId)]));
  });
}

function renderEntities(items, type) {
  const rows = items
    .map((item) => compactEntity(item, type))
    .map((entity) => ({ ...entity, ...scoreEntity(entity) }))
    .filter(includesQuery)
    .sort((a, b) => b.score - a.score);

  state.visibleRows = rows;
  if (!rows.length) {
    els.dataView.innerHTML = `<div class="empty-state">Nic neodpovídá aktuálnímu filtru.</div>`;
    return;
  }

  els.dataView.innerHTML = `
    <div class="entity-grid">
      ${rows
        .map((item, index) => {
          const { name, score, reasons, raw, type: itemType, ...meta } = item;
          const firstMeta = Object.values(meta).find(Boolean) || itemType;
          return `
            <article class="entity-card">
              <header>
                <h3>${escapeHtml(name)}</h3>
                <span class="badge">${escapeHtml(firstMeta).slice(0, 34)}</span>
              </header>
              <div class="entity-score" aria-label="Fit score">
                <span><i style="width: ${score}%"></i></span>
                <strong>${score}</strong>
              </div>
              <p class="fit-reason">${escapeHtml(reasons.join(" / "))}</p>
              <dl class="entity-meta">
                ${Object.entries(meta)
                  .filter(([, value]) => value)
                  .slice(0, 4)
                  .map(
                    ([key, value]) => `
                      <div>
                        <dt>${fieldLabels[key] || key}</dt>
                        <dd>${escapeHtml(value)}</dd>
                      </div>
                    `,
                  )
                  .join("")}
              </dl>
              <button class="card-action" type="button" data-row-id="${index}">Detail</button>
            </article>
          `;
        })
        .join("")}
    </div>
  `;

  els.dataView.querySelectorAll("[data-row-id]").forEach((button) => {
    button.addEventListener("click", () => openEntity(state.visibleRows[Number(button.dataset.rowId)]));
  });
}

function renderActions(data) {
  const phases = data.action_plan.filter(includesQuery);
  state.visibleRows = [];
  els.dataView.innerHTML = phases.length
    ? `
      <div class="timeline">
        ${phases
          .map(
            (phase, index) => `
              <article class="phase-card">
                <span class="rank">${index + 1}</span>
                <h3>${escapeHtml(phase.title)}</h3>
                <ul>
                  ${phase.items.map((item) => `<li>${escapeHtml(item)}</li>`).join("")}
                </ul>
              </article>
            `,
          )
          .join("")}
      </div>
    `
    : `<div class="empty-state">Nic neodpovídá aktuálnímu filtru.</div>`;
}

function renderCurrentView() {
  const data = state.data;
  if (!data) return;

  if (state.view === "funds") {
    renderEntities([...data.funds, ...data.specialized_funds], "fund");
  } else if (state.view === "angels") {
    renderEntities(data.angels, "angel");
  } else if (state.view === "grants") {
    renderEntities(data.grants, "grant");
  } else {
    renderActions(data);
  }
}

function renderFindings(data) {
  els.findings.innerHTML = data.key_findings
    .filter((finding) => finding.preview)
    .slice(0, 9)
    .map(
      (finding) => `
        <article class="finding-item">
          <h3>${escapeHtml(finding.title)}</h3>
          <p>${escapeHtml(finding.preview)}</p>
        </article>
      `,
    )
    .join("");
}

function sourceBadge(source) {
  if (source.error) return `<span class="badge badge-danger">chyba</span>`;
  if (source.changed) return `<span class="badge badge-warning">změna</span>`;
  return `<span class="badge">ověřeno</span>`;
}

function renderSourceSummary(data) {
  const changed = data.sources.filter((source) => source.changed).length;
  const errors = data.sources.filter((source) => source.error).length;
  const checked = data.sources.filter((source) => source.checked_at).length;
  els.sourceSummary.innerHTML = `
    <article>
      <strong>${checked}</strong>
      <span>ověřených zdrojů</span>
    </article>
    <article>
      <strong>${changed}</strong>
      <span>změn k revizi</span>
    </article>
    <article>
      <strong>${errors}</strong>
      <span>chyb při fetchi</span>
    </article>
  `;
}

function renderContactSummary(contactData) {
  const records = contactData.records || [];
  const withEmail = records.filter((record) => record.emails.length).length;
  const withPhone = records.filter((record) => record.phones.length).length;
  const withLinkedin = records.filter((record) => record.linkedin.length).length;
  els.contactSummary.innerHTML = `
    <article>
      <strong>${records.length}</strong>
      <span>subjektů v researchi</span>
    </article>
    <article>
      <strong>${withEmail}</strong>
      <span>s veřejným e-mailem</span>
    </article>
    <article>
      <strong>${withPhone + withLinkedin}</strong>
      <span>s telefonem nebo LinkedInem</span>
    </article>
  `;
}

function linkList(values) {
  return values
    .slice(0, 8)
    .map((value) => {
      const label = value.replace(/^https?:\/\//, "").replace(/\/$/, "");
      return `<a href="${escapeHtml(value)}" target="_blank" rel="noreferrer">${escapeHtml(label)}</a>`;
    })
    .join("");
}

function renderContacts(contactData) {
  const records = [...(contactData.records || [])].sort((a, b) => {
    const aScore = a.emails.length * 3 + a.phones.length * 2 + a.linkedin.length;
    const bScore = b.emails.length * 3 + b.phones.length * 2 + b.linkedin.length;
    return bScore - aScore;
  });
  els.contactList.innerHTML = records
    .map(
      (record) => `
        <article class="contact-item">
          <header>
            <h3>${escapeHtml(record.name)}</h3>
            <a href="${escapeHtml(record.official_url)}" target="_blank" rel="noreferrer">oficiální zdroj</a>
          </header>
          <dl class="entity-meta contact-meta">
            ${
              record.emails.length
                ? `<div><dt>E-maily</dt><dd>${record.emails.map(escapeHtml).join("<br>")}</dd></div>`
                : ""
            }
            ${
              record.phones.length
                ? `<div><dt>Telefony</dt><dd>${record.phones.slice(0, 10).map(escapeHtml).join("<br>")}</dd></div>`
                : ""
            }
            ${record.linkedin.length ? `<div><dt>LinkedIn</dt><dd>${linkList(record.linkedin)}</dd></div>` : ""}
            ${record.facebook.length ? `<div><dt>Facebook</dt><dd>${linkList(record.facebook)}</dd></div>` : ""}
            ${record.whatsapp.length ? `<div><dt>WhatsApp</dt><dd>${linkList(record.whatsapp)}</dd></div>` : ""}
            ${record.forms.length ? `<div><dt>Formuláře</dt><dd>${linkList(record.forms)}</dd></div>` : ""}
          </dl>
        </article>
      `,
    )
    .join("");
}

function renderSources(data) {
  const sorted = [...data.sources].sort((a, b) => Number(b.changed) - Number(a.changed));
  els.sourceList.innerHTML = sorted
    .map(
      (source) => `
        <article class="source-item">
          <div>
            <h3>${escapeHtml(source.name)}</h3>
            <p>${escapeHtml(source.title || source.description || source.query || "Bez popisu")}</p>
            <a href="${escapeHtml(source.url)}" rel="noreferrer" target="_blank">${escapeHtml(
              source.url,
            )}</a>
          </div>
          <div class="source-meta">
            ${sourceBadge(source)}
            <span class="badge">HTTP ${escapeHtml(source.status || "-")}</span>
            <span class="badge">${escapeHtml(shortDate(source.checked_at || state.data.generated_at))}</span>
          </div>
        </article>
      `,
    )
    .join("");
}

function renderCaveats(data) {
  els.caveatList.innerHTML = data.caveats
    .map(
      (text) => `
        <article class="caveat-item">
          <p>${escapeHtml(text)}</p>
        </article>
      `,
    )
    .join("");
}

function openEntity(entity) {
  if (!entity) return;
  const entries = Object.entries(entity.raw || entity).filter(([, value]) => value);
  els.dialogContent.innerHTML = `
    <p class="eyebrow">${escapeHtml(entity.type || "detail")}</p>
    <h2>${escapeHtml(entity.name)}</h2>
    <div class="dialog-score">
      <span><i style="width: ${entity.score || 0}%"></i></span>
      <strong>${entity.score || 0}/100</strong>
    </div>
    <p class="fit-reason">${escapeHtml((entity.reasons || []).join(" / "))}</p>
    <dl class="dialog-list">
      ${entries
        .map(
          ([key, value]) => `
            <div>
              <dt>${escapeHtml(key)}</dt>
              <dd>${escapeHtml(value)}</dd>
            </div>
          `,
        )
        .join("")}
    </dl>
  `;
  els.entityDialog.showModal();
}

function csvValue(value) {
  return `"${String(value ?? "").replaceAll('"', '""')}"`;
}

function downloadCsv(filename, rows) {
  if (!rows.length) return;
  const headers = [...new Set(rows.flatMap((row) => Object.keys(row)))];
  const csv = [
    headers.map(csvValue).join(","),
    ...rows.map((row) => headers.map((header) => csvValue(row[header])).join(",")),
  ].join("\n");
  const blob = new Blob([csv], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  anchor.click();
  URL.revokeObjectURL(url);
}

function bindEvents() {
  els.searchInput.addEventListener("input", (event) => {
    state.query = event.target.value.trim().toLocaleLowerCase("cs-CZ");
    renderCurrentView();
  });

  els.clearSearch.addEventListener("click", () => {
    state.query = "";
    els.searchInput.value = "";
    renderCurrentView();
  });

  els.tabs.forEach((tab) => {
    tab.addEventListener("click", () => {
      state.view = tab.dataset.view;
      els.tabs.forEach((item) => item.classList.toggle("is-active", item === tab));
      renderCurrentView();
    });
  });

  els.closeDialog.addEventListener("click", () => els.entityDialog.close());
  els.entityDialog.addEventListener("click", (event) => {
    if (event.target === els.entityDialog) els.entityDialog.close();
  });

  els.exportInvestors.addEventListener("click", () => {
    const rows = allEntities(state.data).map(({ raw, name, score, reasons, type }) => ({
      type,
      name,
      score,
      reasons: reasons.join(" / "),
      ...raw,
    }));
    downloadCsv("praut-investor-radar.csv", rows);
  });

  els.exportSources.addEventListener("click", () => {
    downloadCsv("praut-investor-sources.csv", state.data.sources);
  });

  els.exportContacts.addEventListener("click", () => {
    downloadCsv("praut-investor-contacts.csv", state.contacts.records || []);
  });
}

async function init() {
  bindEvents();
  const [response, contactsResponse] = await Promise.all([
    fetch("data/site-data.json", { cache: "no-store" }),
    fetch("data/contact-research.json", { cache: "no-store" }),
  ]);
  if (!response.ok) {
    throw new Error(`Nepodařilo se načíst data: HTTP ${response.status}`);
  }
  if (!contactsResponse.ok) {
    throw new Error(`Nepodařilo se načíst kontakty: HTTP ${contactsResponse.status}`);
  }
  state.data = await response.json();
  state.contacts = await contactsResponse.json();
  renderStats(state.data);
  renderTldr(state.data);
  renderPipelineBoard(state.data);
  renderCurrentView();
  renderFindings(state.data);
  renderContactSummary(state.contacts);
  renderContacts(state.contacts);
  renderSourceSummary(state.data);
  renderSources(state.data);
  renderCaveats(state.data);
}

init().catch((error) => {
  document.body.innerHTML = `
    <main class="section-band">
      <h1>Data nejsou k dispozici</h1>
      <p>${escapeHtml(error.message)}</p>
    </main>
  `;
});
