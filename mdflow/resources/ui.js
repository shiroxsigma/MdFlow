"use strict";
// MdFlow フロントエンド。Python(ロジック)とは QWebChannel 経由で連携する。

let md = null;
let editor = null;
let diagramDecorations = [];
let llmAbort = null;
let llmDiffEditor = null;
let llmDiffModels = [];
let llmValidationTimer = null;
const state = { md: "", selectedId: "", preset: "", diagrams: [], zoom: 1, renderId: 0,
  llmSelection: null, llmMode: "ask", syncingScroll: false };

const $ = (id) => document.getElementById(id);
const escapeHtml = (s) => s.replace(/[&<>"']/g, (c) =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

async function api(path, body) {
  const response = await fetch(path, {
    method: body === undefined ? "GET" : "POST",
    headers: body === undefined ? {} : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!response.ok) throw new Error(await response.text());
  return response.json();
}

async function bcall(name, ...args) {
  if (name === "parseDoc") return JSON.stringify(await api("/api/parse", { md: args[0] }));
  if (name === "renderDiagram") return JSON.stringify(await api("/api/render", {
    md: args[0], diagram_id: args[1], conditions: args[2], preset: args[3],
  }));
  if (name === "addPreset") return JSON.stringify(await api("/api/preset", {
    md: args[0], diagram_id: args[1], name: args[2], when: args[3],
    nodes: JSON.parse(args[4] || "[]"),
  }));
  return null;
}

function download(blob, filename) {
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url; link.download = filename; link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

function chooseFile(accept) {
  return new Promise((resolve) => {
    const input = document.createElement("input");
    input.type = "file"; input.accept = accept;
    input.onchange = () => resolve(input.files[0] || null);
    input.click();
  });
}

function toast(msg) {
  const t = $("toast");
  t.textContent = msg;
  t.classList.add("show");
  clearTimeout(toast._t);
  toast._t = setTimeout(() => t.classList.remove("show"), 1800);
}

// ---- Monaco editor ----
function editorText() { return editor ? editor.getValue() : $("editor-fallback").value; }
function setEditorText(v) { if (editor) editor.setValue(v); else $("editor-fallback").value = v; }

function currentFenceLanguage(model, line) {
  let language = "";
  for (let n = 1; n <= line; n++) {
    const match = model.getLineContent(n).match(/^\s*```\s*(\w+)?/);
    if (match) language = language ? "" : (match[1] || "").toLowerCase();
  }
  return language;
}

function initEditor(initialText) {
  return new Promise((resolve) => {
    if (!window.require) { $("editor-fallback").value = initialText; resolve(false); return; }
    window.require.config({ paths: { vs: "/assets/vendor/monaco/vs" } });
    window.require(["vs/editor/editor.main"], () => {
      monaco.editor.defineTheme("mdflow-dark", { base: "vs-dark", inherit: true, rules: [
        { token: "keyword", foreground: "8B7CFF" }, { token: "string", foreground: "5AD1C9" }
      ], colors: { "editor.background": "#1e1e2a", "editorLineNumber.foreground": "#666680" } });
      editor = monaco.editor.create($("editor-host"), { value: initialText, language: "markdown",
        theme: "mdflow-dark", automaticLayout: true, wordWrap: "on", minimap: { enabled: false },
        fontFamily: "Cascadia Code, Consolas, monospace", fontSize: 14, tabSize: 2,
        renderWhitespace: "selection", stickyScroll: { enabled: true } });
      $("editor-fallback").style.display = "none";

      monaco.languages.registerCompletionItemProvider("markdown", { triggerCharacters: ["@", "`", "!"],
        provideCompletionItems(model, position) {
          const lang = currentFenceLanguage(model, position.lineNumber);
          const range = new monaco.Range(position.lineNumber, position.column, position.lineNumber, position.column);
          const entries = lang === "plantuml" || lang === "puml" ? [
            ["@startuml", "@startuml\n\n@enduml"], ["sequence", "actor User\nparticipant App\nUser -> App: request\nApp --> User: response"],
            ["class", "class Example {\n  +method()\n}"], ["C4 container", "!include <C4/C4_Container>\nPerson(user, \"User\")\nContainer(app, \"Application\", \"Technology\")\nRel(user, app, \"Uses\")"]
          ] : lang === "mermaid" ? [
            ["flowchart", "flowchart TD\n  A[Start] --> B[End]"], ["sequenceDiagram", "sequenceDiagram\n  actor User\n  User->>App: Request"]
          ] : [["PlantUML block", "```plantuml\n@startuml\n\n@enduml\n```"], ["Mermaid block", "```mermaid\nflowchart TD\n  A --> B\n```"]];
          return { suggestions: entries.map(([label, insertText]) => ({ label, kind: monaco.languages.CompletionItemKind.Snippet,
            insertText, insertTextRules: monaco.languages.CompletionItemInsertTextRule.InsertAsSnippet, range })) };
        } });
      editor.onDidChangeModelContent(() => { scheduleRender(); updateOutline(); });
      editor.onDidChangeCursorPosition((e) => { $("cursor-position").textContent = `Ln ${e.position.lineNumber}, Col ${e.position.column}`; });
      editor.onDidScrollChange((e) => syncPreviewFromEditor(e.scrollTop, e.scrollHeight));
      editor.addCommand(monaco.KeyMod.CtrlCmd | monaco.KeyCode.KeyS, onSave);
      updateOutline(); resolve(true);
    }, () => { $("editor-fallback").value = initialText; resolve(false); });
  });
}

function revealLine(line) {
  if (!editor || !line) return;
  editor.revealLineInCenter(line); editor.setPosition({ lineNumber: line, column: 1 }); editor.focus();
}

function updateOutline() {
  const host = $("outline-items"); host.innerHTML = "";
  const lines = editorText().split("\n"); let fence = ""; let diagramIndex = 0;
  lines.forEach((line, index) => {
    const fm = line.match(/^\s*```\s*(mermaid|plantuml|puml)\s*$/i);
    if (fm) { fence = fm[1].toLowerCase(); diagramIndex++; addOutline(`◇ ${fence} ${diagramIndex}`, index + 1, "diagram"); return; }
    if (fence && /^\s*```/.test(line)) { fence = ""; return; }
    if (!fence) { const hm = line.match(/^(#{1,3})\s+(.+)/); if (hm) addOutline(hm[2], index + 1, `level-${hm[1].length}`); }
  });
  function addOutline(label, line, cls) { const button = document.createElement("button"); button.className = `outline-item ${cls}`;
    button.textContent = label; button.onclick = () => revealLine(line); host.appendChild(button); }
  updateDiagramDecorations();
}

function updateDiagramDecorations() {
  if (!editor || !window.monaco) return;
  const lines = editorText().split("\n"); let fence = ""; const decorations = [];
  lines.forEach((line, index) => {
    const match = line.match(/^\s*```\s*(mermaid|plantuml|puml)\s*$/i);
    if (match) { fence = match[1].toLowerCase(); return; }
    if (fence && /^\s*```/.test(line)) { fence = ""; return; }
    if (fence) decorations.push({ range: new monaco.Range(index + 1, 1, index + 1, Math.max(1, line.length + 1)),
      options: { inlineClassName: fence === "mermaid" ? "mermaid-code-line" : "plantuml-code-line" } });
  });
  diagramDecorations = editor.deltaDecorations(diagramDecorations, decorations);
}

// ---- markdown / mermaid 初期化 ----
function initRenderers() {
  if (window.markdownit) {
    md = window.markdownit({ html: false, linkify: true, breaks: false });
    const defFence = md.renderer.rules.fence ||
      ((t, i, o, e, s) => s.renderToken(t, i, o));
    md.renderer.rules.fence = function (tokens, idx, options, env, self) {
      const token = tokens[idx];
      const info = (token.info || "").trim().split(/\s+/)[0];
      if (info === "plantuml" || info === "puml") {
        const source = token.content.replace(/\n$/, "");
        const line = token.map ? token.map[0] + 2 : 1;
        return `<div class="plantuml-box" data-line="${line}"><pre class="plantuml-source">${escapeHtml(source)}</pre><div class="plantuml-status">PlantUML を描画中...</div></div>`;
      }
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
async function renderPlantUmlBlocks() {
  if (editor && window.monaco) monaco.editor.setModelMarkers(editor.getModel(), "plantuml", []);
  const blocks = [...document.querySelectorAll("#preview .plantuml-box")];
  await Promise.all(blocks.map(async (box) => {
    const source = box.querySelector(".plantuml-source").textContent;
    const status = box.querySelector(".plantuml-status");
    try {
      const result = await api("/api/plantuml", { source });
      if (result.error) { const error = new Error(result.error); error.line = result.line; throw error; }
      const img = document.createElement("img");
      img.className = "plantuml-diagram";
      img.alt = "PlantUML diagram";
      img.src = "data:image/svg+xml;base64," + btoa(unescape(encodeURIComponent(result.svg)));
      box.replaceChildren(img);
    } catch (e) {
      status.textContent = e.message;
      status.classList.add("error");
      status.title = "クリックして該当箇所へ移動";
      status.onclick = () => revealLine(Number(box.dataset.line) + (e.line || 0));
      if (editor && e.line) monaco.editor.setModelMarkers(editor.getModel(), "plantuml", [{
        startLineNumber: Number(box.dataset.line) + e.line - 1, startColumn: 1,
        endLineNumber: Number(box.dataset.line) + e.line - 1, endColumn: 999,
        message: e.message, severity: monaco.MarkerSeverity.Error }]);
    }
  }));
}

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
  const renderId = ++state.renderId;
  await refreshSelectors();
  const conditions = $("conditions").value || "{}";
  const preset = $("sel-preset").value;
  const res = JSON.parse(
    (await bcall("renderDiagram", editorText(), state.selectedId, conditions, preset)) || "{}");
  if (renderId !== state.renderId) return;

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
    catch (e) { console.warn(e); const line = Number(String(e.message || e).match(/line\s+(\d+)/i)?.[1]);
      if (line) { warn.innerHTML = `<button class="badge danger" id="diagram-error">図の構文エラー: line ${line}</button>`;
        $("diagram-error").onclick = () => revealLine(line); } }
  }
  await renderPlantUmlBlocks();
  applyZoom();
}

// ---- SVG → PNG ラスタライズ（PPT貼付用）----
function rasterizeSelected() {
  return new Promise((resolve, reject) => {
    let box = selectedDiagramElement();
    if (!box) return reject(new Error("描画済みの図が見つかりません"));
    const rect = box.getBoundingClientRect();
    const scale = 2;
    const w = Math.max(1, Math.round(rect.width)), h = Math.max(1, Math.round(rect.height));
    const svg64 = box.tagName.toLowerCase() === "img" ? box.src :
      "data:image/svg+xml;base64," + btoa(unescape(encodeURIComponent(new XMLSerializer().serializeToString(box))));
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

function selectedDiagramElement() {
  return document.querySelector("#preview .tool-selected svg, #preview .tool-selected img")
    || document.querySelector("#preview .mermaid-box.selected svg")
    || document.querySelector("#preview .mermaid-box svg")
    || document.querySelector("#preview .plantuml-diagram");
}

function selectPreviewDiagram(event) {
  const box = event.target.closest(".mermaid-box, .plantuml-box");
  if (!box) return;
  document.querySelectorAll("#preview .tool-selected").forEach((item) => item.classList.remove("tool-selected"));
  box.classList.add("tool-selected"); applyZoom();
}

function applyZoom() {
  const diagram = selectedDiagramElement();
  if (diagram) { diagram.style.transformOrigin = "top center"; diagram.style.transform = `scale(${state.zoom})`; }
  $("zoom-label").textContent = `${Math.round(state.zoom * 100)}%`;
}

function changeZoom(delta) { state.zoom = Math.min(3, Math.max(.25, state.zoom + delta)); applyZoom(); }

async function selectedSvgText() {
  const diagram = selectedDiagramElement();
  if (!diagram) throw new Error("描画済みの図がありません");
  if (diagram.tagName.toLowerCase() === "svg") return new XMLSerializer().serializeToString(diagram);
  const response = await fetch(diagram.src); return response.text();
}

async function copySvg() {
  try { await navigator.clipboard.writeText(await selectedSvgText()); toast("SVGをコピーしました"); }
  catch (e) { toast("SVGコピー失敗: " + e.message); }
}

async function pngBlob() {
  const dataUrl = await rasterizeSelected(); return (await fetch(dataUrl)).blob();
}
async function copyPng() {
  try { await navigator.clipboard.write([new ClipboardItem({ "image/png": await pngBlob() })]); toast("PNGをコピーしました"); }
  catch (e) { toast("PNGコピー失敗: " + e.message); }
}
async function saveDiagram() {
  try { download(new Blob([await selectedSvgText()], { type: "image/svg+xml" }), `${state.selectedId || "diagram"}.svg`); toast("SVGを保存しました"); }
  catch (e) { toast("保存失敗: " + e.message); }
}

function syncPreviewFromEditor(scrollTop, scrollHeight) {
  if (state.syncingScroll) return; const preview = $("preview");
  const ratio = scrollTop / Math.max(1, scrollHeight - editor.getLayoutInfo().height);
  state.syncingScroll = true; preview.scrollTop = ratio * Math.max(0, preview.scrollHeight - preview.clientHeight);
  requestAnimationFrame(() => { state.syncingScroll = false; });
}

function syncEditorFromPreview() {
  if (!editor || state.syncingScroll) return; const preview = $("preview");
  const ratio = preview.scrollTop / Math.max(1, preview.scrollHeight - preview.clientHeight);
  state.syncingScroll = true; editor.setScrollTop(ratio * Math.max(0, editor.getScrollHeight() - editor.getLayoutInfo().height));
  requestAnimationFrame(() => { state.syncingScroll = false; });
}

// ---- ボタン ----
async function onOpen() {
  const file = await chooseFile(".md,text/markdown,text/plain");
  if (file) {
    setEditorText(await file.text());
    $("file-name").textContent = file.name;
    await render(); toast("Markdownを開きました");
  }
}
async function onSave() {
  const filename = ($("file-name").textContent || "mdflow.md").split(/[\\/]/).pop();
  download(new Blob([editorText()], { type: "text/markdown;charset=utf-8" }), filename);
  toast("Markdownを保存しました");
}
async function onExport() {
  try {
    await render();
    const png = await rasterizeSelected();
    const response = await fetch("/api/export", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ md: editorText(), diagram_id: state.selectedId,
        conditions: $("conditions").value || "{}", preset: $("sel-preset").value, png_dataurl: png }) });
    if (!response.ok) throw new Error(await response.text());
    download(await response.blob(), (state.selectedId || "diagram") + ".pptx");
    toast("PowerPointを出力しました");
  } catch (e) { toast("出力失敗: " + e.message); }
}
async function onImport() {
  const file = await chooseFile(".pptx,application/vnd.openxmlformats-officedocument.presentationml.presentation");
  if (!file) return;
  const form = new FormData(); form.append("file", file);
  const response = await fetch("/api/import", { method: "POST", body: form });
  if (!response.ok) { toast("PowerPointの取込に失敗しました"); return; }
  const j = await response.json();
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

// ---- 条件登録モーダル ----
function openCondModal() {
  const dia = state.diagrams.find((d) => d.id === state.selectedId);
  if (!dia) return;
  if (!dia.id || dia.id.startsWith("#")) {
    toast("図に『%% id: 名前』を付けてから登録してください");
    return;
  }
  $("cond-modal-dia").textContent = "→ " + dia.id;
  $("cond-name").value = "";
  $("cond-when").value = "";
  $("cond-error").style.display = "none";
  const grid = $("cond-nodes");
  grid.innerHTML = "";
  (dia.nodes || []).forEach((n) => {
    const lab = document.createElement("label");
    lab.innerHTML = `<input type="checkbox" value="${escapeHtml(n)}">${escapeHtml(n)}`;
    grid.appendChild(lab);
  });
  $("modal-backdrop").classList.remove("hidden");
  $("cond-name").focus();
}
function closeCondModal() { $("modal-backdrop").classList.add("hidden"); }

async function openLlm() {
  state.llmSelection = editor ? editor.getSelection() : null;
  const selected = editor && !state.llmSelection.isEmpty();
  const saved = JSON.parse(localStorage.getItem("mdflow.llm") || "{}");
  $("llm-provider").value = saved.provider || "openai";
  $("llm-url").value = saved.url || "http://127.0.0.1:1234/v1";
  $("llm-timeout").value = saved.timeout || 120;
  $("llm-purpose").value = saved.purpose || "quick";
  $("llm-scope").value = selected ? "selection" : "section";
  $("llm-scope").querySelector('option[value="selection"]').disabled = !selected;
  $("llm-result").classList.add("hidden");
  $("llm-backdrop").classList.remove("hidden");
  $("llm-instruction").focus();
  updateLlmScope();
  await connectLlm(false);
}

function llmSettings() {
  return { provider: $("llm-provider").value, url: $("llm-url").value.trim(),
    timeout: Number($("llm-timeout").value) || 120, purpose: $("llm-purpose").value,
    roles: JSON.parse(localStorage.getItem("mdflow.llm.roles") || "{}") };
}

async function connectLlm(notify = true) {
  const settings = llmSettings(); localStorage.setItem("mdflow.llm", JSON.stringify(settings));
  const status = $("llm-status"); status.textContent = "確認中..."; status.className = "badge";
  try {
    const info = await api("/api/llm/models", settings);
    const models = $("llm-model"); models.innerHTML = "";
    (info.models || []).forEach((name) => { const option = document.createElement("option"); option.value = name; option.textContent = name; models.appendChild(option); });
    const roleModel = settings.roles[settings.purpose];
    if (roleModel && [...models.options].some((o) => o.value === roleModel)) models.value = roleModel;
    status.textContent = info.available ? `${settings.provider} ✓` : "未接続";
    status.className = `badge ${info.available ? "ok" : "danger"}`;
    if (!info.available) { $("llm-result").classList.remove("hidden"); $("llm-answer").textContent = info.error; }
    else if (notify) toast("LLM接続設定を保存しました");
  } catch (e) { status.textContent = "未接続"; status.className = "badge danger"; }
}

function llmTarget() {
  const model = editor && editor.getModel(); const scope = $("llm-scope").value;
  if (model && scope === "selection" && state.llmSelection && !state.llmSelection.isEmpty())
    return { text: model.getValueInRange(state.llmSelection), range: state.llmSelection, label: "選択範囲" };
  if (model && scope === "section") {
    const cursor = editor.getPosition().lineNumber; const lines = editorText().split("\n");
    let start = 1, level = 0, end = lines.length;
    for (let i = cursor - 1; i >= 0; i--) { const m = lines[i].match(/^(#{1,6})\s/); if (m) { start = i + 1; level = m[1].length; break; } }
    if (level) for (let i = start; i < lines.length; i++) { const m = lines[i].match(/^(#{1,6})\s/); if (m && m[1].length <= level) { end = i; break; } }
    const range = new monaco.Range(start, 1, end, model.getLineMaxColumn(end));
    return { text: model.getValueInRange(range), range, label: level ? "現在の見出し" : "文書全体" };
  }
  return { text: editorText(), range: model ? model.getFullModelRange() : null, label: "文書全体" };
}

function updateLlmScope() {
  const target = llmTarget(); state.llmTargetRange = target.range;
  $("llm-scope-label").textContent = `${target.label}（${target.text.length.toLocaleString()}文字）`;
  $("llm-token-estimate").textContent = `約${Math.ceil(target.text.length / 3).toLocaleString()} tokens`;
}

async function runLlm(mode) {
  const instruction = $("llm-instruction").value.trim();
  if (!instruction) { toast("依頼または質問を入力してください"); return; }
  const settings = llmSettings(); const target = llmTarget(); state.llmTargetRange = target.range;
  localStorage.setItem("mdflow.llm", JSON.stringify(settings));
  settings.roles[settings.purpose] = $("llm-model").value;
  localStorage.setItem("mdflow.llm.roles", JSON.stringify(settings.roles));
  state.llmMode = mode; $("llm-result").classList.remove("hidden");
  $("llm-apply-actions").classList.add("hidden"); $("llm-diff").classList.add("hidden"); $("llm-answer").classList.remove("hidden");
  $("llm-answer").textContent = ""; $("llm-validation").textContent = "";
  $("llm-stop").classList.remove("hidden"); llmAbort = new AbortController();
  const timer = setTimeout(() => llmAbort.abort("timeout"), settings.timeout * 1000);
  try {
    const response = await fetch("/api/llm/stream", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ...settings, mode, instruction, text: target.text, model: $("llm-model").value }), signal: llmAbort.signal });
    const reader = response.body.getReader(), decoder = new TextDecoder(); let answer = "";
    while (true) { const { value, done } = await reader.read(); if (done) break; answer += decoder.decode(value, { stream: true }); $("llm-answer").textContent = answer; }
    const errorMarker = "\x1eMDFLOW_ERROR:", errorAt = answer.indexOf(errorMarker);
    if (errorAt >= 0) throw new Error(answer.slice(errorAt + errorMarker.length));
    state.llmAnswer = stripOuterFence(answer.trim());
    $("llm-answer").textContent = state.llmAnswer;
    if (mode === "edit") { showLlmDiff(target.text, state.llmAnswer); await validateLlmEdit(); $("llm-apply-actions").classList.remove("hidden"); }
  } catch (e) { $("llm-answer").classList.remove("hidden"); $("llm-answer").textContent = e.name === "AbortError" ? "生成を停止しました。" : e.message; }
  finally { clearTimeout(timer); llmAbort = null; $("llm-stop").classList.add("hidden"); }
}

function stripOuterFence(text) { const match = text.match(/^```(?:markdown)?\s*\n([\s\S]*?)\n```$/); return match ? match[1] : text; }

function showLlmDiff(original, modified) {
  $("llm-answer").classList.add("hidden"); $("llm-diff").classList.remove("hidden");
  if (llmDiffEditor) llmDiffEditor.dispose(); llmDiffModels.forEach((model) => model.dispose());
  llmDiffModels = [monaco.editor.createModel(original, "markdown"), monaco.editor.createModel(modified, "markdown")];
  llmDiffEditor = monaco.editor.createDiffEditor($("llm-diff"), { theme: "mdflow-dark", automaticLayout: true,
    readOnly: false, originalEditable: false, renderSideBySide: true, minimap: { enabled: false }, wordWrap: "on" });
  llmDiffEditor.setModel({ original: llmDiffModels[0], modified: llmDiffModels[1] });
  llmDiffModels[1].onDidChangeContent(() => { state.llmAnswer = llmDiffModels[1].getValue(); clearTimeout(llmValidationTimer);
    llmValidationTimer = setTimeout(validateLlmEdit, 700); });
}

function candidateDocument() {
  if (!editor || !state.llmTargetRange) return state.llmAnswer;
  const model = editor.getModel(); const start = model.getOffsetAt(state.llmTargetRange.getStartPosition());
  const end = model.getOffsetAt(state.llmTargetRange.getEndPosition());
  return editorText().slice(0, start) + state.llmAnswer + editorText().slice(end);
}

async function validateLlmEdit() {
  const text = candidateDocument(), errors = []; const fences = (text.match(/^```/gm) || []).length;
  if (fences % 2) errors.push("コードフェンスが閉じていません");
  const ids = [...text.matchAll(/%%\s*id\s*:\s*(\S+)/g)].map((m) => m[1]);
  const duplicates = [...new Set(ids.filter((id, i) => ids.indexOf(id) !== i))];
  if (duplicates.length) errors.push(`図ID重複: ${duplicates.join(", ")}`);
  for (const match of text.matchAll(/```mermaid\s*\n([\s\S]*?)```/g)) {
    try { if (window.mermaid?.parse) await window.mermaid.parse(match[1]); } catch (e) { errors.push(`Mermaid: ${e.message || e}`); }
  }
  for (const match of text.matchAll(/```(?:plantuml|puml)\s*\n([\s\S]*?)```/g)) {
    const result = await api("/api/plantuml", { source: match[1] }); if (result.error) errors.push(`PlantUML: ${result.error}`);
  }
  $("llm-validation").textContent = errors.length ? `⚠ ${errors.join(" / ")}` : "✓ 構文検証済み";
  $("llm-validation").className = errors.length ? "badge danger" : "badge ok";
}

function applyLlmEdit() {
  const value = llmDiffModels[1] ? llmDiffModels[1].getValue() : state.llmAnswer;
  if (!editor) { setEditorText(value); }
  else {
    const range = state.llmTargetRange || editor.getModel().getFullModelRange();
    editor.pushUndoStop(); editor.executeEdits("local-llm", [{ range, text: value, forceMoveMarkers: true }]);
    editor.pushUndoStop(); editor.focus();
  }
  $("llm-backdrop").classList.add("hidden"); toast("編集案を適用しました（Undoできます）");
}

async function submitCond() {
  const name = $("cond-name").value.trim();
  const when = $("cond-when").value.trim();
  const nodes = [...$("cond-nodes").querySelectorAll("input:checked")].map((c) => c.value);
  const err = $("cond-error");
  if (!name) { err.textContent = "プリセット名を入力してください"; err.style.display = ""; return; }
  const res = JSON.parse(
    (await bcall("addPreset", editorText(), state.selectedId, name, when, JSON.stringify(nodes))) || "{}");
  if (res.error) { err.textContent = res.error; err.style.display = ""; return; }
  setEditorText(res.md);
  closeCondModal();
  await render();
  $("sel-preset").value = name;   // 登録直後のプリセットを選択表示
  await render();
  toast(res.message || "登録しました");
}

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
  $("btn-add-cond").onclick = openCondModal;
  $("btn-llm").onclick = openLlm;
  $("btn-zoom-in").onclick = () => changeZoom(.1);
  $("btn-zoom-out").onclick = () => changeZoom(-.1);
  $("btn-copy-svg").onclick = copySvg;
  $("btn-copy-png").onclick = copyPng;
  $("btn-save-diagram").onclick = saveDiagram;
  $("llm-close").onclick = () => { if (llmAbort) llmAbort.abort(); $("llm-backdrop").classList.add("hidden"); };
  $("llm-connect").onclick = () => connectLlm(true);
  $("llm-provider").onchange = () => { $("llm-url").value = $("llm-provider").value === "ollama" ? "http://127.0.0.1:11434" : "http://127.0.0.1:1234/v1"; };
  $("llm-purpose").onchange = () => { const roles = JSON.parse(localStorage.getItem("mdflow.llm.roles") || "{}"); const model = roles[$("llm-purpose").value]; if (model && [...$("llm-model").options].some((o) => o.value === model)) $("llm-model").value = model; updateLlmScope(); };
  $("llm-scope").onchange = updateLlmScope;
  $("llm-stop").onclick = () => { if (llmAbort) llmAbort.abort(); };
  $("llm-ask").onclick = () => runLlm("ask");
  $("llm-edit").onclick = () => runLlm("edit");
  $("llm-apply").onclick = applyLlmEdit;
  $("cond-cancel").onclick = closeCondModal;
  $("cond-submit").onclick = submitCond;
  $("modal-backdrop").addEventListener("click", (e) => {
    if (e.target.id === "modal-backdrop") closeCondModal();
  });
  $("editor-fallback").addEventListener("input", scheduleRender);
  $("conditions").addEventListener("input", scheduleRender);
  $("preview").addEventListener("scroll", syncEditorFromPreview);
  $("preview").addEventListener("click", selectPreviewDiagram);
  $("sel-diagram").addEventListener("change", () => { state.selectedId = $("sel-diagram").value; render(); });
  $("sel-preset").addEventListener("change", render);
  initDivider();
}

// ---- 起動 ----
window.addEventListener("DOMContentLoaded", async () => {
  initRenderers();
  wire();
  api("/api/initial").then(async (initial) => {
    await initEditor(initial.text || "");
    await render();
  }).catch((e) => toast("初期化に失敗しました: " + e.message));
});
