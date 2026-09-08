"use strict";
// MdFlow フロントエンド。Python(ロジック)とは QWebChannel 経由で連携する。

let bridge = null;
let md = null;
const state = { md: "", selectedId: "", preset: "", diagrams: [] };

const $ = (id) => document.getElementById(id);
const escapeHtml = (s) => s.replace(/[&<>"']/g, (c) =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

function bcall(name, ...args) {
  return new Promise((resolve) => {
    if (!bridge || typeof bridge[name] !== "function") return resolve(null);
    bridge[name](...args, resolve);
  });
}

function toast(msg) {
  const t = $("toast");
  t.textContent = msg;
  t.classList.add("show");
  clearTimeout(toast._t);
  toast._t = setTimeout(() => t.classList.remove("show"), 1800);
}

// ---- editor（textarea ベース。Monaco 同梱時は差し替え余地あり）----
function editorText() { return $("editor-fallback").value; }
function setEditorText(v) { $("editor-fallback").value = v; }

// ---- markdown / mermaid 初期化 ----
function initRenderers() {
  if (window.markdownit) {
    md = window.markdownit({ html: false, linkify: true, breaks: false });
    const defFence = md.renderer.rules.fence ||
      ((t, i, o, e, s) => s.renderToken(t, i, o));
    md.renderer.rules.fence = function (tokens, idx, options, env, self) {
      const token = tokens[idx];
      const info = (token.info || "").trim().split(/\s+/)[0];
      if (info !== "mermaid") return defFence(tokens, idx, options, env, self);
      let code = token.content.replace(/\n$/, "");
      const idm = code.match(/%%\s*id\s*:\s*(\S+)/);
      const id = idm ? idm[1] : "#" + env.mmIndex;
      env.mmIndex++;
      const selected = id === env.selectedId;
      if (selected && env.injected) code = env.injected;
      const cls = selected ? "mermaid-box selected" : "mermaid-box";
      return `<div class="${cls}"><pre class="mermaid">${escapeHtml(code)}</pre></div>`;
    };
  }
  if (window.mermaid) {
    $("status-engine").textContent = "mermaid ✓";
    window.mermaid.initialize({ startOnLoad: false, theme: "dark", securityLevel: "strict" });
  } else {
    $("status-engine").innerHTML =
      '<span class="badge danger">mermaid未配置: scripts/fetch_mermaid.py</span>';
  }
}

// ---- 再描画（デバウンス）----
let renderTimer = null;
function scheduleRender() { clearTimeout(renderTimer); renderTimer = setTimeout(render, 300); }

async function refreshSelectors() {
  const info = JSON.parse((await bcall("parseDoc", editorText())) || "{}");
  state.diagrams = info.diagrams || [];
  const selDia = $("sel-diagram");
  const prev = selDia.value;
  selDia.innerHTML = "";
  state.diagrams.forEach((d) => {
    const o = document.createElement("option");
    o.value = d.id; o.textContent = d.id; selDia.appendChild(o);
  });
  if (state.diagrams.some((d) => d.id === prev)) selDia.value = prev;
  state.selectedId = selDia.value;
  buildPresetOptions(info);
}

function buildPresetOptions(info) {
  const dia = state.diagrams.find((d) => d.id === state.selectedId);
  const selPre = $("sel-preset");
  const prev = selPre.value;
  selPre.innerHTML = "";
  const auto = document.createElement("option");
  auto.value = ""; auto.textContent = "(条件で自動判定)";
  selPre.appendChild(auto);
  (dia ? dia.presets : []).forEach((p) => {
    const o = document.createElement("option");
    o.value = p; o.textContent = p; selPre.appendChild(o);
  });
  const saved = info && info.selected ? info.selected[state.selectedId] : "";
  if ([...selPre.options].some((o) => o.value === prev)) selPre.value = prev;
  else if (saved && [...selPre.options].some((o) => o.value === saved)) selPre.value = saved;
}

async function render() {
  await refreshSelectors();
  const conditions = $("conditions").value || "{}";
  const preset = $("sel-preset").value;
  const res = JSON.parse(
    (await bcall("renderDiagram", editorText(), state.selectedId, conditions, preset)) || "{}");

  // ステータス
  $("status-preset").textContent = "プリセット: " + (res.preset || "(なし)");
  const warn = $("status-warn");
  warn.innerHTML = (res.warnings && res.warnings.length)
    ? '<span class="badge warn">⚠ ' + res.warnings.join(" / ") + "</span>" : "";

  // プレビュー
  const preview = $("preview");
  if (md) {
    const env = { mmIndex: 0, selectedId: state.selectedId, injected: res.injected || "" };
    preview.innerHTML = md.render(editorText(), env);
  } else {
    preview.innerHTML = "<pre>" + escapeHtml(editorText()) + "</pre>";
  }
  if (window.mermaid) {
    try { await window.mermaid.run({ querySelector: "#preview .mermaid" }); }
    catch (e) { console.warn(e); }
  }
}

// ---- SVG → PNG ラスタライズ（PPT貼付用）----
function rasterizeSelected() {
  return new Promise((resolve, reject) => {
    let box = document.querySelector("#preview .mermaid-box.selected svg")
      || document.querySelector("#preview .mermaid-box svg");
    if (!box) return reject(new Error("描画済みの図が見つかりません"));
    const rect = box.getBoundingClientRect();
    const scale = 2;
    const w = Math.max(1, Math.round(rect.width)), h = Math.max(1, Math.round(rect.height));
    const xml = new XMLSerializer().serializeToString(box);
    const svg64 = "data:image/svg+xml;base64," + btoa(unescape(encodeURIComponent(xml)));
    const img = new Image();
    img.onload = () => {
      const canvas = document.createElement("canvas");
      canvas.width = w * scale; canvas.height = h * scale;
      const ctx = canvas.getContext("2d");
      ctx.fillStyle = "#ffffff"; ctx.fillRect(0, 0, canvas.width, canvas.height);
      ctx.drawImage(img, 0, 0, canvas.width, canvas.height);
      resolve(canvas.toDataURL("image/png"));
    };
    img.onerror = () => reject(new Error("SVGのラスタライズに失敗しました"));
    img.src = svg64;
  });
}

// ---- ボタン ----
async function onOpen() {
  const text = await bcall("openFile");
  if (text != null && text !== "") { setEditorText(text); await render(); toast("開きました"); }
}
async function onSave() {
  const res = await bcall("saveFile", editorText(), state.selectedId, $("sel-preset").value);
  if (res) { const j = JSON.parse(res); if (j.md) setEditorText(j.md); toast(j.message || "保存しました"); await render(); }
}
async function onExport() {
  try {
    await render();
    const png = await rasterizeSelected();
    const res = await bcall("exportPpt", editorText(), state.selectedId,
      $("conditions").value || "{}", $("sel-preset").value, png);
    const j = JSON.parse(res || "{}");
    toast(j.path ? "PPT出力: " + j.path : (j.error || "キャンセル"));
  } catch (e) { toast("出力失敗: " + e.message); }
}
async function onImport() {
  const res = await bcall("importPpt");
  const j = JSON.parse(res || "{}");
  if (j.error) { toast(j.error); return; }
  if (j.md != null) {
    setEditorText(j.md);
    $("conditions").value = JSON.stringify(j.conditions || {});
    await render();
    if (j.preset) $("sel-preset").value = j.preset;
    await render();
    let m = `復元: source=${j.source}, hash_ok=${j.hash_ok}`;
    if (!j.hash_ok) m += " ⚠ 画像とコードが不一致の可能性";
    toast(m);
  }
}

// 外部（Python）からドロップ取り込み時に呼ばれる
window.mdflowLoadImport = (payloadJson) => {
  const j = JSON.parse(payloadJson);
  if (j.md != null) { setEditorText(j.md); $("conditions").value = JSON.stringify(j.conditions || {}); render(); }
};
window.mdflowLoadFile = (text) => { setEditorText(text); render(); };

// ---- divider ドラッグ ----
function initDivider() {
  const div = $("divider"), left = $("left"), main = $("main");
  let dragging = false;
  div.addEventListener("mousedown", () => { dragging = true; document.body.style.cursor = "col-resize"; });
  window.addEventListener("mouseup", () => { dragging = false; document.body.style.cursor = ""; });
  window.addEventListener("mousemove", (e) => {
    if (!dragging) return;
    const r = main.getBoundingClientRect();
    const ratio = Math.min(0.8, Math.max(0.2, (e.clientX - r.left) / r.width));
    left.style.flex = `1 1 ${ratio * 100}%`;
  });
}

function wire() {
  $("btn-open").onclick = onOpen;
  $("btn-save").onclick = onSave;
  $("btn-export").onclick = onExport;
  $("btn-import").onclick = onImport;
  $("editor-fallback").addEventListener("input", scheduleRender);
  $("conditions").addEventListener("input", scheduleRender);
  $("sel-diagram").addEventListener("change", () => { state.selectedId = $("sel-diagram").value; render(); });
  $("sel-preset").addEventListener("change", render);
  initDivider();
}

// ---- 起動 ----
window.addEventListener("DOMContentLoaded", () => {
  initRenderers();
  wire();
  new QWebChannel(qt.webChannelTransport, async (channel) => {
    bridge = channel.objects.bridge;
    const initial = await bcall("initialText");
    if (initial) setEditorText(initial);
    await render();
  });
});
