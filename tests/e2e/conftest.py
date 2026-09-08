from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
from pathlib import Path
from urllib.request import urlopen

import pytest


@pytest.fixture(scope="session")
def live_server():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    env = os.environ.copy()
    # pytest-playwright's browser fixture can coexist with NiceGUI's own screen
    # test hooks; disable the latter so MdFlow controls its ephemeral port.
    env.pop("NICEGUI_SCREEN_TEST", None)
    env.pop("NICEGUI_SCREEN_TEST_PORT", None)
    env.pop("PYTEST_CURRENT_TEST", None)
    env.update({"MDFLOW_PORT": str(port), "MDFLOW_SHOW_BROWSER": "0"})
    process = subprocess.Popen(
        [sys.executable, "-m", "mdflow"], cwd=Path(__file__).parents[2], env=env,
        stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True,
    )
    url = f"http://127.0.0.1:{port}"
    try:
        for _ in range(60):
            try:
                with urlopen(f"{url}/api/initial", timeout=1):  # noqa: S310 - test server
                    break
            except OSError:
                if process.poll() is not None:
                    pytest.fail("MdFlow test server exited during startup: " + (process.stderr.read() if process.stderr else ""))
                time.sleep(.2)
        else:
            pytest.fail("MdFlow test server did not start")
        yield url
    finally:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()


@pytest.fixture
def app_page(page, live_server):
    page.goto(live_server)
    page.locator(".monaco-editor").wait_for(timeout=20_000)
    return page
