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
  llmSelection: null, llmMode: "ask", syncingScroll: false, fileHandle: null,
  directoryHandle: null, activeExplorerPath: "", lastSaved: "", lastModified: 0,
  llmServers: [], recoveryTimer: null, autoSaveTimer: null };

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
      editor.onDidChangeModelContent(() => { scheduleRender(); updateOutline(); documentChanged(); });
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
        const named = source.match(/^\s*@startuml\s+(\S+)/m);
        const id = named ? named[1] : `plantuml-${env.pumlIndex++}`;
        return `<div class="plantuml-box" data-line="${line}" data-id="${escapeHtml(id)}"><pre class="plantuml-source">${escapeHtml(source)}</pre><div class="plantuml-status">PlantUML を描画中...</div></div>`;
      }
      if (info !== "mermaid") return defFence(tokens, idx, options, env, self);
      let code = token.content.replace(/\n$/, "");
      const idm = code.match(/%%\s*id\s*:\s*(\S+)/);
      const id = idm ? idm[1] : "#" + env.mmIndex;
      env.mmIndex++;
      const selected = id === env.selectedId;
      if (selected && env.injected) code = env.injected;
      const cls = selected ? "mermaid-box selected" : "mermaid-box";
      return `<div class="${cls}" data-id="${escapeHtml(id)}"><pre class="mermaid">${escapeHtml(code)}</pre></div>`;
    };
  }
  if (window.mermaid) {
    $("status-engine").textContent = "mermaid ✓";
    window.mermaid.initialize({ startOnLoad: false, theme: "dark", securityLevel: "strict" });
  } else {
    $("status-engine").innerHTML =
      '<span class="badge danger">mermaid未配置: scripts/fetch_mermaid.py</span>';
  }
  api("/api/plantuml/diagnostics").then((info) => {
    const suffix = info.available ? `PlantUML ${info.version || "✓"}${info.graphviz ? " / Graphviz ✓" : ""}` : "PlantUML 未設定";
    $("status-engine").textContent += ` / ${suffix}`;
    $("status-engine").title = info.available ? `cache: ${info.cache} / concurrency: ${info.concurrency}` : (info.error || "");
  });
}

const DIAGRAM_TEMPLATES = {
  sequence: "```plantuml\n@startuml sequence-name\nactor User\nparticipant App\nUser -> App: Request\nApp --> User: Response\n@enduml\n```\n",
  class: "```plantuml\n@startuml class-name\nclass Example {\n  +method()\n}\n@enduml\n```\n",
  c4: "```plantuml\n@startuml architecture\n!include <C4/C4_Container>\nPerson(user, \"User\")\nContainer(app, \"Application\", \"Technology\")\nRel(user, app, \"Uses\")\n@enduml\n```\n",
  mermaid: "```mermaid\n%% id: flow-name\nflowchart TD\n  A[Start] --> B[End]\n```\n",
};
function insertDiagramTemplate() {
  const text = DIAGRAM_TEMPLATES[$("diagram-template").value]; if (!text || !editor) return;
  const selection = editor.getSelection(); editor.executeEdits("template", [{ range: selection, text, forceMoveMarkers: true }]);
  editor.focus(); $("diagram-template").value = "";
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
    const env = { mmIndex: 0, pumlIndex: 0, selectedId: state.selectedId, injected: res.injected || "" };
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
  return rasterizeElement(selectedDiagramElement(), Number($("export-scale").value) || 2);
}

function rasterizeElement(box, scale = 2) {
  return new Promise((resolve, reject) => {
    if (!box) return reject(new Error("描画済みの図が見つかりません"));
    const rect = box.getBoundingClientRect();
    const zoom = Number(box.style.transform.match(/scale\(([^)]+)\)/)?.[1] || 1);
    const w = Math.max(1, Math.round(rect.width / zoom)), h = Math.max(1, Math.round(rect.height / zoom));
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

async function collectRenderedDiagrams() {
  await render();
  const elements = [...document.querySelectorAll("#preview .mermaid-box svg, #preview .plantuml-diagram")];
  return Promise.all(elements.map(async (element, index) => ({
    name: element.closest(".mermaid-box, .plantuml-box")?.dataset.id || `diagram-${index + 1}`,
    svg: element.tagName.toLowerCase() === "svg" ? new XMLSerializer().serializeToString(element) : await (await fetch(element.src)).text(),
    png_dataurl: await rasterizeElement(element, Number($("export-scale").value) || 2),
  })));
}

async function exportAll(path, filename) {
  try {
    const diagrams = await collectRenderedDiagrams();
    if (!diagrams.length) throw new Error("出力する図がありません");
    const response = await fetch(path, { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ diagrams, md: editorText() }) });
    if (!response.ok) throw new Error(await response.text());
    download(await response.blob(), filename); toast(`${diagrams.length}件の図を出力しました`);
  } catch (e) { toast("一括出力失敗: " + e.message); }
}

const COMMANDS = [
  ["フォルダーを開く", openExplorerFolder], ["ファイルを開く", onOpen], ["保存", onSave], ["名前を付けて保存", onSaveAs],
  ["Local LLMを開く", openLlm], ["選択図をSVGコピー", copySvg], ["選択図をPNGコピー", copyPng],
  ["選択図をSVG保存", saveDiagram], ["全図をZIP出力", () => exportAll("/api/export/bundle", "mdflow-diagrams.zip")],
  ["全図をPPT出力", () => exportAll("/api/export/ppt-multi", "mdflow-diagrams.pptx")],
  ["Mermaidの全経路を自動生成", generateAllPaths], ["PDF印刷", () => window.print()],
  ["図テンプレートを挿入", () => $("diagram-template").focus()],
];

function openCommandPalette() {
  $("command-backdrop").classList.remove("hidden"); $("command-query").value = ""; renderCommands(); $("command-query").focus();
}
function closeCommandPalette() { $("command-backdrop").classList.add("hidden"); }
function renderCommands() {
  const query = $("command-query").value.toLowerCase(); const host = $("command-items"); host.innerHTML = "";
  COMMANDS.filter(([label]) => label.toLowerCase().includes(query)).forEach(([label, action], index) => {
    const button = document.createElement("button"); button.className = `command-item${index === 0 ? " active" : ""}`;
    button.textContent = label; button.onclick = () => { closeCommandPalette(); action(); }; host.appendChild(button);
  });
}

function showDiagramContext(event) {
  const box = event.target.closest(".mermaid-box, .plantuml-box"); if (!box) return;
  event.preventDefault(); selectPreviewDiagram(event); const menu = $("diagram-context");
  menu.style.left = `${Math.min(event.clientX, innerWidth - 160)}px`; menu.style.top = `${Math.min(event.clientY, innerHeight - 160)}px`;
  menu.classList.remove("hidden");
}
function runContextCommand(name) {
  ({ "copy-svg": copySvg, "copy-png": copyPng, "save-diagram": saveDiagram,
    "export-all": () => exportAll("/api/export/bundle", "mdflow-diagrams.zip") })[name]?.();
  $("diagram-context").classList.add("hidden");
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
  if (window.showOpenFilePicker) {
    try {
      const [handle] = await window.showOpenFilePicker({ types: [{ description: "Markdown", accept: { "text/markdown": [".md", ".markdown"] } }] });
      await loadFileHandle(handle); return;
    } catch (e) { if (e.name === "AbortError") return; }
  }
  const file = await chooseFile(".md,text/markdown,text/plain");
  if (file) {
    setEditorText(await file.text());
    $("file-name").textContent = file.name;
    state.fileHandle = null; markSaved();
    await render(); toast("Markdownを開きました");
  }
}

async function openExplorerFolder() {
  if (!window.showDirectoryPicker) { toast("このブラウザはフォルダー表示に対応していません"); return; }
  try {
    const handle = await window.showDirectoryPicker({ mode: "readwrite" });
    state.directoryHandle = handle;
    const db = await fileDb();
    db.transaction("handles", "readwrite").objectStore("handles").put(handle, "__workspace__");
    await refreshExplorer();
  } catch (e) { if (e.name !== "AbortError") toast("フォルダーを開けません: " + e.message); }
}

async function restoreExplorerFolder() {
  try {
    const db = await fileDb();
    const request = db.transaction("handles").objectStore("handles").get("__workspace__");
    request.onsuccess = async () => {
      const handle = request.result;
      if (handle && await handle.queryPermission({ mode: "read" }) === "granted") {
        state.directoryHandle = handle; await refreshExplorer();
      }
    };
  } catch (_) { /* IndexedDBまたは権限が利用できない場合は未選択表示を維持 */ }
}

async function refreshExplorer() {
  const root = $("explorer-tree"); root.innerHTML = "";
  if (!state.directoryHandle) { root.innerHTML = '<div class="explorer-empty">📁 を押して作業フォルダーを選択</div>'; return; }
  if (!await ensureFilePermission(state.directoryHandle, false)) { toast("フォルダーの読み取りが許可されませんでした"); return; }
  $("explorer-name").textContent = state.directoryHandle.name;
  await appendDirectoryEntries(state.directoryHandle, root, "", 0);
  if (!root.children.length) root.innerHTML = '<div class="explorer-empty">フォルダーは空です</div>';
}

async function appendDirectoryEntries(handle, host, parentPath, depth) {
  const entries = [];
  for await (const entry of handle.values()) entries.push(entry);
  entries.sort((a, b) => (a.kind === b.kind ? a.name.localeCompare(b.name, "ja") : a.kind === "directory" ? -1 : 1));
  for (const entry of entries) {
    const path = parentPath ? `${parentPath}/${entry.name}` : entry.name;
    if (entry.kind === "directory") {
      const container = document.createElement("div"); container.className = "explorer-directory";
      const button = explorerButton(entry.name, "▸", depth); const children = document.createElement("div"); children.className = "explorer-children";
      let loaded = false;
      button.onclick = async () => { container.classList.toggle("open"); button.querySelector(".twisty").textContent = container.classList.contains("open") ? "▾" : "▸";
        if (!loaded) { loaded = true; await appendDirectoryEntries(entry, children, path, depth + 1); } };
      container.append(button, children); host.appendChild(container);
    } else {
      const supported = /\.(md|markdown|txt)$/i.test(entry.name);
      const button = explorerButton(entry.name, "", depth); button.dataset.path = path;
      if (!supported) { button.classList.add("unsupported"); button.title = "Markdown／テキストファイルのみ編集できます"; }
      else button.onclick = () => loadFileHandle(entry, `${state.directoryHandle.name}/${path}`).catch((e) => toast(e.message));
      host.appendChild(button);
    }
  }
}

function explorerButton(name, twisty, depth) {
  const button = document.createElement("button"); button.className = "explorer-item"; button.style.paddingLeft = `${7 + depth * 13}px`;
  const marker = document.createElement("span"); marker.className = "twisty"; marker.textContent = twisty;
  const label = document.createElement("span"); label.className = "entry-name"; label.textContent = name;
  button.append(marker, label); return button;
}
async function onSave() {
  if (state.fileHandle) {
    try { await writeFileHandle(); toast("Markdownを上書き保存しました"); return; }
    catch (e) { toast("上書き保存失敗: " + e.message); return; }
  }
  const filename = ($("file-name").textContent || "mdflow.md").split(/[\\/]/).pop();
  download(new Blob([editorText()], { type: "text/markdown;charset=utf-8" }), filename);
  markSaved(); toast("Markdownを保存しました");
}

async function onSaveAs() {
  if (!window.showSaveFilePicker) { await onSave(); return; }
  try {
    const handle = await window.showSaveFilePicker({ suggestedName: ($("file-name").textContent || "mdflow.md").replace(/\s●$/, ""),
      types: [{ description: "Markdown", accept: { "text/markdown": [".md"] } }] });
    state.fileHandle = handle; $("file-name").textContent = handle.name; await writeFileHandle(); await rememberFile(handle); toast("保存しました");
  } catch (e) { if (e.name !== "AbortError") toast("保存失敗: " + e.message); }
}

function documentChanged() {
  const dirty = editorText() !== state.lastSaved; $("file-name").classList.toggle("dirty", dirty);
  clearTimeout(state.recoveryTimer); state.recoveryTimer = setTimeout(() => {
    if (editorText() !== state.lastSaved) localStorage.setItem("mdflow.recovery", JSON.stringify({ text: editorText(), name: $("file-name").textContent, at: Date.now() }));
  }, 400);
  if (dirty && $("auto-save").checked && state.fileHandle) {
    clearTimeout(state.autoSaveTimer); state.autoSaveTimer = setTimeout(() => writeFileHandle().catch((e) => toast("自動保存失敗: " + e.message)), 900);
  }
}

function markSaved() {
  state.lastSaved = editorText(); $("file-name").classList.remove("dirty"); localStorage.removeItem("mdflow.recovery");
}

async function loadFileHandle(handle, displayPath = handle.name) {
  if (!await ensureFilePermission(handle, false)) throw new Error("ファイルの読み取りが許可されませんでした");
  const file = await handle.getFile(); state.fileHandle = handle; state.lastModified = file.lastModified;
  setEditorText(await file.text()); $("file-name").textContent = displayPath; state.activeExplorerPath = displayPath.replace(/^[^/]+\//, "");
  document.querySelectorAll(".explorer-item.active").forEach((item) => item.classList.remove("active"));
  document.querySelector(`.explorer-item[data-path="${CSS.escape(state.activeExplorerPath)}"]`)?.classList.add("active");
  markSaved(); await rememberFile(handle); await render(); toast("Markdownを開きました");
}

async function writeFileHandle() {
  if (!await ensureFilePermission(state.fileHandle, true)) throw new Error("書き込みが許可されませんでした");
  const writable = await state.fileHandle.createWritable(); await writable.write(editorText()); await writable.close();
  const file = await state.fileHandle.getFile(); state.lastModified = file.lastModified; markSaved();
}

async function ensureFilePermission(handle, write) {
  const options = { mode: write ? "readwrite" : "read" };
  if ((await handle.queryPermission(options)) === "granted") return true;
  return (await handle.requestPermission(options)) === "granted";
}

function fileDb() {
  return new Promise((resolve, reject) => { const request = indexedDB.open("mdflow-files", 1);
    request.onupgradeneeded = () => request.result.createObjectStore("handles"); request.onsuccess = () => resolve(request.result); request.onerror = () => reject(request.error); });
}
async function rememberFile(handle) {
  const db = await fileDb(); const tx = db.transaction("handles", "readwrite"); tx.objectStore("handles").put(handle, handle.name);
  const recent = JSON.parse(localStorage.getItem("mdflow.recent") || "[]").filter((name) => name !== handle.name);
  recent.unshift(handle.name); localStorage.setItem("mdflow.recent", JSON.stringify(recent.slice(0, 8))); refreshRecentFiles();
}
function refreshRecentFiles() {
  const select = $("recent-files"); select.innerHTML = '<option value="">最近使ったファイル</option>';
  JSON.parse(localStorage.getItem("mdflow.recent") || "[]").forEach((name) => { const option = document.createElement("option"); option.value = name; option.textContent = name; select.appendChild(option); });
}
async function openRecent(name) {
  if (!name) return; try { const db = await fileDb(); const request = db.transaction("handles").objectStore("handles").get(name);
    request.onsuccess = () => request.result ? loadFileHandle(request.result).catch((e) => toast(e.message)) : toast("ファイル履歴が見つかりません"); }
  catch (e) { toast("履歴を開けません: " + e.message); }
}

async function checkExternalChange() {
  if (!state.fileHandle) return;
  try { const file = await state.fileHandle.getFile(); if (state.lastModified && file.lastModified > state.lastModified) {
    if (editorText() === state.lastSaved || confirm("ファイルが外部で変更されました。再読み込みしますか？")) await loadFileHandle(state.fileHandle);
    else { state.lastModified = file.lastModified; toast("外部変更があります（未保存編集を保持）"); }
  } } catch (_) { /* permission may be unavailable while the window is inactive */ }
}

function offerRecovery(initialText) {
  const recovery = JSON.parse(localStorage.getItem("mdflow.recovery") || "null");
  if (!recovery || recovery.text === initialText) return;
  $("recovery-banner").classList.remove("hidden");
  $("btn-recover").onclick = () => { setEditorText(recovery.text); $("file-name").textContent = recovery.name || "recovered.md";
    $("recovery-banner").classList.add("hidden"); toast("未保存の編集を復元しました"); };
  $("btn-dismiss-recovery").onclick = () => { localStorage.removeItem("mdflow.recovery"); $("recovery-banner").classList.add("hidden"); };
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

async function generateAllPaths() {
  const diagram = state.diagrams.find((item) => item.id === state.selectedId);
  if (!diagram) { toast("Mermaid flowchartを選択してください"); return; }
  try {
    const result = await api("/api/preset/all-paths", {
      md: editorText(), diagram_id: state.selectedId, limit: 100,
    });
    if (result.error) { toast(result.error); return; }
    const preview = (result.paths || []).slice(0, 8).map((path, index) =>
      `${index + 1}. ${path.join(" → ")}`).join("\n");
    const suffix = result.count > 8 ? `\n…ほか${result.count - 8}件` : "";
    if (!confirm(`${result.count}件の全経路プリセットを生成します。\n\n${preview}${suffix}`)) return;
    setEditorText(result.md);
    await render();
    const warning = (result.warnings || []).join(" / ");
    toast(`${result.count}件の経路を生成しました${warning ? `（${warning}）` : ""}`);
  } catch (e) { toast("全経路の生成に失敗しました: " + e.message); }
}

async function openLlm() {
  state.llmSelection = editor ? editor.getSelection() : null;
  const selected = editor && !state.llmSelection.isEmpty();
  const saved = JSON.parse(localStorage.getItem("mdflow.llm") || "{}");
  $("llm-timeout").value = saved.timeout || 120;
  $("llm-purpose").value = saved.purpose || "quick";
  $("llm-policy").value = saved.policy || "all";
  $("llm-scope").value = selected ? "selection" : "section";
  $("llm-scope").querySelector('option[value="selection"]').disabled = !selected;
  $("llm-result").classList.add("hidden");
  $("llm-history").classList.add("hidden");
  $("llm-confirm").checked = false; $("llm-apply").disabled = true;
  $("llm-backdrop").classList.remove("hidden");
  $("llm-instruction").focus();
  updateLlmScope();
  try { await loadLlmServers(); await connectLlm(false); }
  catch (e) { $("llm-status").textContent = "設定エラー"; $("llm-status").className = "badge danger";
    $("llm-result").classList.remove("hidden"); $("llm-answer").textContent = e.message; }
}

function llmSettings() {
  return { server_index: Number($("llm-server").value || 0),
    timeout: Number($("llm-timeout").value) || 120, purpose: $("llm-purpose").value,
    policy: $("llm-policy").value,
    roles: JSON.parse(localStorage.getItem("mdflow.llm.roles") || "{}") };
}

function saveLlmPreferences(settings) {
  localStorage.setItem("mdflow.llm", JSON.stringify({ timeout: settings.timeout,
    purpose: settings.purpose, policy: settings.policy }));
}

function applySelectedLlmServer() {
  const selected = state.llmServers[Number($("llm-server").value || 0)];
  $("llm-provider").value = selected?.provider || "";
  $("llm-url").value = selected?.base_url || "";
}

async function loadLlmServers() {
  const info = await api("/api/llm/servers");
  $("llm-config-path").textContent = info.config_path || "config.json";
  if (info.error) throw new Error(info.error);
  state.llmServers = info.servers || [];
  const select = $("llm-server"); select.innerHTML = "";
  state.llmServers.forEach((server, index) => { const option = document.createElement("option");
    option.value = String(index); option.textContent = server.name || server.base_url; select.appendChild(option); });
  select.value = String(info.active || 0); applySelectedLlmServer();
}

async function connectLlm(notify = true) {
  const settings = llmSettings(); saveLlmPreferences(settings);
  const status = $("llm-status"); status.textContent = "確認中..."; status.className = "badge";
  try {
    if (notify) {
      const saved = await api("/api/llm/settings", { active_server: settings.server_index });
      if (!saved.ok) throw new Error(saved.error || "接続先を保存できませんでした");
    }
    const info = await api("/api/llm/models", settings);
    const models = $("llm-model"); models.innerHTML = "";
    (info.models || []).forEach((name) => { const option = document.createElement("option"); option.value = name; option.textContent = name; models.appendChild(option); });
    const roleModel = settings.roles[settings.purpose];
    if (roleModel && [...models.options].some((o) => o.value === roleModel)) models.value = roleModel;
    else if (info.current && [...models.options].some((o) => o.value === info.current)) models.value = info.current;
    status.textContent = info.available ? `${settings.provider} ✓` : "未接続";
    status.className = `badge ${info.available ? "ok" : "danger"}`;
    if (!info.available) { $("llm-result").classList.remove("hidden"); $("llm-answer").textContent = info.error; }
    else if (notify) toast("LLM接続先をconfig.jsonへ保存しました");
  } catch (e) { status.textContent = "未接続"; status.className = "badge danger"; status.title = e.message; }
}

async function saveLlmModel() {
  const result = await api("/api/llm/settings", { active_server: Number($("llm-server").value || 0),
    model: $("llm-model").value });
  if (!result.ok) toast(result.error || "モデルを保存できませんでした");
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
  if ($("llm-scope").value === "smart") {
    $("llm-scope-label").textContent = "質問に関連する見出しをローカル検索";
    $("llm-token-estimate").textContent = "依頼入力後に計算";
    return;
  }
  const target = llmTarget(); state.llmTargetRange = target.range;
  $("llm-scope-label").textContent = `${target.label}（${target.text.length.toLocaleString()}文字）`;
  $("llm-token-estimate").textContent = `約${Math.ceil(target.text.length / 3).toLocaleString()} tokens`;
}

async function runLlm(mode) {
  const instruction = $("llm-instruction").value.trim();
  if (!instruction) { toast("依頼または質問を入力してください"); return; }
  const settings = llmSettings(); let target = llmTarget();
  if ($("llm-scope").value === "smart") {
    if (mode === "edit") { toast("関連検索は質問用です。編集範囲を選択してください"); return; }
    const relevant = await api("/api/llm/context", { md: editorText(), query: instruction });
    target = { text: relevant.text, range: null, label: relevant.chunks.map((item) => item.title).join(" / ") };
    $("llm-scope-label").textContent = `関連箇所: ${target.label}`;
    $("llm-token-estimate").textContent = `約${Math.ceil(target.text.length / 3).toLocaleString()} tokens`;
  }
  state.llmTargetRange = target.range;
  saveLlmPreferences(settings);
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
    if (mode === "edit") {
      const repaired = await api("/api/llm/repair", { original: target.text, candidate: state.llmAnswer, policy: settings.policy });
      state.llmAnswer = repaired.text;
      $("llm-repair-note").textContent = repaired.warnings?.length ? `自動保護: ${repaired.warnings.join(" / ")}` : "";
    }
    $("llm-answer").textContent = state.llmAnswer;
    if (mode === "edit") { showLlmDiff(target.text, state.llmAnswer); await validateLlmEdit(); $("llm-confirm").checked = false;
      $("llm-apply").disabled = true; $("llm-apply-actions").classList.remove("hidden"); }
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
  if (!$("llm-confirm").checked) { toast("差分と検証結果の確認が必要です"); return; }
  const value = llmDiffModels[1] ? llmDiffModels[1].getValue() : state.llmAnswer;
  const beforeDocument = editorText();
  if (!editor) { setEditorText(value); }
  else {
    const range = state.llmTargetRange || editor.getModel().getFullModelRange();
    editor.pushUndoStop(); editor.executeEdits("local-llm", [{ range, text: value, forceMoveMarkers: true }]);
    editor.pushUndoStop(); editor.focus();
  }
  saveLlmSnapshot(beforeDocument, editorText());
  $("llm-backdrop").classList.add("hidden"); toast("編集案を適用しました（Undoできます）");
}

function saveLlmSnapshot(before, after) {
  const history = JSON.parse(localStorage.getItem("mdflow.llm.history") || "[]");
  history.unshift({ at: new Date().toISOString(), instruction: $("llm-instruction").value, before, after });
  localStorage.setItem("mdflow.llm.history", JSON.stringify(history.slice(0, 10)));
}

function showLlmHistory() {
  const history = JSON.parse(localStorage.getItem("mdflow.llm.history") || "[]");
  const host = $("llm-history-items"); host.innerHTML = ""; $("llm-history").classList.remove("hidden");
  history.forEach((item, index) => { const row = document.createElement("div"); row.className = "history-item";
    const text = document.createElement("div"); text.innerHTML = `<div>${escapeHtml(item.instruction || "LLM編集")}</div><small>${new Date(item.at).toLocaleString()}</small>`;
    const restore = document.createElement("button"); restore.textContent = "復元"; restore.onclick = () => {
      saveLlmSnapshot(editorText(), item.before); setEditorText(item.before); toast("編集前スナップショットを復元しました"); };
    row.append(text, restore); host.appendChild(row); });
  if (!history.length) host.textContent = "履歴はありません。";
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
    const explorerRight = $("file-explorer").getBoundingClientRect().right;
    const ratio = Math.min(0.8, Math.max(0.2, (e.clientX - explorerRight) / Math.max(1, r.right - explorerRight)));
    left.style.flex = `1 1 ${ratio * 100}%`;
  });
}

function wire() {
  $("btn-open").onclick = onOpen;
  $("btn-save").onclick = onSave;
  $("btn-save-as").onclick = onSaveAs;
  $("btn-export").onclick = onExport;
  $("btn-import").onclick = onImport;
  $("btn-add-cond").onclick = openCondModal;
  $("btn-generate-paths").onclick = generateAllPaths;
  $("btn-open-folder").onclick = openExplorerFolder;
  $("btn-refresh-folder").onclick = refreshExplorer;
  $("btn-insert-template").onclick = insertDiagramTemplate;
  $("btn-llm").onclick = openLlm;
  $("btn-command").onclick = openCommandPalette;
  $("btn-zoom-in").onclick = () => changeZoom(.1);
  $("btn-zoom-out").onclick = () => changeZoom(-.1);
  $("btn-copy-svg").onclick = copySvg;
  $("btn-copy-png").onclick = copyPng;
  $("btn-save-diagram").onclick = saveDiagram;
  $("btn-export-all").onclick = () => exportAll("/api/export/bundle", "mdflow-diagrams.zip");
  $("btn-export-ppt-all").onclick = () => exportAll("/api/export/ppt-multi", "mdflow-diagrams.pptx");
  $("btn-print-pdf").onclick = () => window.print();
  $("llm-close").onclick = () => { if (llmAbort) llmAbort.abort(); $("llm-backdrop").classList.add("hidden"); };
  $("llm-connect").onclick = () => connectLlm(true);
  $("llm-server").onchange = () => { applySelectedLlmServer(); connectLlm(false); };
  $("llm-model").onchange = saveLlmModel;
  $("llm-purpose").onchange = () => { const roles = JSON.parse(localStorage.getItem("mdflow.llm.roles") || "{}"); const model = roles[$("llm-purpose").value]; if (model && [...$("llm-model").options].some((o) => o.value === model)) $("llm-model").value = model; updateLlmScope(); };
  $("llm-scope").onchange = updateLlmScope;
  $("llm-history-open").onclick = showLlmHistory;
  $("llm-confirm").onchange = () => { $("llm-apply").disabled = !$("llm-confirm").checked; };
  $("llm-stop").onclick = () => { if (llmAbort) llmAbort.abort(); };
  $("llm-ask").onclick = () => runLlm("ask");
  $("llm-edit").onclick = () => runLlm("edit");
  $("llm-apply").onclick = applyLlmEdit;
  $("cond-cancel").onclick = closeCondModal;
  $("cond-submit").onclick = submitCond;
  $("modal-backdrop").addEventListener("click", (e) => {
    if (e.target.id === "modal-backdrop") closeCondModal();
  });
  $("editor-fallback").addEventListener("input", () => { scheduleRender(); documentChanged(); });
  $("recent-files").onchange = () => { openRecent($("recent-files").value); $("recent-files").value = ""; };
  $("auto-save").onchange = () => localStorage.setItem("mdflow.autosave", $("auto-save").checked ? "1" : "0");
  $("conditions").addEventListener("input", scheduleRender);
  $("preview").addEventListener("scroll", syncEditorFromPreview);
  $("preview").addEventListener("click", selectPreviewDiagram);
  $("preview").addEventListener("contextmenu", showDiagramContext);
  $("diagram-context").querySelectorAll("button").forEach((button) => button.onclick = () => runContextCommand(button.dataset.command));
  $("command-query").oninput = renderCommands;
  $("command-query").onkeydown = (event) => { if (event.key === "Enter") $("command-items").querySelector("button")?.click(); if (event.key === "Escape") closeCommandPalette(); };
  $("command-backdrop").onclick = (event) => { if (event.target === $("command-backdrop")) closeCommandPalette(); };
  document.addEventListener("click", (event) => { if (!event.target.closest("#diagram-context")) $("diagram-context").classList.add("hidden");
    document.querySelectorAll(".toolbar-menu[open]").forEach((menu) => { if (!menu.contains(event.target)) menu.removeAttribute("open"); }); });
  document.addEventListener("keydown", (event) => { if ((event.ctrlKey || event.metaKey) && event.shiftKey && event.key.toLowerCase() === "p") {
    event.preventDefault(); openCommandPalette(); } });
  $("sel-diagram").addEventListener("change", () => { state.selectedId = $("sel-diagram").value; render(); });
  $("sel-preset").addEventListener("change", render);
  initDivider();
}

// ---- 起動 ----
window.addEventListener("DOMContentLoaded", async () => {
  initRenderers();
  wire();
  refreshRecentFiles(); $("auto-save").checked = localStorage.getItem("mdflow.autosave") === "1";
  restoreExplorerFolder();
  api("/api/initial").then(async (initial) => {
    $("app-version").textContent = `v${initial.version || ""}`;
    await initEditor(initial.text || "");
    state.lastSaved = initial.text || "";
    offerRecovery(initial.text || "");
    await render();
  }).catch((e) => toast("初期化に失敗しました: " + e.message));
  setInterval(checkExternalChange, 3000);
});

window.addEventListener("beforeunload", (event) => {
  if (editor && editorText() !== state.lastSaved) { event.preventDefault(); event.returnValue = ""; }
});
