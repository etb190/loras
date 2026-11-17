/* Loras - standalone Civitai metadata catalog.
 * Vanilla JS, no build step. Talks to the aiohttp backend only.
 */
"use strict";

// ------------------------------------------------------------------ helpers

const $ = (sel) => document.querySelector(sel);
const el = (tag, cls, text) => {
  const node = document.createElement(tag);
  if (cls) node.className = cls;
  if (text !== undefined && text !== null) node.textContent = text;
  return node;
};

function toast(message, kind = "info", ms = 3200) {
  const box = $("#toasts");
  const t = el("div", `toast ${kind === "ok" ? "ok" : kind === "err" ? "err" : ""}`, message);
  box.appendChild(t);
  setTimeout(() => t.remove(), ms);
}

async function api(path, options) {
  const response = await fetch(path, options);
  if (!response.ok) {
    let message = `HTTP ${response.status}`;
    try {
      const data = await response.json();
      if (data && typeof data.detail === "string") message = data.detail;
    } catch (_) { /* keep default */ }
    const err = new Error(message);
    err.status = response.status;
    throw err;
  }
  return response.json();
}

// Civitai CDN URL rewriting (ported from ComfyUI-Lora-Manager's civitaiUtils.js):
// /original=true -> /width=450,optimized=true for cheap thumbnails.
function civitaiThumb(url, width = 450) {
  if (!url) return url;
  try {
    const parsed = new URL(url);
    const host = parsed.hostname.toLowerCase();
    if (host !== "civitai.com" && !host.endsWith(".civitai.com")) return url;
    if (!parsed.pathname.includes("/original=true")) return url;
    parsed.pathname = parsed.pathname.replace(
      "/original=true",
      `/width=${width},optimized=true`
    );
    return parsed.toString();
  } catch (_) {
    return url;
  }
}

function formatSizeKB(sizeKB) {
  if (sizeKB === undefined || sizeKB === null || isNaN(sizeKB)) return "?";
  const mb = sizeKB / 1024;
  if (mb >= 1024) return `${(mb / 1024).toFixed(2)} GB`;
  if (mb >= 1) return `${mb.toFixed(1)} MB`;
  return `${Math.round(sizeKB)} KB`;
}

function formatDate(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  if (isNaN(d.getTime())) return iso;
  return d.toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
}

// Minimal HTML sanitizer for Civitai descriptions rendered inside the modal.
function sanitizeDescription(html) {
  const template = document.createElement("template");
  template.innerHTML = String(html || "");
  const forbidden = new Set([
    "script", "style", "iframe", "object", "embed", "link", "meta",
    "base", "form", "input", "button", "video", "audio",
  ]);
  template.content.querySelectorAll("*").forEach((node) => {
    if (forbidden.has(node.tagName.toLowerCase())) {
      node.remove();
      return;
    }
    for (const attr of [...node.attributes]) {
      const name = attr.name.toLowerCase();
      if (name.startsWith("on")) node.removeAttribute(attr.name);
      else if ((name === "href" || name === "src") && attr.value.trim().toLowerCase().startsWith("javascript:")) {
        node.removeAttribute(attr.name);
      }
    }
  });
  return template.content;
}

async function copyText(text) {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch (_) {
    const area = el("textarea");
    area.value = text;
    document.body.appendChild(area);
    area.select();
    try { document.execCommand("copy"); } catch (_) { /* ignore */ }
    area.remove();
    return true;
  }
}

// -------------------------------------------------------------------- state

const state = {
  models: [],
  meta: { types: {}, baseModels: {}, hasToken: false, count: 0 },
  filters: { q: "", type: "", baseModel: "" },
  detailModelId: null,
};

async function loadCatalog() {
  const data = await api("/api/models");
  state.models = data.models || [];
  state.meta = await api("/api/meta");
  renderFilters();
  renderCards();
}

// ------------------------------------------------------------------- render

function filteredModels() {
  const { q, type, baseModel } = state.filters;
  const needle = q.trim().toLowerCase();
  return state.models.filter((m) => {
    if (type && (m.type || "").toLowerCase() !== type.toLowerCase()) return false;
    if (baseModel && !(m.baseModels || []).some((b) => b.toLowerCase() === baseModel.toLowerCase())) return false;
    if (needle) {
      const hay = [
        m.name, m.creator, String(m.id),
        (m.tags || []).join(" "),
        (m.trainedWords || []).join(" "),
      ].join(" ").toLowerCase();
      if (!hay.includes(needle)) return false;
    }
    return true;
  });
}

function renderFilters() {
  const typeSelect = $("#filterType");
  const baseSelect = $("#filterBaseModel");
  const keep = (select, current) => {
    select.innerHTML = "";
    select.appendChild(el("option", null, "All")).value = "";
    Object.entries(current).forEach(([name, count]) => {
      const opt = el("option", null, `${name} (${count})`);
      opt.value = name;
      select.appendChild(opt);
    });
  };
  keep(typeSelect, state.meta.types || {});
  keep(baseSelect, state.meta.baseModels || {});
  typeSelect.value = state.filters.type;
  baseSelect.value = state.filters.baseModel;
  $("#filtersBar").classList.toggle("hidden", !(state.models.length > 0));
  $("#emptyState").classList.toggle("hidden", state.models.length > 0);
  $("#statsLine").textContent = state.models.length
    ? `${state.models.length} model${state.models.length === 1 ? "" : "s"} in catalog`
    : "";
  $("#tokenState").textContent = state.meta.hasToken ? "saved" : "off";
  $("#tokenState").style.color = state.meta.hasToken ? "var(--green)" : "var(--text-muted)";
}

function renderCards() {
  const grid = $("#cardGrid");
  grid.innerHTML = "";
  const models = filteredModels();
  $("#resultCount").textContent = `${models.length} shown`;

  for (const m of models) {
    grid.appendChild(buildCard(m));
  }
}

function buildCard(m) {
  const card = el("article", "card");
  card.addEventListener("click", () => openDetail(m.id));

  // cover
  const cover = el("div", "card-cover");
  const coverUrl = m.coverImage && m.coverImage.url;
  if (coverUrl) {
    if ((m.coverImage.type || "image") === "video") {
      const video = document.createElement("video");
      video.muted = true;
      video.preload = "metadata";
      video.src = civitaiThumb(coverUrl, 450);
      cover.appendChild(video);
    } else {
      const img = document.createElement("img");
      img.loading = "lazy";
      img.src = civitaiThumb(coverUrl, 450);
      img.alt = m.name || "";
      if ((m.coverImage.nsfwLevel || 0) > 1 || m.nsfw) {
        img.classList.add("nsfw-blur");
        cover.addEventListener("click", (ev) => {
          if (!cover.classList.contains("revealed")) {
            ev.stopPropagation();
            cover.classList.add("revealed");
          }
        }, { capture: true });
      }
      cover.appendChild(img);
    }
  }
  const overlay = el("div", "cover-overlay");
  overlay.appendChild(el("span", "badge type", m.type || "model"));
  if (m.nsfw || (m.coverImage && (m.coverImage.nsfwLevel || 0) > 1)) {
    overlay.appendChild(el("span", "badge nsfw", "NSFW"));
  }
  cover.appendChild(overlay);
  card.appendChild(cover);

  // body
  const body = el("div", "card-body");
  const title = el("h3", "card-title", m.name || `Model ${m.id}`);
  body.appendChild(title);
  const meta = el("div", "card-meta");
  if (m.creator) meta.appendChild(el("span", "creator", m.creator));
  if (m.baseModels && m.baseModels.length) {
    meta.appendChild(el("span", null, m.baseModels.slice(0, 2).join(", ")));
  }
  if (m.versionCount) meta.appendChild(el("span", null, `${m.versionCount} v`));
  body.appendChild(meta);

  const words = m.trainedWords || [];
  if (words.length) {
    const row = el("div", "chip-row");
    words.slice(0, 3).forEach((w) => {
      const chip = el("span", "chip", w);
      chip.title = "Click to copy trigger word";
      chip.addEventListener("click", async (ev) => {
        ev.stopPropagation();
        await copyText(w);
        toast(`Copied trigger word: ${w}`, "ok", 1600);
      });
      row.appendChild(chip);
    });
    if (words.length > 3) row.appendChild(el("span", "chip more", `+${words.length - 3}`));
    body.appendChild(row);
  }

  const tags = m.tags || [];
  if (tags.length) {
    const row = el("div", "chip-row");
    tags.slice(0, 4).forEach((t) => row.appendChild(el("span", "chip tag-chip", t)));
    if (tags.length > 4) row.appendChild(el("span", "chip more", `+${tags.length - 4}`));
    body.appendChild(row);
  }
  card.appendChild(body);

  // footer
  const foot = el("div", "card-foot");
  const stats = m.stats || {};
  const bits = [];
  if (stats.thumbsUpCount !== undefined && stats.thumbsUpCount !== null) bits.push(`\u{1F44D} ${stats.thumbsUpCount}`);
  if (stats.downloadCount !== undefined && stats.downloadCount !== null) bits.push(`\u2193 ${stats.downloadCount}`);
  bits.push(`saved ${formatDate(m.fetchedAt)}`);
  foot.appendChild(el("span", null, bits.join("  ·  ")));
  foot.appendChild(el("span", "spacer"));

  const actions = el("div", "card-actions");
  const refreshBtn = el("button", "card-action", "\u21BB");
  refreshBtn.title = "Re-fetch metadata from Civitai";
  refreshBtn.addEventListener("click", async (ev) => {
    ev.stopPropagation();
    refreshBtn.disabled = true;
    try {
      const updated = await api(`/api/models/${m.id}/refresh`, { method: "POST" });
      await loadCatalog();
      toast(`Updated "${updated.name}"`, "ok");
    } catch (err) {
      toast(`Refresh failed: ${err.message}`, "err");
    } finally {
      refreshBtn.disabled = false;
    }
  });
  const deleteBtn = el("button", "card-action danger", "\u2715");
  deleteBtn.title = "Remove from catalog (metadata only - Civitai is untouched)";
  deleteBtn.addEventListener("click", async (ev) => {
    ev.stopPropagation();
    if (!window.confirm(`Remove "${m.name}" from the catalog?`)) return;
    try {
      await api(`/api/models/${m.id}`, { method: "DELETE" });
      state.models = state.models.filter((x) => x.id !== m.id);
      state.meta = await api("/api/meta");
      renderFilters();
      renderCards();
      toast("Removed", "ok");
    } catch (err) {
      toast(`Delete failed: ${err.message}`, "err");
    }
  });
  const linkBtn = el("button", "card-action", "\u2197");
  linkBtn.title = "Open on Civitai";
  linkBtn.addEventListener("click", (ev) => {
    ev.stopPropagation();
    window.open(m.pageUrl, "_blank", "noopener");
  });
  actions.appendChild(refreshBtn);
  actions.appendChild(linkBtn);
  actions.appendChild(deleteBtn);
  foot.appendChild(actions);
  card.appendChild(foot);

  return card;
}

// ------------------------------------------------------------- fetch modal

function openModal(id) { $(`#${id}`).classList.remove("hidden"); }
function closeModal(id) { $(`#${id}`).classList.add("hidden"); }

async function runFetch() {
  const input = $("#linksInput");
  const tokenField = $("#fetchToken");
  const remember = $("#rememberToken");
  const progress = $("#fetchProgress");
  const raw = input.value.trim();
  if (!raw) { toast("Paste at least one Civitai link", "err"); return; }

  const token = tokenField.value.trim();
  const payload = { urls: raw };
  if (token) payload.token = token;

  const urls = raw.replace(/[",]/g, " ").split(/\s+/).filter(Boolean);
  progress.classList.remove("hidden");
  progress.innerHTML = "";
  urls.forEach((u) => {
    const line = el("div", "line");
    line.appendChild(el("span", "url", u));
    line.appendChild(el("span", "status", " ...waiting"));
    progress.appendChild(line);
  });

  $("#fetchBtn").disabled = true;
  try {
    const data = await api("/api/fetch", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });

    const resultMap = new Map();
    (data.fetched || []).forEach((m) => resultMap.set(String(m.id), { ok: true, name: m.name }));
    (data.errors || []).forEach((e) => {
      const link = parseUrlKey(e.url);
      resultMap.set(link, { ok: false, error: e.error });
    });

    [...progress.children].forEach((line, idx) => {
      const key = parseUrlKey(urls[idx]);
      const result = resultMap.get(key) || { ok: false, error: "no result" };
      const statusEl = line.querySelector(".status");
      statusEl.className = result.ok ? "status status-ok" : "status status-err";
      statusEl.textContent = result.ok
        ? ` \u2713 ${result.name}`
        : ` \u2717 ${result.error}`;
    });

    if (token && remember.checked) {
      await api("/api/token", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ token }),
      });
      toast("Token stored on server", "ok");
    }

    const okCount = (data.fetched || []).length;
    const errCount = (data.errors || []).length;
    toast(`Fetched ${okCount} entr${okCount === 1 ? "y" : "ies"}${errCount ? `, ${errCount} failed` : ""}`, errCount && !okCount ? "err" : "ok");

    await loadCatalog();
    if (okCount > 0) {
      input.value = "";
      tokenField.value = "";
      closeModal("fetchModal");
    }
  } catch (err) {
    toast(`Fetch failed: ${err.message}`, "err");
  } finally {
    $("#fetchBtn").disabled = false;
  }
}

function parseUrlKey(url) {
  const match = String(url).match(/(models\/(\d+)|model-versions\/(\d+))/);
  if (!match) return String(url);
  if (match[2]) return match[2];
  return `v${match[3] || ""}`;
}

// ------------------------------------------------------------ detail modal

async function openDetail(id) {
  let model;
  try {
    model = await api(`/api/models/${id}`);
  } catch (err) {
    toast(`Could not load model: ${err.message}`, "err");
    return;
  }
  state.detailModelId = id;
  $("#detailTitle").textContent = model.name || `Model ${id}`;
  $("#detailCivitaiLink").href = `https://civitai.com/models/${id}`;
  renderDetail(model);
  openModal("detailModal");
}

function renderDetail(model) {
  const body = $("#detailBody");
  body.innerHTML = "";

  const versions = model.modelVersions || [];
  const linkedId = model._linkedVersionId || (versions[0] && versions[0].id);
  const primary = versions.find((v) => v.id === linkedId) || versions[0] || {};

  const grid = el("div", "detail-grid");

  // --- left: gallery
  const gallery = el("div");
  const main = el("div", "gallery-main");
  const images = primary.images || [];
  const mainImgUrl = images[0] && images[0].url;
  if (mainImgUrl) updateGalleryMain(main, images[0], 0);
  else main.appendChild(el("div", "muted", "No preview images in metadata"));
  gallery.appendChild(main);

  if (images.length > 1) {
    const strip = el("div", "gallery-strip");
    images.slice(0, 12).forEach((img, idx) => {
      const thumb = el("button", "gallery-thumb");
      const im = document.createElement("img");
      im.loading = "lazy";
      im.src = civitaiThumb(img.url, 160);
      im.alt = "";
      thumb.appendChild(im);
      if (idx === 0) thumb.classList.add("active");
      thumb.addEventListener("click", () => {
        strip.querySelectorAll(".gallery-thumb").forEach((t) => t.classList.remove("active"));
        thumb.classList.add("active");
        updateGalleryMain(main, img, idx);
      });
      strip.appendChild(thumb);
    });
    gallery.appendChild(strip);
  }
  grid.appendChild(gallery);

  // --- right: metadata
  const side = el("div", "detail-side");

  const metaRow = el("div", "detail-meta-row");
  metaRow.appendChild(el("span", "badge type", model.type || "model"));
  if (model.nsfw || (primary.nsfwLevel || 0) > 1) metaRow.appendChild(el("span", "badge nsfw", "NSFW"));
  if (model.availability && model.availability !== "Public") {
    metaRow.appendChild(el("span", "pill", model.availability));
  }
  side.appendChild(metaRow);

  const creator = (model.creator || {}).username || "unknown";
  const stats = model.stats || {};
  const kv = el("div", "kv");
  kv.innerHTML = "";
  kv.appendChild(el("span", null, "by "));
  kv.appendChild(el("b", null, creator));
  kv.appendChild(document.createTextNode("  ·  "));
  kv.appendChild(el("b", null, String(stats.thumbsUpCount ?? 0)));
  kv.appendChild(document.createTextNode(" thumbs · "));
  kv.appendChild(el("b", null, String(stats.downloadCount ?? 0)));
  kv.appendChild(document.createTextNode(" downloads · fetched "));
  kv.appendChild(el("b", null, formatDate(model._fetchedAt)));
  side.appendChild(kv);

  // trigger words
  const twSection = el("div", "triggerwords-box");
  twSection.appendChild(el("div", "section-title", "Trigger words (linked version)"));
  const words = primary.trainedWords || [];
  if (words.length) {
    const list = el("div", "tw-list");
    words.forEach((w) => {
      const chip = el("span", "tw-chip", w);
      chip.title = "Click to copy";
      chip.addEventListener("click", async () => {
        await copyText(w);
        chip.classList.add("copied");
        setTimeout(() => chip.classList.remove("copied"), 1200);
      });
      list.appendChild(chip);
    });
    twSection.appendChild(list);
    const copyAll = el("button", "btn ghost small", "Copy all trigger words");
    copyAll.addEventListener("click", async () => {
      await copyText(words.join(", "));
      toast("All trigger words copied", "ok", 1800);
    });
    twSection.appendChild(copyAll);
  } else {
    twSection.appendChild(el("div", "muted", "No trained words on this version"));
  }
  side.appendChild(twSection);

  // tags
  const tags = model.tags || [];
  if (tags.length) {
    const tagBox = el("div");
    tagBox.appendChild(el("div", "section-title", "Tags"));
    const row = el("div", "chip-row");
    tags.forEach((t) => row.appendChild(el("span", "chip tag-chip", t)));
    tagBox.appendChild(row);
    side.appendChild(tagBox);
  }

  // description
  if (model.description) {
    const descBox = el("div");
    descBox.appendChild(el("div", "section-title", "Description"));
    const desc = el("div", "description");
    desc.appendChild(sanitizeDescription(model.description));
    descBox.appendChild(desc);
    side.appendChild(descBox);
  }

  grid.appendChild(side);
  body.appendChild(grid);

  // --- versions table
  const versionsBox = el("div");
  versionsBox.appendChild(el("div", "section-title", `Versions (${versions.length})`));
  if (versions.length) {
    const table = el("table", "versions");
    const thead = el("thead");
    const hr = el("tr");
    ["Version", "Base model", "Published", "Trigger words", "Files"].forEach((h) => hr.appendChild(el("th", null, h)));
    thead.appendChild(hr);
    table.appendChild(thead);
    const tbody = el("tbody");
    versions.forEach((v) => {
      const tr = el("tr");
      if (v.id === linkedId) tr.classList.add("linked");
      const nameTd = el("td");
      nameTd.appendChild(el("b", null, v.name || `#${v.id}`));
      if (v.id === linkedId) nameTd.appendChild(document.createTextNode(" "));
      if (v.id === linkedId) nameTd.appendChild(el("span", "pill linked", "linked"));
      tr.appendChild(nameTd);
      tr.appendChild(el("td", null, v.baseModel || "-"));
      tr.appendChild(el("td", null, formatDate(v.publishedAt)));
      tr.appendChild(el("td", null, (v.trainedWords || []).join(", ") || "-"));
      const filesTd = el("td");
      (v.files || []).forEach((f) => {
        const line = el("div", "file-line");
        line.appendChild(el("b", null, f.name || f.id || "file"));
        line.appendChild(document.createTextNode(
          `  ·  ${formatSizeKB(f.sizeKB)}  ·  ${(f.hashes || {}).SHA256 || (f.hashes || {}).AutoV2 || ""}`
        ));
        filesTd.appendChild(line);
      });
      if (!(v.files || []).length) filesTd.appendChild(el("span", "muted", "-"));
      tr.appendChild(filesTd);
      tbody.appendChild(tr);
    });
    table.appendChild(tbody);
    versionsBox.appendChild(table);
  }
  body.appendChild(versionsBox);

  // --- source urls + raw json
  const footBox = el("div", "raw-json-toggle");
  const sourceUrls = model._sourceUrls || [];
  if (sourceUrls.length) {
    const line = el("div", "kv");
    line.appendChild(el("span", null, "Fetched from: "));
    sourceUrls.forEach((u, idx) => {
      if (idx) line.appendChild(document.createTextNode(", "));
      const a = el("a", null, u);
      a.href = u;
      a.target = "_blank";
      a.rel = "noopener";
      line.appendChild(a);
    });
    footBox.appendChild(line);
  }
  const toggle = el("button", "btn ghost small", "Show raw metadata JSON");
  toggle.addEventListener("click", () => {
    let pre = footBox.querySelector("pre");
    if (pre) { pre.remove(); toggle.textContent = "Show raw metadata JSON"; return; }
    pre = el("pre", "raw-json");
    pre.textContent = JSON.stringify(model, null, 2);
    footBox.appendChild(pre);
    toggle.textContent = "Hide raw metadata JSON";
  });
  footBox.appendChild(toggle);
  body.appendChild(footBox);
}

function updateGalleryMain(main, img, idx) {
  main.innerHTML = "";
  main.classList.remove("revealed");
  const isVideo = (img.type || "image") === "video";
  const url = civitaiThumb(img.url, 2400);
  if (isVideo) {
    const video = document.createElement("video");
    video.controls = true;
    video.preload = "metadata";
    video.src = url;
    main.appendChild(video);
    return;
  }
  const im = document.createElement("img");
  im.src = url;
  im.alt = `preview ${idx + 1}`;
  if ((img.nsfwLevel || 0) > 1) {
    im.classList.add("nsfw-blur");
    main.addEventListener("click", () => main.classList.add("revealed"), { once: true });
  }
  main.appendChild(im);
}

// ------------------------------------------------------------- token modal

async function openTokenModal() {
  const status = await api("/api/token");
  $("#tokenInput").value = "";
  $("#tokenStoreCheck").checked = status.hasToken;
  $("#tokenStatusLine").textContent = status.hasToken
    ? "A token is stored on the server (used automatically for fetches)."
    : "No token stored on the server. You can still pass one per fetch.";
  openModal("tokenModal");
}

async function saveToken() {
  const token = $("#tokenInput").value.trim();
  const store = $("#tokenStoreCheck").checked;
  try {
    if (store && token) {
      await api("/api/token", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ token }),
      });
      toast("Token stored on server", "ok");
    } else if (!store && token) {
      await api("/api/token", { method: "DELETE" });
      toast("Token kept out of the server - pass it per fetch instead", "ok");
    } else {
      await api("/api/token", { method: "DELETE" });
      toast("Server token removed", "ok");
    }
    state.meta = await api("/api/meta");
    renderFilters();
    closeModal("tokenModal");
  } catch (err) {
    toast(`Token update failed: ${err.message}`, "err");
  }
}

async function removeToken() {
  await api("/api/token", { method: "DELETE" });
  $("#tokenInput").value = "";
  $("#tokenStoreCheck").checked = false;
  $("#tokenStatusLine").textContent = "No token stored on the server.";
  state.meta = await api("/api/meta");
  renderFilters();
  toast("Token removed", "ok");
}

// ------------------------------------------------------------------ events

function wireEvents() {
  $("#addLinksBtn").addEventListener("click", () => {
    $("#fetchProgress").classList.add("hidden");
    openModal("fetchModal");
    $("#linksInput").focus();
  });
  $("#emptyAddBtn").addEventListener("click", () => openModal("fetchModal"));
  $("#fetchBtn").addEventListener("click", runFetch);

  $("#tokenBtn").addEventListener("click", openTokenModal);
  $("#tokenSaveBtn").addEventListener("click", saveToken);
  $("#tokenRemoveBtn").addEventListener("click", removeToken);

  $("#exportBtn").addEventListener("click", () => {
    if (!state.models.length) { toast("Catalog is empty - nothing to export", "err"); return; }
    window.location.href = "/api/export";
  });

  document.querySelectorAll("[data-close]").forEach((btn) => {
    btn.addEventListener("click", () => closeModal(btn.dataset.close));
  });
  document.querySelectorAll(".modal-backdrop").forEach((backdrop) => {
    backdrop.addEventListener("click", (ev) => {
      if (ev.target === backdrop) backdrop.classList.add("hidden");
    });
  });
  document.addEventListener("keydown", (ev) => {
    if (ev.key === "Escape") {
      document.querySelectorAll(".modal-backdrop").forEach((b) => b.classList.add("hidden"));
    }
  });

  $("#globalSearch").addEventListener("input", debounce((ev) => {
    state.filters.q = ev.target.value;
    renderCards();
  }, 180));

  $("#filterType").addEventListener("change", (ev) => {
    state.filters.type = ev.target.value;
    renderCards();
  });
  $("#filterBaseModel").addEventListener("change", (ev) => {
    state.filters.baseModel = ev.target.value;
    renderCards();
  });
}

function debounce(fn, ms) {
  let timer = null;
  return (...args) => {
    clearTimeout(timer);
    timer = setTimeout(() => fn(...args), ms);
  };
}

// -------------------------------------------------------------------- boot

wireEvents();
loadCatalog().catch((err) => toast(`Failed to load catalog: ${err.message}`, "err"));
