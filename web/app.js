"use strict";

/* Precedent Database — front-end. Plain DOM, no framework. Truth lives on disk;
   this just talks to the local API. Built to be keyboard-first and screen-reader
   friendly: real buttons, labeled controls, alt text present in the DOM. */

// ---------------------------------------------------------------------------
// Small helpers
// ---------------------------------------------------------------------------
const $ = (sel, root = document) => root.querySelector(sel);

function el(tag, props = {}, ...children) {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(props)) {
    if (v === null || v === undefined || v === false) continue;
    if (k === "class") e.className = v;
    else if (k === "text") e.textContent = v;
    else if (k === "html") e.innerHTML = v;
    else if (k.startsWith("on") && typeof v === "function")
      e.addEventListener(k.slice(2).toLowerCase(), v);
    else e.setAttribute(k, v === true ? "" : v);
  }
  for (const c of children.flat()) {
    if (c === null || c === undefined || c === false) continue;
    e.appendChild(typeof c === "string" ? document.createTextNode(c) : c);
  }
  return e;
}

function setStatus(msg, kind = "") {
  const bar = $("#statusBar");
  bar.textContent = msg || "";
  bar.className = "status-bar" + (kind ? " " + kind : "");
}

async function api(path, { method = "GET", body, form } = {}) {
  const opts = { method, headers: {} };
  if (form) opts.body = form;
  else if (body !== undefined) {
    opts.headers["Content-Type"] = "application/json";
    opts.body = JSON.stringify(body);
  }
  const res = await fetch(path, opts);
  let data = null;
  try { data = await res.json(); } catch { /* no body */ }
  if (!res.ok) {
    const detail = (data && (data.detail || data.reason)) || res.statusText;
    throw new Error(detail);
  }
  return data;
}

// ---------------------------------------------------------------------------
// View switching
// ---------------------------------------------------------------------------
let viewMode = localStorage.getItem("viewMode") || "gallery";
let config = { types: [], tags: [] };

function show(view) {
  for (const v of document.querySelectorAll(".view")) v.hidden = v.id !== view + "View";
  for (const btn of document.querySelectorAll(".nav-btn[data-view]")) {
    if (btn.dataset.view === view) btn.setAttribute("aria-current", "page");
    else btn.removeAttribute("aria-current");
  }
  const heading = $("#" + view + "View h2");
  if (heading) heading.setAttribute("tabindex", "-1"), heading.focus({ preventScroll: false });
}

// ---------------------------------------------------------------------------
// Init
// ---------------------------------------------------------------------------
async function init() {
  wireChrome();
  try {
    const st = await api("/api/status");
    if (!st.archiveSet) { show("setup"); $("#archivePath").focus(); return; }
    await afterArchiveReady(st);
  } catch (e) {
    setStatus("Could not reach the server: " + e.message, "error");
  }
}

async function afterArchiveReady(st) {
  if (!st.hasApiKey)
    setStatus("Ready. No ANTHROPIC_API_KEY set, so AI alt text is disabled until you add one.");
  else
    setStatus("Ready — " + st.count + " entries indexed.");
  await loadConfig();
  show("library");
  await loadEntries();
}

function wireChrome() {
  for (const btn of document.querySelectorAll(".nav-btn[data-view]"))
    btn.addEventListener("click", () => show(btn.dataset.view));
  $("#rebuildBtn").addEventListener("click", rebuild);
  $("#backBtn").addEventListener("click", () => { show("library"); loadEntries(); });

  $("#setupForm").addEventListener("submit", onSetup);
  $("#filterForm").addEventListener("submit", (e) => e.preventDefault());
  $("#searchInput").addEventListener("input", debounce(loadEntries, 250));
  $("#typeFilter").addEventListener("change", loadEntries);
  $("#tagFilter").addEventListener("change", loadEntries);
  $("#sortSelect").addEventListener("change", loadEntries);
  $("#galleryBtn").addEventListener("click", () => setViewMode("gallery"));
  $("#listBtn").addEventListener("click", () => setViewMode("list"));

  wireAddView();
  setViewMode(viewMode);
}

function debounce(fn, ms) {
  let t;
  return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); };
}

// ---------------------------------------------------------------------------
// Setup
// ---------------------------------------------------------------------------
async function onSetup(e) {
  e.preventDefault();
  const path = $("#archivePath").value.trim();
  if (!path) return;
  setStatus("Indexing " + path + " …");
  try {
    const st = await api("/api/settings/archive", { method: "POST", body: { path } });
    await afterArchiveReady(st);
  } catch (err) {
    setStatus("Could not use that folder: " + err.message, "error");
  }
}

async function rebuild() {
  setStatus("Rebuilding index …");
  try {
    const r = await api("/api/index/rebuild", { method: "POST" });
    setStatus("Index rebuilt — " + r.count + " entries.", "success");
    if (!$("#libraryView").hidden) loadEntries();
  } catch (e) { setStatus("Rebuild failed: " + e.message, "error"); }
}

// ---------------------------------------------------------------------------
// Library
// ---------------------------------------------------------------------------
async function loadConfig() {
  config = await api("/api/config");
  const typeSel = $("#typeFilter");
  const allTypes = Array.from(new Set([...(config.types || []), ...(config.usedTypes || [])]));
  typeSel.innerHTML = "";
  typeSel.appendChild(el("option", { value: "" }, "All types"));
  for (const t of allTypes) typeSel.appendChild(el("option", { value: t }, t));
  const tagSel = $("#tagFilter");
  tagSel.innerHTML = "";
  tagSel.appendChild(el("option", { value: "" }, "All tags"));
  for (const t of config.tags || [])
    tagSel.appendChild(el("option", { value: t.tag }, `${t.tag} (${t.count})`));
}

function setViewMode(mode) {
  viewMode = mode;
  localStorage.setItem("viewMode", mode);
  $("#galleryBtn").setAttribute("aria-pressed", String(mode === "gallery"));
  $("#listBtn").setAttribute("aria-pressed", String(mode === "list"));
  const results = $("#results");
  results.className = "results " + mode;
}

async function loadEntries() {
  const params = new URLSearchParams();
  const q = $("#searchInput").value.trim();
  if (q) params.set("q", q);
  if ($("#typeFilter").value) params.set("type", $("#typeFilter").value);
  if ($("#tagFilter").value) params.set("tag", $("#tagFilter").value);
  params.set("sort", $("#sortSelect").value);
  const results = $("#results");
  results.setAttribute("aria-busy", "true");
  try {
    const data = await api("/api/entries?" + params.toString());
    renderResults(data.entries);
    $("#resultCount").textContent =
      data.total === 0 ? "No matching precedents." :
      data.total + (data.total === 1 ? " precedent" : " precedents");
  } catch (e) {
    setStatus("Could not load entries: " + e.message, "error");
  } finally {
    results.setAttribute("aria-busy", "false");
  }
}

function renderResults(entries) {
  const results = $("#results");
  results.innerHTML = "";
  if (!entries.length) return;
  for (const e of entries) {
    const thumb = e.primaryImageUrl
      ? el("img", { class: "thumb", src: e.primaryImageUrl, alt: e.primaryAlt || "", loading: "lazy" })
      : el("span", { class: "thumb placeholder" }, e.imageCount ? "image missing" : "no image");
    const meta = [];
    if (e.type) meta.push(e.type);
    if (e.missingAlt) meta.push("alt missing");
    const card = el("button", {
      class: "card", type: "button",
      "aria-label": (e.title || "Untitled") + (e.type ? ", " + e.type : ""),
      onclick: () => openEntry(e.id),
    },
      thumb,
      el("div", { class: "card-body" },
        el("div", { class: "card-title" }, e.title || "Untitled"),
        meta.length ? el("div", { class: "card-meta" }, meta.join(" · ")) : null,
      ),
    );
    results.appendChild(card);
  }
}

// ---------------------------------------------------------------------------
// Entry detail
// ---------------------------------------------------------------------------
async function openEntry(id) {
  setStatus("");
  try {
    const entry = await api("/api/entries/" + encodeURIComponent(id));
    renderEntry(entry);
    show("entry");
  } catch (e) { setStatus("Could not open entry: " + e.message, "error"); }
}

async function refreshEntry(id) {
  const entry = await api("/api/entries/" + encodeURIComponent(id));
  renderEntry(entry);
}

function renderEntry(entry) {
  const body = $("#entryBody");
  body.innerHTML = "";

  const titleEl = el("h2", { id: "entryTitle", tabindex: "-1" }, entry.title || "Untitled");
  body.appendChild(titleEl);

  // Images + per-image actions
  for (const img of entry.images) body.appendChild(renderImage(entry, img));

  // Details form (title/type/tags/notes/sources)
  body.appendChild(renderDetailsForm(entry));

  // Relations
  body.appendChild(renderRelations(entry));

  titleEl.focus({ preventScroll: true });
}

function altBadge(img) {
  if (img.altSource === "human") return el("span", { class: "badge ok" }, "Alt: edited by you");
  if (img.altSource === "ai" && img.alt) return el("span", { class: "badge" }, "Alt: AI-generated");
  return el("span", { class: "badge warn" }, "Alt: none yet");
}

function renderImage(entry, img) {
  const wrap = el("div", { class: "entry-image" });

  const mainImg = img.url
    ? el("img", { class: "main", src: img.url, alt: img.alt || "" })
    : el("p", { class: "badge warn" }, "Image file not found on disk: " + img.path);
  wrap.appendChild(mainImg);

  // Badges row
  const badges = el("div", { class: "chips" }, altBadge(img));
  if (img.primary) badges.appendChild(el("span", { class: "chip" }, "primary"));
  if (img.tactilePrepped) badges.appendChild(el("span", { class: "badge ok" }, "tactile-prepped"));
  wrap.appendChild(badges);

  // Visible alt-text box with toggle
  const altText = el("p", { class: "alt-text" }, img.alt || "(no alt text yet)");
  const altBox = el("div", { class: "alt-box" },
    el("span", { class: "alt-label" }, "Alt text "),
    altText);
  const toggle = el("button", {
    class: "btn small", type: "button", "aria-expanded": "true", "aria-controls": "altbox-" + img.index,
    onclick: () => {
      const open = altBox.hidden;
      altBox.hidden = !open;
      toggle.setAttribute("aria-expanded", String(open));
      toggle.textContent = open ? "Hide alt text" : "Show alt text";
    },
  }, "Hide alt text");
  altBox.id = "altbox-" + img.index;
  wrap.appendChild(toggle);
  wrap.appendChild(altBox);

  // Image action buttons
  const actions = el("div", { class: "image-actions" });
  actions.appendChild(el("button", { class: "btn small", type: "button", onclick: () => toggleAltEditor(entry, img, wrap) }, "Edit alt"));
  actions.appendChild(el("button", { class: "btn small", type: "button", onclick: () => generateAlt(entry, img) }, "Generate alt (AI)"));
  actions.appendChild(el("button", { class: "btn small", type: "button", onclick: () => suggestMeta(entry, img) }, "Suggest title/tags (AI)"));
  if (!img.primary)
    actions.appendChild(el("button", { class: "btn small", type: "button", onclick: () => setPrimary(entry, img) }, "Make primary"));
  actions.appendChild(el("button", { class: "btn small", type: "button", onclick: () => togglePanel(wrap, "piaf", () => piafPanel(entry, img)) }, "Prep for PIAF"));
  actions.appendChild(el("button", { class: "btn small", type: "button", onclick: () => togglePanel(wrap, "edit", () => editPanel(entry, img)) }, "Edit image"));
  wrap.appendChild(actions);

  // Caption
  const cap = el("input", { type: "text", value: img.caption || "", id: "cap-" + img.index });
  const capForm = el("form", { class: "row", onsubmit: (e) => { e.preventDefault(); saveCaption(entry, img, cap.value); } },
    el("div", { class: "field grow" }, el("label", { for: "cap-" + img.index }, "Caption"), cap),
    el("button", { class: "btn small", type: "submit" }, "Save caption"));
  wrap.appendChild(capForm);

  // Derivatives
  if (img.derivatives && img.derivatives.length) {
    const d = el("div", { class: "derivatives" }, el("strong", {}, "Generated files: "));
    for (const dv of img.derivatives) {
      d.appendChild(el("div", { class: "row" },
        dv.url ? el("img", { src: dv.url, alt: dv.kind + " version of " + (entry.title || "image") }) : null,
        el("a", { class: "btn small", href: dv.download, download: "" }, "Download " + dv.kind),
      ));
    }
    wrap.appendChild(d);
  }

  return wrap;
}

function toggleAltEditor(entry, img, wrap) {
  let panel = wrap.querySelector(".alt-editor");
  if (panel) { panel.remove(); return; }
  const ta = el("textarea", { id: "alt-edit-" + img.index }, img.alt || "");
  panel = el("div", { class: "action-panel alt-editor" },
    el("div", { class: "field" }, el("label", { for: "alt-edit-" + img.index }, "Edit alt text (saved as your edit)"), ta),
    el("button", {
      class: "btn small primary", type: "button",
      onclick: async () => {
        try {
          await api(`/api/entries/${entry.id}/images/${img.index}/alt`, { method: "POST", body: { alt: ta.value } });
          setStatus("Alt text saved.", "success");
          refreshEntry(entry.id);
        } catch (e) { setStatus("Could not save alt: " + e.message, "error"); }
      },
    }, "Save alt text"));
  wrap.appendChild(panel);
  ta.focus();
}

async function generateAlt(entry, img, confirmOverwrite = false) {
  setStatus("Generating alt text …");
  try {
    const r = await api(`/api/entries/${entry.id}/images/${img.index}/alt/generate${confirmOverwrite ? "?confirm=true" : ""}`, { method: "POST" });
    if (r.ok) { setStatus("Alt text generated.", "success"); refreshEntry(entry.id); return; }
    if (r.needsConfirm) {
      if (confirm("This image already has alt text you edited. Overwrite it with a new AI version?"))
        return generateAlt(entry, img, true);
      setStatus("Kept your alt text.");
      return;
    }
    if (r.reason === "no_api_key") setStatus("No API key set — add ANTHROPIC_API_KEY to enable AI alt text.", "error");
    else setStatus("Could not generate alt text: " + r.reason, "error");
  } catch (e) { setStatus("Alt generation failed: " + e.message, "error"); }
}

async function suggestMeta(entry, img) {
  setStatus("Asking for title/tag suggestions …");
  try {
    const r = await api(`/api/entries/${entry.id}/images/${img.index}/suggest`, { method: "POST" });
    if (!r.ok) { setStatus(r.reason === "no_api_key" ? "No API key set." : "No suggestions available.", "error"); return; }
    const s = r.suggestions;
    const msg = `Suggestion — title: "${s.title}", type: ${s.type || "(none)"}, tags: ${(s.tags || []).join(", ")}. Apply?`;
    if (confirm(msg)) {
      await api("/api/entries/" + entry.id, { method: "PATCH", body: { title: s.title || entry.title, type: s.type || entry.type, tags: Array.from(new Set([...(entry.tags || []), ...(s.tags || [])])) } });
      setStatus("Applied suggestions.", "success");
      refreshEntry(entry.id);
    } else setStatus("Suggestions discarded.");
  } catch (e) { setStatus("Suggestion failed: " + e.message, "error"); }
}

async function setPrimary(entry, img) {
  try {
    await api(`/api/entries/${entry.id}/images/${img.index}/meta`, { method: "POST", body: { primary: true } });
    refreshEntry(entry.id);
  } catch (e) { setStatus(e.message, "error"); }
}

async function saveCaption(entry, img, caption) {
  try {
    await api(`/api/entries/${entry.id}/images/${img.index}/meta`, { method: "POST", body: { caption } });
    setStatus("Caption saved.", "success");
  } catch (e) { setStatus(e.message, "error"); }
}

function togglePanel(wrap, key, builder) {
  const existing = wrap.querySelector(".panel-" + key);
  if (existing) { existing.remove(); return; }
  for (const p of wrap.querySelectorAll(".action-panel.toolpanel")) p.remove();
  const panel = builder();
  panel.classList.add("toolpanel", "panel-" + key);
  wrap.appendChild(panel);
  const first = panel.querySelector("input,select,button");
  if (first) first.focus();
}

function piafPanel(entry, img) {
  const th = el("input", { type: "range", min: "0", max: "255", value: "128", id: "th-" + img.index });
  const thNum = el("output", {}, "128");
  th.addEventListener("input", () => (thNum.textContent = th.value));
  const edge = el("input", { type: "checkbox", id: "edge-" + img.index });
  const inv = el("input", { type: "checkbox", id: "inv-" + img.index });
  return el("div", { class: "action-panel" },
    el("p", {}, el("strong", {}, "Prep for PIAF "), "— makes a bold black-on-white version for swell paper."),
    el("div", { class: "field" }, el("label", { for: "th-" + img.index }, "Threshold (lower = more black)"), el("div", { class: "row" }, th, thNum)),
    el("div", { class: "field check" }, edge, el("label", { for: "edge-" + img.index }, "Edge detection (good for plans / line drawings)")),
    el("div", { class: "field check" }, inv, el("label", { for: "inv-" + img.index }, "Invert (white-on-black source)")),
    el("button", {
      class: "btn small primary", type: "button",
      onclick: async () => {
        setStatus("Rendering PIAF version …");
        try {
          await api(`/api/entries/${entry.id}/images/${img.index}/piaf`, { method: "POST", body: { threshold: Number(th.value), edge: edge.checked, invert: inv.checked } });
          setStatus("PIAF version ready — download it below.", "success");
          refreshEntry(entry.id);
        } catch (e) { setStatus("PIAF failed: " + e.message, "error"); }
      },
    }, "Generate PIAF version"));
}

function editPanel(entry, img) {
  const rotate = el("select", { id: "rot-" + img.index },
    ...[0, 90, 180, 270].map((d) => el("option", { value: d }, d + "°")));
  const contrast = el("input", { type: "number", value: "1.0", step: "0.1", min: "0", id: "con-" + img.index });
  const maxDim = el("input", { type: "number", placeholder: "(optional) max width/height px", id: "max-" + img.index });
  return el("div", { class: "action-panel" },
    el("p", {}, el("strong", {}, "Edit image "), "— basic crop/rotate/resize/contrast. Saves a new file; original untouched."),
    el("div", { class: "row" },
      el("div", { class: "field" }, el("label", { for: "rot-" + img.index }, "Rotate (clockwise)"), rotate),
      el("div", { class: "field" }, el("label", { for: "con-" + img.index }, "Contrast (1.0 = none)"), contrast),
      el("div", { class: "field" }, el("label", { for: "max-" + img.index }, "Resize longest side"), maxDim)),
    el("button", {
      class: "btn small primary", type: "button",
      onclick: async () => {
        const payload = { rotate: Number(rotate.value), contrast: Number(contrast.value) };
        if (maxDim.value) payload.resize = { maxDim: Number(maxDim.value) };
        setStatus("Applying edit …");
        try {
          await api(`/api/entries/${entry.id}/images/${img.index}/edit`, { method: "POST", body: payload });
          setStatus("Edited copy created — download it below.", "success");
          refreshEntry(entry.id);
        } catch (e) { setStatus("Edit failed: " + e.message, "error"); }
      },
    }, "Apply edit"));
}

function renderDetailsForm(entry) {
  const typeSel = el("select", { id: "d-type" }, el("option", { value: "" }, "(no type)"));
  const types = Array.from(new Set([...(config.types || []), entry.type].filter(Boolean)));
  for (const t of types) {
    const o = el("option", { value: t }, t);
    if (t === entry.type) o.selected = true;
    typeSel.appendChild(o);
  }
  const titleIn = el("input", { type: "text", id: "d-title", value: entry.title || "" });
  const tagsIn = el("input", { type: "text", id: "d-tags", value: (entry.tags || []).join(", ") });
  const notesIn = el("textarea", { id: "d-notes" }, entry.notes || "");
  const sourcesIn = el("textarea", { id: "d-sources" },
    (entry.sources || []).map((s) => s.url + (s.label ? " | " + s.label : "")).join("\n"));

  const form = el("form", {
    class: "meta-grid", "aria-label": "Entry details",
    onsubmit: async (e) => {
      e.preventDefault();
      const sources = sourcesIn.value.split("\n").map((l) => l.trim()).filter(Boolean).map((l) => {
        const [url, ...rest] = l.split("|");
        return { url: url.trim(), label: rest.join("|").trim() };
      });
      try {
        await api("/api/entries/" + entry.id, { method: "PATCH", body: {
          title: titleIn.value, type: typeSel.value,
          tags: tagsIn.value.split(",").map((t) => t.trim()).filter(Boolean),
          notes: notesIn.value, sources,
        } });
        setStatus("Details saved.", "success");
        refreshEntry(entry.id);
      } catch (err) { setStatus("Could not save: " + err.message, "error"); }
    },
  },
    el("h3", {}, "Details"),
    el("div", { class: "field" }, el("label", { for: "d-title" }, "Title"), titleIn),
    el("div", { class: "field" }, el("label", { for: "d-type" }, "Type"), typeSel),
    el("div", { class: "field" }, el("label", { for: "d-tags" }, "Tags (comma-separated)"), tagsIn),
    el("div", { class: "field" }, el("label", { for: "d-sources" }, "Sources (one per line: url | label)"), sourcesIn),
    el("div", { class: "field" }, el("label", { for: "d-notes" }, "Notes (markdown)"), notesIn),
    el("button", { class: "btn primary", type: "submit" }, "Save details"));
  return form;
}

function renderRelations(entry) {
  const section = el("section", { "aria-labelledby": "relHeading" }, el("h3", { id: "relHeading" }, "Related entries"));
  const list = el("ul", { class: "related-list" });
  if (!entry.related.length) list.appendChild(el("li", { class: "hint" }, "No related entries yet."));
  for (const r of entry.related) {
    list.appendChild(el("li", {},
      el("button", { class: "btn link", type: "button", onclick: () => openEntry(r.id) }, r.title),
      el("button", {
        class: "btn small danger", type: "button", "aria-label": "Remove relation to " + r.title,
        onclick: async () => {
          try { await api(`/api/entries/${entry.id}/relations/${encodeURIComponent(r.id)}`, { method: "DELETE" }); refreshEntry(entry.id); }
          catch (e) { setStatus(e.message, "error"); }
        },
      }, "Remove"));
  }
  section.appendChild(list);

  if (entry.backlinks && entry.backlinks.length) {
    section.appendChild(el("h3", {}, "Linked from"));
    const bl = el("ul", { class: "related-list" });
    for (const b of entry.backlinks)
      bl.appendChild(el("li", {}, el("button", { class: "btn link", type: "button", onclick: () => openEntry(b.id) }, b.title)));
    section.appendChild(bl);
  }

  // Add-relation search
  const search = el("input", { type: "search", id: "relSearch", placeholder: "search entries to link…", "aria-label": "Search entries to link" });
  const candidates = el("ul", { class: "candidate-list", "aria-live": "polite" });
  search.addEventListener("input", debounce(async () => {
    const q = search.value.trim();
    candidates.innerHTML = "";
    if (!q) return;
    const data = await api("/api/entries?q=" + encodeURIComponent(q));
    const taken = new Set([entry.id, ...entry.related.map((r) => r.id)]);
    for (const c of data.entries.filter((c) => !taken.has(c.id)).slice(0, 8)) {
      candidates.appendChild(el("li", {}, el("button", {
        class: "btn small", type: "button",
        onclick: async () => {
          try { await api(`/api/entries/${entry.id}/relations`, { method: "POST", body: { target: c.id } }); setStatus("Linked.", "success"); refreshEntry(entry.id); }
          catch (e) { setStatus(e.message, "error"); }
        },
      }, "Link: " + (c.title || "Untitled"))));
    }
  }, 250));
  section.appendChild(el("div", { class: "field" }, el("label", { for: "relSearch" }, "Add a relation"), search));
  section.appendChild(candidates);
  return section;
}

// ---------------------------------------------------------------------------
// Add view
// ---------------------------------------------------------------------------
function wireAddView() {
  const dz = $("#dropZone");
  ["dragenter", "dragover"].forEach((ev) => dz.addEventListener(ev, (e) => { e.preventDefault(); dz.classList.add("dragover"); }));
  ["dragleave", "drop"].forEach((ev) => dz.addEventListener(ev, (e) => { e.preventDefault(); dz.classList.remove("dragover"); }));
  dz.addEventListener("drop", (e) => { if (e.dataTransfer.files.length) uploadFiles(e.dataTransfer.files); });
  $("#fileInput").addEventListener("change", (e) => { if (e.target.files.length) uploadFiles(e.target.files); });
  $("#groupCheck").addEventListener("change", (e) => { $("#groupTitleField").hidden = !e.target.checked; });

  document.addEventListener("paste", (e) => {
    if ($("#addView").hidden) return;
    const items = [...(e.clipboardData?.files || [])].filter((f) => f.type.startsWith("image/"));
    if (items.length) { e.preventDefault(); uploadFiles(items); }
  });

  $("#existingForm").addEventListener("submit", async (e) => {
    e.preventDefault();
    const path = $("#existingPath").value.trim();
    if (!path) return;
    try {
      const r = await api("/api/add/existing", { method: "POST", body: { path } });
      setStatus(r.created ? "Added entry for " + path : "That image already has an entry.", "success");
      openEntry(r.id);
    } catch (err) { setStatus("Could not add: " + err.message, "error"); }
  });

  $("#urlForm").addEventListener("submit", async (e) => {
    e.preventDefault();
    const url = $("#urlInput").value.trim();
    if (!url) return;
    setStatus("Fetching " + url + " …");
    try {
      const r = await api("/api/add/url", { method: "POST", body: { url } });
      if (!r.ok) {
        setStatus("Could not fetch that page: " + (r.reason || "unknown") + (r.manualRecommended ? " — try a screenshot instead." : ""), "error");
        return;
      }
      setStatus("Added “" + r.title + "”." + (r.note ? " " + r.note : ""), "success");
      openEntry(r.id);
    } catch (err) { setStatus("Fetch failed: " + err.message, "error"); }
  });

  $("#genMissingBtn").addEventListener("click", async () => {
    setStatus("Generating alt text for all images that are missing it … this can take a while.");
    try {
      const r = await api("/api/alt/generate-missing", { method: "POST" });
      if (!r.ok && r.reason === "no_api_key") { setStatus("No API key set — add ANTHROPIC_API_KEY first.", "error"); return; }
      setStatus(`Done — ${r.updated} generated, ${r.skipped} already had alt, ${r.failed} failed.`, "success");
    } catch (e) { setStatus("Bulk alt generation failed: " + e.message, "error"); }
  });
}

async function uploadFiles(fileList) {
  const group = $("#groupCheck").checked;
  const form = new FormData();
  for (const f of fileList) form.append("files", f);
  form.append("group", group ? "true" : "false");
  form.append("groupTitle", $("#groupTitle").value || "");
  setStatus("Adding " + fileList.length + " image(s) …");
  try {
    const r = await api("/api/add/upload", { method: "POST", form });
    const note = r.altScheduled ? " AI alt text is being generated in the background." : "";
    setStatus("Added " + r.count + " entr" + (r.count === 1 ? "y." : "ies.") + note, "success");
    if (r.created.length === 1) openEntry(r.created[0].id);
    else { show("library"); loadEntries(); }
  } catch (e) { setStatus("Upload failed: " + e.message, "error"); }
}

document.addEventListener("DOMContentLoaded", init);
