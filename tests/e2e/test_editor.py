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
