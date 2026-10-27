"""واجهة مداد: محادثة، مراجعة، تطبيق، تشغيل."""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from midad.provider import ProviderError, resolve_provider
from midad.safety import SafetyError
from midad.store import Store
from midad.workshop import (
    export_zip,
    handle_apply,
    handle_cancel,
    handle_chat,
    handle_run,
    handle_save,
    handle_undo,
    import_zip,
    project_view,
)
from midad.runner import preview_file

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "static"
EXAMPLE = ROOT / "examples" / "calculator"


def create_app(data_dir: Path, provider=None, seed: bool = True) -> FastAPI:
    store = Store(data_dir)
    if seed:
        store.seed_example(EXAMPLE)
    app = FastAPI(title="مداد")
    app.state.store = store
    app.state.provider_override = provider

    @app.exception_handler(SafetyError)
    async def safety_error(_request: Request, exc: SafetyError) -> JSONResponse:
        return JSONResponse({"ok": False, "error": exc.message}, status_code=400)

    @app.exception_handler(ProviderError)
    async def provider_error(_request: Request, exc: ProviderError) -> JSONResponse:
        return JSONResponse({"ok": False, "error": exc.message}, status_code=400)

    @app.exception_handler(KeyError)
    async def missing_project(_request: Request, _exc: KeyError) -> JSONResponse:
        return JSONResponse({"ok": False, "error": "المشروع مش موجود."}, status_code=404)

    @app.exception_handler(FileNotFoundError)
    async def missing_file(_request: Request, _exc: FileNotFoundError) -> JSONResponse:
        return JSONResponse({"ok": False, "error": "الملف مش موجود."}, status_code=404)

    @app.exception_handler(ValueError)
    async def bad_request(_request: Request, exc: ValueError) -> JSONResponse:
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=400)

    @app.get("/api/health")
    def health() -> dict:
        return {"ok": True, "name": "midad"}

    @app.get("/api/settings")
    def get_settings() -> dict:
        return _settings_view(store)

    @app.put("/api/settings")
    async def put_settings(request: Request) -> dict:
        body = await request.json()
        current = store.load_settings()
        _save_setting(current, body, "api_key", "clear_key")
        _save_setting(current, body, "openai_api_key", "clear_openai")
        _save_setting(current, body, "anthropic_api_key", "clear_anthropic")
        _save_setting(current, body, "gemini_api_key", "clear_gemini")
        for field in ("base_url", "model", "openai_model", "anthropic_model", "gemini_text_model", "gemini_image_model"):
            if str(body.get(field) or "").strip():
                current[field] = str(body[field]).strip()
        store.save_settings(current)
        return _settings_view(store)

    @app.get("/api/projects")
    def list_projects() -> dict:
        return {"projects": store.list_projects()}

    @app.post("/api/projects")
    async def create_project(request: Request) -> dict:
        body = await request.json()
        return store.create_project(str(body.get("name") or ""))

    @app.post("/api/projects/import")
    async def post_import(name: str = Form(""), file: UploadFile = File(...)) -> dict:
        payload = await file.read()
        return import_zip(store, name, payload)

    @app.get("/api/projects/{project_id}")
    def get_project(project_id: str) -> dict:
        return project_view(store, project_id)

    @app.get("/api/projects/{project_id}/file")
    def get_file(project_id: str, path: str) -> dict:
        return {"path": path, "content": store.read_text(project_id, path)}

    @app.put("/api/projects/{project_id}/file")
    async def put_file(project_id: str, request: Request) -> dict:
        body = await request.json()
        return handle_save(store, project_id, str(body.get("path") or ""), str(body.get("content") or ""))

    @app.post("/api/projects/{project_id}/chat")
    async def chat(project_id: str, request: Request) -> dict:
        body = await request.json()
        mode = str(body.get("mode") or "edit")
        engine = str(body.get("engine") or "demo")
        provider_impl = resolve_provider(store.load_settings(), app.state.provider_override, engine=engine, mode=mode)
        return handle_chat(
            store,
            provider_impl,
            project_id,
            str(body.get("message") or ""),
            body.get("active_file"),
            mode,
        )

    @app.post("/api/projects/{project_id}/apply")
    async def apply_change(project_id: str, request: Request) -> dict:
        body = await request.json()
        return handle_apply(store, project_id, str(body.get("pending_id") or ""))

    @app.post("/api/projects/{project_id}/cancel")
    def cancel(project_id: str) -> dict:
        return handle_cancel(store, project_id)

    @app.post("/api/projects/{project_id}/undo")
    def undo(project_id: str) -> dict:
        return handle_undo(store, project_id)

    @app.post("/api/projects/{project_id}/run")
    async def run(project_id: str, request: Request) -> dict:
        body = {}
        if request.headers.get("content-type", "").startswith("application/json"):
            body = await request.json()
        return handle_run(store, project_id, body.get("path"), timeout=float(body.get("timeout") or 8))

    @app.get("/api/projects/{project_id}/export")
    def export_project(project_id: str) -> Response:
        payload = export_zip(store, project_id)
        return Response(
            content=payload,
            media_type="application/zip",
            headers={"Content-Disposition": f'attachment; filename="{project_id}.zip"'},
        )

    @app.get("/preview/{project_id}/{file_path:path}")
    def preview(project_id: str, file_path: str) -> FileResponse:
        return FileResponse(preview_file(store.project_dir(project_id), file_path))

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(STATIC / "index.html")

    app.mount("/", StaticFiles(directory=STATIC), name="static")
    return app


def _save_setting(current: dict, body: dict, field: str, clear_flag: str) -> None:
    if body.get(clear_flag):
        current.pop(field, None)
    elif str(body.get(field) or "").strip():
        current[field] = str(body[field]).strip()


def _hint(secret: str) -> str:
    if not secret:
        return ""
    if len(secret) >= 4:
        return "••••" + secret[-4:]
    return "••••"


def _settings_view(store: Store) -> dict:
    saved = store.load_settings()
    forced_demo = os.environ.get("MIDAD_PROVIDER") == "demo"
    openai = "" if forced_demo else str(saved.get("openai_api_key") or saved.get("api_key") or os.environ.get("OPENAI_API_KEY") or "")
    claude = "" if forced_demo else str(saved.get("anthropic_api_key") or os.environ.get("ANTHROPIC_API_KEY") or "")
    gemini = "" if forced_demo else str(saved.get("gemini_api_key") or os.environ.get("GEMINI_API_KEY") or "")
    connected = [name for name, key in (("ChatGPT", openai), ("Claude", claude), ("Gemini", gemini)) if key]
    return {
        "provider": "demo" if not connected else "connected",
        "connected": connected,
        "base_url": str(saved.get("base_url") or os.environ.get("OPENAI_BASE_URL") or "https://api.openai.com/v1"),
        "model": str(saved.get("openai_model") or saved.get("model") or os.environ.get("OPENAI_MODEL") or "gpt-4.1"),
        "key_set": bool(openai),
        "key_hint": _hint(openai),
        "key_source": "saved" if openai else "none",
        "engines": {
            "chatgpt": {"key_set": bool(openai), "hint": _hint(openai), "model": str(saved.get("openai_model") or saved.get("model") or "gpt-4.1")},
            "claude": {"key_set": bool(claude), "hint": _hint(claude), "model": str(saved.get("anthropic_model") or "claude-sonnet-5-5")},
            "gemini": {
                "key_set": bool(gemini),
                "hint": _hint(gemini),
                "text_model": str(saved.get("gemini_text_model") or "gemini-3.1-pro-preview"),
                "image_model": str(saved.get("gemini_image_model") or "gemini-3.1-flash-image"),
            },
        },
    }


app = create_app(Path(os.environ.get("MIDAD_DATA", ROOT / "data")))
