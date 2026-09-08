import re

import pytest
from playwright.sync_api import expect

pytestmark = pytest.mark.e2e


def test_monaco_outline_search_and_save(app_page):
    app_page.evaluate("editor.setValue('# E2E title\\n\\nBody')")
    expect(app_page.locator("#outline-items")).to_contain_text("E2E title")
    app_page.evaluate("editor.focus()")
    app_page.keyboard.press("Control+f")
    expect(app_page.locator(".find-widget")).to_be_visible()
    with app_page.expect_download() as download:
        app_page.keyboard.press("Escape")
        app_page.keyboard.press("Control+s")
    assert download.value.suggested_filename.endswith(".md")


def test_live_preview_keeps_cursor_and_editor_scroll(app_page):
    app_page.evaluate("""
      () => {
        editor.setValue(Array.from({length: 240}, (_, i) => `line ${i + 1}`).join('\\n'));
        editor.setPosition({lineNumber: 180, column: 5});
        editor.revealLineInCenter(180);
      }
    """)
    app_page.wait_for_timeout(500)
    before = app_page.evaluate("editor.getScrollTop()")
    app_page.evaluate("""
      () => editor.executeEdits('e2e', [{range: new monaco.Range(180, 5, 180, 5), text: 'x'}])
    """)
    app_page.wait_for_timeout(800)
    after = app_page.evaluate("editor.getScrollTop()")
    assert app_page.evaluate("editor.getPosition().lineNumber") == 180
    assert abs(after - before) < 20


def test_markdown_without_diagram_does_not_render_empty_id(app_page):
    app_page.evaluate("editor.setValue('# Text only\\n\\nNo diagram yet.')")
    app_page.wait_for_timeout(700)
    expect(app_page.locator("#status-warn")).not_to_contain_text("diagram ''")
    expect(app_page.locator("#preview")).to_contain_text("No diagram yet")


def test_quick_preset_picker_visualizes_route(app_page):
    source = """```mermaid
%% id: quick-flow
flowchart TD
  A --> B
  A --> C
```
```mdflow-mapping
diagram: quick-flow
presets:
  管理者・正常:
    active_nodes: [A, B]
  一般・正常:
    active_nodes: [A, C]
```"""
    app_page.evaluate("value => editor.setValue(value)", source)
    expect(app_page.locator("#preset-buttons")).to_contain_text("管理者・正常")
    app_page.locator("#preset-buttons .preset-chip", has_text="一般・正常").click()
    expect(app_page.locator("#status-preset")).to_have_text("プリセット: 一般・正常")
    expect(app_page.locator("#preset-buttons .preset-chip.active")).to_have_text("一般・正常")
    expect(app_page.locator("#condition-advanced")).not_to_have_attribute("open", "")


def test_dirty_state_and_crash_recovery(app_page):
    app_page.evaluate("editor.setValue('# Unsaved recovery')")
    expect(app_page.locator("#file-name")).to_have_class(re.compile(r"dirty"))
    app_page.wait_for_function("localStorage.getItem('mdflow.recovery') !== null")
    app_page.on("dialog", lambda dialog: dialog.accept())
    app_page.reload()
    app_page.locator(".monaco-editor").wait_for(timeout=20_000)
    expect(app_page.locator("#recovery-banner")).to_be_visible()
    app_page.locator("#btn-recover").click()
    expect(app_page.locator("#preview")).to_contain_text("Unsaved recovery")


def test_diagram_template_insertion(app_page):
    app_page.evaluate("editor.setValue('')")
    app_page.locator("#diagram-template").select_option("sequence")
    app_page.locator("#btn-insert-template").click()
    assert "@startuml sequence-name" in app_page.evaluate("editor.getValue()")


def test_file_explorer_renders_selected_directory(app_page):
    expect(app_page.locator("#file-explorer")).to_be_visible()
    app_page.evaluate("""
      async () => {
        const markdown = {kind: 'file', name: 'flow.md'};
        const nested = {kind: 'directory', name: 'docs', async *values() {
          yield {kind: 'file', name: 'readme.md'};
        }};
        state.directoryHandle = {name: 'project', async queryPermission() { return 'granted'; },
          async *values() { yield nested; yield markdown; }};
        await refreshExplorer();
      }
    """)
    expect(app_page.locator("#explorer-name")).to_have_text("project")
    expect(app_page.locator("#explorer-tree")).to_contain_text("docs")
    expect(app_page.locator("#explorer-tree")).to_contain_text("flow.md")


def test_standalone_plantuml_file_opens_as_source_and_preview(app_page):
    source = "@startuml\nAlice -> Bob: hello\n@enduml"
    app_page.evaluate("""
      async (source) => {
        rememberFile = async () => {};
        const handle = {
          kind: 'file', name: 'diagram.puml',
          async queryPermission() { return 'granted'; },
          async getFile() { return {text: async () => source, lastModified: 1}; },
        };
        await loadFileHandle(handle);
      }
    """, source)
    expect(app_page.locator("#file-name")).to_have_text("diagram.puml")
    assert app_page.evaluate("editor.getValue()") == source
    assert app_page.evaluate("state.documentKind") == "plantuml"
    expect(app_page.locator("#preview .plantuml-box")).to_have_count(1)


def test_generate_all_mermaid_paths(app_page):
    app_page.evaluate(r"""editor.setValue(`\n\`\`\`mermaid
%% id: all-routes
flowchart TD
  A[Start] --> B{Choice}
  B -->|Yes| C[Done]
  B -->|No| D[Denied]
  C --> E[End]
  D --> E
\`\`\``)""")
    app_page.locator("#sel-diagram option[value='all-routes']").wait_for(state="attached", timeout=10_000)
    expect(app_page.locator("#quick-diagram")).to_have_value("all-routes")
    app_page.locator("#quick-diagram").select_option("all-routes")
    app_page.locator("#btn-generate-paths-inline").click()
    app_page.wait_for_function("editor.getValue().includes('自動経路 01')")
    expect(app_page.locator("#path-generation-status")).to_contain_text("2件の経路を作成")
    expect(app_page.locator("#preset-buttons")).to_contain_text("自動経路 02")
    text = app_page.evaluate("editor.getValue()")
    assert "A → B → C → E" in text
    assert "A → B → D → E" in text
    app_page.evaluate("editor.trigger('e2e', 'undo', null)")
    assert "自動経路 01" not in app_page.evaluate("editor.getValue()")


def test_generate_state_diagram_paths_with_japanese_states(app_page):
    source = """```mermaid
%% id: state-flow
stateDiagram-v2
  [*] --> 初期状態
  初期状態 --> 機能有効状態: 有効
  初期状態 --> 出力無効状態: 無効
  機能有効状態 --> 地図出力中
  地図出力中 --> 契約国外状態
  契約国外状態 --> 地図出力中
  地図出力中 --> [*]
    出力無効状態 --> [*]
```"""
    app_page.evaluate("value => editor.setValue(value)", source)
    app_page.locator("#btn-generate-paths-inline").click()
    expect(app_page.locator("#path-generation-status")).to_contain_text("3件の経路を作成")
    expect(app_page.locator("#quick-diagram")).to_have_value("state-flow")
    app_page.locator("#preset-buttons .preset-chip", has_text="自動経路 01").click()
    expect(app_page.locator("#preview .mermaid-box svg")).to_be_visible(timeout=10_000)
    expect(app_page.locator("#status-warn")).not_to_contain_text("構文エラー")


def test_visible_diagram_selector_switches_path_target(app_page):
    source = """```mermaid
%% id: first-flow
flowchart TD
  A --> B
```

```mermaid
%% id: second-flow
flowchart TD
  X --> Y
  X --> Z
```"""
    app_page.evaluate("value => editor.setValue(value)", source)
    app_page.locator("#quick-diagram option[value='second-flow']").wait_for(state="attached", timeout=10_000)
    app_page.locator("details.toolbar-menu").nth(1).locator("summary").click()
    expect(app_page.locator("#sel-diagram")).to_be_visible()
    app_page.locator("#sel-diagram").select_option("second-flow")
    expect(app_page.locator("#quick-diagram")).to_have_value("second-flow")
    app_page.locator("#btn-generate-paths-inline").click()
    expect(app_page.locator("#path-generation-status")).to_contain_text("2件の経路を作成")
    assert "diagram: second-flow" in app_page.evaluate("editor.getValue()")


def test_command_palette(app_page):
    app_page.keyboard.press("Control+Shift+p")
    expect(app_page.locator("#command-palette")).to_be_visible()
    app_page.locator("#command-query").fill("Local LLM")
    expect(app_page.locator("#command-items")).to_contain_text("Local LLMを開く")
    app_page.keyboard.press("Enter")
    expect(app_page.locator("#llm-panel")).to_be_visible()


def test_mermaid_zoom_and_svg_copy(app_page, context):
    context.grant_permissions(["clipboard-read", "clipboard-write"], origin=app_page.url)
    app_page.evaluate("editor.setValue('```mermaid\\nflowchart TD\\n A-->B\\n```')")
    app_page.locator("#preview .mermaid-box svg").wait_for(timeout=15_000)
    app_page.locator("#preview .mermaid-box").click()
    app_page.locator("#btn-zoom-in").click()
    expect(app_page.locator("#zoom-label")).to_have_text("110%")
    app_page.locator("#btn-copy-svg").click()
    expect(app_page.locator("#toast")).to_contain_text("SVGをコピー")
    assert "<svg" in app_page.evaluate("navigator.clipboard.readText()")
    app_page.locator("#export-scale").select_option("1")
    with app_page.expect_download() as download:
        app_page.locator("#btn-export-all").click()
    assert download.value.suggested_filename == "mdflow-diagrams.zip"


def test_llm_diff_and_stop(app_page):
    app_page.route(re.compile(r".*/api/llm/models"), lambda route: route.fulfill(
        status=200, content_type="application/json", body='{"available":true,"models":["e2e-model"]}'))
    app_page.route(re.compile(r".*/api/llm/stream"), lambda route: route.fulfill(
        status=200, content_type="text/plain", body="# Updated\n\nSafe text"))
    app_page.locator("#btn-llm").click()
    app_page.locator("#llm-instruction").fill("Improve it")
    app_page.locator("#llm-edit").click()
    expect(app_page.locator("#llm-diff .monaco-diff-editor")).to_be_visible(timeout=15_000)
    expect(app_page.locator("#llm-validation")).to_contain_text("構文検証済み")

    app_page.evaluate("""
      window.__originalFetch = window.fetch;
      window.fetch = (url, options = {}) => {
        if (!String(url).includes('/api/llm/stream')) return window.__originalFetch(url, options);
        return new Promise((resolve, reject) => {
          options.signal.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError')));
        });
      };
    """)
    app_page.locator("#llm-ask").click()
    expect(app_page.locator("#llm-stop")).to_be_visible()
    app_page.locator("#llm-stop").click()
    expect(app_page.locator("#llm-answer")).to_contain_text("生成を停止しました")


def test_llm_connection_list_comes_from_json_api(app_page):
    app_page.route(re.compile(r".*/api/llm/servers"), lambda route: route.fulfill(
        status=200, content_type="application/json", body='{"servers":['
        '{"name":"Studio A","provider":"openai","base_url":"http://127.0.0.1:1234/v1","model":"a"},'
        '{"name":"Ollama B","provider":"ollama","base_url":"http://127.0.0.1:11434","model":"b"}'
        '],"active":1,"config_path":"config.json"}'))
    app_page.route(re.compile(r".*/api/llm/models"), lambda route: route.fulfill(
        status=200, content_type="application/json", body='{"available":true,"models":["b"],"current":"b"}'))
    app_page.route(re.compile(r".*/api/llm/settings"), lambda route: route.fulfill(
        status=200, content_type="application/json", body='{"ok":true,"active":1}'))
    app_page.locator("#btn-llm").click()
    expect(app_page.locator("#llm-server")).to_have_value("1")
    expect(app_page.locator("#llm-server")).to_contain_text("Studio A")
    expect(app_page.locator("#llm-url")).to_have_value("http://127.0.0.1:11434")
    expect(app_page.locator("#llm-config-path")).to_have_text("config.json")
    assert app_page.evaluate("JSON.parse(localStorage.getItem('mdflow.llm')).url") is None


def test_llm_requires_confirmation_and_saves_history(app_page):
    app_page.route(re.compile(r".*/api/llm/models"), lambda route: route.fulfill(
        status=200, content_type="application/json", body='{"available":true,"models":["e2e-model"]}'))
    app_page.route(re.compile(r".*/api/llm/stream"), lambda route: route.fulfill(
        status=200, content_type="text/plain", body="# Safer document\n\nReviewed"))
    app_page.evaluate("editor.setValue('# Original\\n\\nText')")
    app_page.locator("#btn-llm").click()
    app_page.locator("#llm-scope").select_option("document")
    app_page.locator("#llm-instruction").fill("Review safely")
    app_page.locator("#llm-edit").click()
    expect(app_page.locator("#llm-apply")).to_be_disabled()
    app_page.locator("#llm-confirm").check()
    app_page.locator("#llm-apply").click()
    expect(app_page.locator("#preview")).to_contain_text("Safer document")
    assert app_page.evaluate("JSON.parse(localStorage.getItem('mdflow.llm.history')).length") == 1
