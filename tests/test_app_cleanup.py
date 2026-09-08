import asyncio
from pathlib import Path

from fastapi import UploadFile

from mdflow import app as app_module


def test_import_cleans_temporary_directory(monkeypatch, tmp_path):
    work = tmp_path / "work"
    monkeypatch.setattr(app_module.tempfile, "mkdtemp", lambda prefix: _mkdir(work))
    monkeypatch.setattr(app_module.pptx_io, "import_ppt", lambda path: object())
    monkeypatch.setattr(app_module.webapi, "import_result_to_dict", lambda result: {"ok": True})
    upload = UploadFile(filename="../unsafe.pptx", file=None)
    upload.read = lambda: _async_bytes(b"pptx")

    assert asyncio.run(app_module.import_ppt(upload)) == {"ok": True}
    assert not work.exists()


async def _async_bytes(value):
    return value


def test_export_attaches_cleanup_task(monkeypatch, tmp_path):
    work = tmp_path / "export"
    monkeypatch.setattr(app_module.tempfile, "mkdtemp", lambda prefix: _mkdir(work))
    monkeypatch.setattr(app_module.webapi, "build_payload", lambda *args: object())
    monkeypatch.setattr(app_module.pptx_io, "export_ppt",
                        lambda payload, image, output, title: Path(output).write_bytes(b"pptx"))

    response = app_module.export_ppt({"png_dataurl": "base64,aA==", "diagram_id": "safe"})
    assert response.background is not None
    asyncio.run(response.background())
    assert not work.exists()


def _mkdir(path):
    path.mkdir()
    return str(path)
