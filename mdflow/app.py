"""NiceGUI application for MdFlow."""
from __future__ import annotations

import base64
import io
import json
import os
import re
import shutil
import tempfile
import zipfile
from pathlib import Path

from fastapi import UploadFile
from fastapi.responses import FileResponse, HTMLResponse, Response, StreamingResponse
from nicegui import app, ui
from starlette.background import BackgroundTask

from . import __version__, edit_safety, llm_context, local_llm, plantuml, pptx_io, webapi

_RES = Path(__file__).parent / "resources"
_SAMPLE = Path(__file__).parents[1] / "samples" / "login.md"

app.add_static_files("/assets", _RES)


@app.get("/api/initial")
def initial() -> dict[str, str]:
    return {"text": _SAMPLE.read_text("utf-8"), "version": __version__}


@app.post("/api/parse")
def parse(payload: dict) -> dict:
    return webapi.parse_doc(payload.get("md", ""))


@app.post("/api/render")
def render(payload: dict) -> dict:
    return webapi.render_diagram(payload.get("md", ""), payload.get("diagram_id", ""),
                                 payload.get("conditions", "{}"), payload.get("preset", ""))


@app.post("/api/plantuml")
def render_plantuml(payload: dict) -> dict:
    try:
        return {"svg": plantuml.render_svg(payload.get("source", ""))}
    except plantuml.PlantUmlError as exc:
        return {"error": str(exc), "line": exc.line}


@app.get("/api/plantuml/diagnostics")
def plantuml_diagnostics() -> dict:
    return plantuml.diagnostics()


@app.get("/api/llm/status")
def llm_status() -> dict:
    cfg = local_llm.config()
    try:
        return {"available": True, "provider": cfg.provider, "url": cfg.url,
                "model": cfg.model, "models": local_llm.models(cfg)}
    except local_llm.LocalLlmError as exc:
        return {"available": False, "provider": cfg.provider, "url": cfg.url,
                "model": cfg.model, "models": [], "error": str(exc)}


@app.post("/api/llm/models")
def llm_models(payload: dict) -> dict:
    try:
        cfg = local_llm.config_from(payload.get("provider", ""), payload.get("url", ""),
                                    payload.get("model", ""))
        return {"available": True, "models": local_llm.models(cfg)}
    except local_llm.LocalLlmError as exc:
        return {"available": False, "models": [], "error": str(exc)}


@app.post("/api/llm/chat")
def llm_chat(payload: dict) -> dict:
    try:
        cfg = local_llm.config_from(payload.get("provider", ""), payload.get("url", ""),
                                    payload.get("model", ""))
        answer = local_llm.chat(payload.get("instruction", ""), payload.get("text", ""),
                                payload.get("mode", "ask"), payload.get("model", ""), cfg)
        return {"answer": answer}
    except local_llm.LocalLlmError as exc:
        return {"error": str(exc)}


@app.post("/api/llm/stream")
def llm_stream(payload: dict) -> StreamingResponse:
    def generate():
        try:
            cfg = local_llm.config_from(payload.get("provider", ""), payload.get("url", ""),
                                        payload.get("model", ""))
            yield from local_llm.stream_chat(
                payload.get("instruction", ""), payload.get("text", ""),
                payload.get("mode", "ask"), payload.get("model", ""), cfg,
                max(10, min(600, int(payload.get("timeout", 120)))),
            )
        except (local_llm.LocalLlmError, ValueError) as exc:
            yield f"\n\x1eMDFLOW_ERROR:{exc}"
    return StreamingResponse(generate(), media_type="text/plain; charset=utf-8")


@app.post("/api/llm/context")
def llm_relevant_context(payload: dict) -> dict:
    found = llm_context.retrieve(payload.get("md", ""), payload.get("query", ""))
    return {"text": "\n\n".join(item.text for item in found),
            "chunks": [{"title": item.title, "line": item.start_line,
                        "score": item.score} for item in found]}


@app.post("/api/llm/repair")
def llm_repair(payload: dict) -> dict:
    text, warnings = edit_safety.repair(payload.get("original", ""),
                                        payload.get("candidate", ""),
                                        payload.get("policy", "all"))
    return {"text": text, "warnings": warnings}


@app.post("/api/preset")
def add_preset(payload: dict) -> dict:
    return webapi.add_preset(payload.get("md", ""), payload.get("diagram_id", ""),
                             payload.get("name", ""), payload.get("when", ""),
                             payload.get("nodes", []))


@app.post("/api/preset/all-paths")
def generate_all_paths(payload: dict) -> dict:
    return webapi.generate_all_paths(payload.get("md", ""), payload.get("diagram_id", ""),
                                     int(payload.get("limit", 100)))


@app.post("/api/export")
def export_ppt(payload: dict) -> FileResponse:
    result = webapi.build_payload(payload.get("md", ""), payload.get("diagram_id", ""),
                                  payload.get("conditions", "{}"), payload.get("preset", ""))
    diagram_id = payload.get("diagram_id") or "diagram"
    work = Path(tempfile.mkdtemp(prefix="mdflow_"))
    png = work / "diagram.png"
    png.write_bytes(base64.b64decode(payload.get("png_dataurl", "").split(",", 1)[-1]))
    output = work / f"{diagram_id}.pptx"
    try:
        pptx_io.export_ppt(result, png, output, title=diagram_id)
    except Exception:
        shutil.rmtree(work, ignore_errors=True)
        raise
    return FileResponse(output, filename=output.name,
                        media_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
                        background=BackgroundTask(shutil.rmtree, work, ignore_errors=True))


def _safe_export_name(value: str, fallback: str = "diagram") -> str:
    cleaned = re.sub(r"[^\w.\-]+", "-", value, flags=re.UNICODE).strip(".-")
    return cleaned[:80] or fallback


@app.post("/api/export/bundle")
def export_bundle(payload: dict) -> Response:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        used: set[str] = set()
        for index, item in enumerate(payload.get("diagrams", []), 1):
            base = _safe_export_name(item.get("name", ""), f"diagram-{index}")
            while base in used:
                base += f"-{index}"
            used.add(base)
            if item.get("svg"):
                archive.writestr(f"{base}.svg", item["svg"].encode("utf-8"))
            if item.get("png_dataurl"):
                archive.writestr(f"{base}.png", base64.b64decode(item["png_dataurl"].split(",", 1)[-1]))
        archive.writestr("document.md", payload.get("md", "").encode("utf-8"))
        archive.writestr("manifest.json", json.dumps({"diagrams": list(used)}, ensure_ascii=False).encode("utf-8"))
    return Response(output.getvalue(), media_type="application/zip",
                    headers={"Content-Disposition": 'attachment; filename="mdflow-diagrams.zip"'})


@app.post("/api/export/ppt-multi")
def export_ppt_multi(payload: dict) -> FileResponse:
    work = Path(tempfile.mkdtemp(prefix="mdflow_multi_"))
    try:
        images = []
        for index, item in enumerate(payload.get("diagrams", []), 1):
            path = work / f"diagram-{index}.png"
            path.write_bytes(base64.b64decode(item.get("png_dataurl", "").split(",", 1)[-1]))
            images.append((_safe_export_name(item.get("name", ""), f"diagram-{index}"), path))
        output = work / "mdflow-diagrams.pptx"
        pptx_io.export_images_ppt(images, output)
    except Exception:
        shutil.rmtree(work, ignore_errors=True)
        raise
    return FileResponse(output, filename=output.name,
                        media_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
                        background=BackgroundTask(shutil.rmtree, work, ignore_errors=True))


@app.post("/api/import")
async def import_ppt(file: UploadFile) -> dict:
    work = Path(tempfile.mkdtemp(prefix="mdflow_"))
    try:
        source = work / Path(file.filename or "import.pptx").name
        source.write_bytes(await file.read())
        return webapi.import_result_to_dict(pptx_io.import_ppt(source))
    finally:
        shutil.rmtree(work, ignore_errors=True)


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    """Serve the standalone editor without a framework overlay."""
    return (_RES / "ui.html").read_text("utf-8")


def main() -> int:
    show_browser = os.environ.get("MDFLOW_SHOW_BROWSER", "1") != "0"
    port = int(os.environ.get("MDFLOW_PORT", "8080"))
    ui.run(title="MdFlow", host="127.0.0.1", port=port, reload=False, show=show_browser)
    return 0


if __name__ in {"__main__", "__mp_main__"}:
    main()
