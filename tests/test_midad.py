import io
import json
import zipfile
from pathlib import Path

import httpx
from fastapi.testclient import TestClient

from midad.app import create_app
from midad.provider import DemoProvider, OpenAIProvider, Plan, extract_json
from midad.safety import Operation


def _client(tmp_path: Path, provider=None, seed: bool = True) -> TestClient:
    if provider is None:
        provider = DemoProvider()
    return TestClient(create_app(tmp_path, provider=provider, seed=seed))


def _text(client: TestClient, path: str, project: str = "calculator") -> str:
    response = client.get(f"/api/projects/{project}/file", params={"path": path})
    assert response.status_code == 200, response.text
    return response.json()["content"]


def test_pages_load(tmp_path: Path):
    with _client(tmp_path) as client:
        assert client.get("/api/health").json()["ok"] is True
        page = client.get("/")
        assert page.status_code == 200
        assert "مداد" in page.text
        assert client.get("/app.js").status_code == 200
        assert client.get("/app.css").status_code == 200


def test_existing_project_is_edited_only_after_apply_and_can_undo(tmp_path: Path):
    with _client(tmp_path) as client:
        blob = tmp_path / "projects" / "calculator" / "blob.bin"
        blob.write_bytes(b"\x00\x01\xff")
        before = _text(client, "main.py")
        notes = _text(client, "notes.txt")
        preview = client.post("/api/projects/calculator/chat", json={"message": "أضف دالة طرح"}).json()
        assert preview["ok"] is True
        assert preview["pending"]["diffs"]
        assert "def sub" in preview["pending"]["diffs"][0]["unified"]
        assert _text(client, "main.py") == before

        applied = client.post(
            "/api/projects/calculator/apply",
            json={"pending_id": preview["pending"]["id"]},
        ).json()
        assert applied["ok"] is True
        assert applied["changed"] == ["main.py"]
        updated = _text(client, "main.py")
        assert "def sub" in updated
        assert "return a + b" in updated
        assert _text(client, "notes.txt") == notes
        assert blob.read_bytes() == b"\x00\x01\xff"

        ran = client.post("/api/projects/calculator/run", json={"path": "main.py"}).json()
        assert ran["exit_code"] == 0
        assert "جمع: 5" in ran["stdout"]
        assert "طرح: 3" in ran["stdout"]

        assert client.post("/api/projects/calculator/undo").json()["ok"] is True
        assert _text(client, "main.py") == before
        restored = client.post("/api/projects/calculator/run", json={"path": "main.py"}).json()
        assert "جمع: 5" in restored["stdout"]
        assert "طرح:" not in restored["stdout"]


def test_broken_generated_code_does_not_touch_files(tmp_path: Path):
    with _client(tmp_path) as client:
        before = _text(client, "main.py")
        preview = client.post("/api/projects/calculator/chat", json={"message": "حط كود بايظ"}).json()
        assert preview["ok"] is False
        assert "ما اتغيرتش" in preview["reply"] or "زي ما هي" in preview["reply"]
        assert preview["pending"] is None
        assert _text(client, "main.py") == before


def test_delete_requires_explicit_ask_and_undo_restores(tmp_path: Path):
    class Deleter:
        name = "deleter"

        def plan(self, request):
            return Plan(
                reply="همسح الملاحظات",
                operations=[Operation(op="delete", path="notes.txt")],
            )

    with _client(tmp_path, provider=Deleter()) as client:
        blocked = client.post("/api/projects/calculator/chat", json={"message": "رتب الكود"}).json()
        assert blocked["ok"] is False
        assert "لا تمسح" in _text(client, "notes.txt")

    with _client(tmp_path, provider=Deleter()) as client:
        allowed = client.post("/api/projects/calculator/chat", json={"message": "احذف notes.txt"}).json()
        assert allowed["ok"] is True
        client.post("/api/projects/calculator/apply", json={"pending_id": allowed["pending"]["id"]})
        missing = client.get("/api/projects/calculator/file", params={"path": "notes.txt"})
        assert missing.status_code == 404
        client.post("/api/projects/calculator/undo")
        assert "لا تمسح" in _text(client, "notes.txt")


def test_stale_preview_is_rejected(tmp_path: Path):
    with _client(tmp_path) as client:
        preview = client.post("/api/projects/calculator/chat", json={"message": "أضف دالة طرح"}).json()
        saved = client.put(
            "/api/projects/calculator/file",
            json={"path": "main.py", "content": _text(client, "main.py") + "\n# يدوي\n"},
        )
        assert saved.status_code == 200
        rejected = client.post(
            "/api/projects/calculator/apply",
            json={"pending_id": preview["pending"]["id"]},
        )
        assert rejected.status_code == 400
        current = _text(client, "main.py")
        assert current.endswith("# يدوي\n")
        assert "def sub" not in current


def test_ambiguous_replace_and_path_escape_do_not_write(tmp_path: Path):
    class Unsafe:
        name = "unsafe"

        def __init__(self, operations):
            self.operations = operations

        def plan(self, request):
            return Plan(reply="تعديل", operations=self.operations)

    with _client(tmp_path, provider=Unsafe([Operation(op="replace", path="main.py", search=":", replace=";")])) as client:
        result = client.post("/api/projects/calculator/chat", json={"message": "غيّر"}).json()
        assert result["ok"] is False
        assert "def add" in _text(client, "main.py")

    with _client(tmp_path, provider=Unsafe([Operation(op="create", path="../evil.py", content="print(1)\n")])) as client:
        result = client.post("/api/projects/calculator/chat", json={"message": "اكتب"}).json()
        assert result["ok"] is False
        assert not (tmp_path / "evil.py").exists()


def test_long_file_keeps_its_head_when_the_prompt_is_truncated(tmp_path: Path):
    content = "HEAD_MARKER\n" + ("x" * 25000) + "\nTAIL_MARKER"

    class Tail:
        name = "tail"

        def plan(self, request):
            shown = request.files["big.py"]
            assert "TAIL_MARKER" not in shown
            assert "HEAD_MARKER" in shown
            return Plan(
                reply="هعدّل الذيل",
                operations=[Operation(op="replace", path="big.py", search="TAIL_MARKER", replace="NEW_TAIL")],
            )

    with _client(tmp_path, provider=Tail(), seed=False) as client:
        project = client.post("/api/projects", json={"name": "كبير"}).json()
        project_id = project["id"]
        assert client.put(
            f"/api/projects/{project_id}/file",
            json={"path": "big.py", "content": content},
        ).status_code == 200
        preview = client.post(f"/api/projects/{project_id}/chat", json={"message": "عدّل الذيل"}).json()
        assert preview["ok"] is True
        applied = client.post(
            f"/api/projects/{project_id}/apply",
            json={"pending_id": preview["pending"]["id"]},
        ).json()
        assert applied["ok"] is True
        updated = _text(client, "big.py", project_id)
        assert updated.startswith("HEAD_MARKER")
        assert "NEW_TAIL" in updated
        assert "TAIL_MARKER" not in updated
        assert len(updated) > 20000


def test_openai_plan_is_previewed_before_it_is_written(tmp_path: Path):
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/chat/completions")
        assert request.headers["authorization"] == "Bearer secret-key"
        plan = {
            "reply_ar": "هضيف سطر طباعة",
            "operations": [
                {
                    "op": "replace",
                    "path": "main.py",
                    "search": 'print("جمع:", add(2, 3))',
                    "replace": 'print("جمع:", add(2, 3))\n    print("note")',
                }
            ],
        }
        fenced = "```json\n" + json.dumps(plan, ensure_ascii=False) + "\n```"
        return httpx.Response(200, json={"choices": [{"message": {"content": fenced}}]})

    provider = OpenAIProvider(
        "secret-key",
        "https://example.test/v1",
        "gpt-test",
        transport=httpx.MockTransport(handler),
    )
    with _client(tmp_path, provider=provider) as client:
        before = _text(client, "main.py")
        preview = client.post("/api/projects/calculator/chat", json={"message": "ضيف ملاحظة"}).json()
        assert preview["ok"] is True
        assert preview["provider"] == "openai"
        assert _text(client, "main.py") == before
        client.post("/api/projects/calculator/apply", json={"pending_id": preview["pending"]["id"]})
        assert 'print("note")' in _text(client, "main.py")
        assert "def add" in _text(client, "main.py")


def test_import_rejects_zip_slip_and_export_roundtrips(tmp_path: Path):
    with _client(tmp_path) as client:
        slipped = io.BytesIO()
        with zipfile.ZipFile(slipped, "w") as archive:
            archive.writestr("../evil.txt", "nope")
        rejected = client.post(
            "/api/projects/import",
            files={"file": ("bad.zip", slipped.getvalue(), "application/zip")},
            data={"name": "سيء"},
        )
        assert rejected.status_code == 400
        assert not (tmp_path / "evil.txt").exists()

        packed = io.BytesIO()
        with zipfile.ZipFile(packed, "w") as archive:
            archive.writestr("pkg/hello.py", "print('hi')\n")
        imported = client.post(
            "/api/projects/import",
            files={"file": ("good.zip", packed.getvalue(), "application/zip")},
            data={"name": "مستورد"},
        )
        assert imported.status_code == 200
        project_id = imported.json()["id"]
        assert _text(client, "pkg/hello.py", project_id) == "print('hi')\n"
        exported = client.get(f"/api/projects/{project_id}/export")
        assert exported.status_code == 200
        with zipfile.ZipFile(io.BytesIO(exported.content)) as archive:
            assert archive.read("pkg/hello.py") == b"print('hi')\n"


def test_empty_project_can_create_a_page_and_run_stops_when_it_hangs(tmp_path: Path):
    with _client(tmp_path, seed=False) as client:
        project_id = client.post("/api/projects", json={"name": "فاضي"}).json()["id"]
        preview = client.post(f"/api/projects/{project_id}/chat", json={"message": "اعمل صفحة ترحيب"}).json()
        assert preview["ok"] is True
        client.post(f"/api/projects/{project_id}/apply", json={"pending_id": preview["pending"]["id"]})
        assert "أهلاً" in _text(client, "index.html", project_id)
        ran = client.post(f"/api/projects/{project_id}/run", json={"path": "index.html"}).json()
        assert ran["kind"] == "preview"

        script = "import time\nprint('start', flush=True)\ntime.sleep(5)\n"
        client.put(f"/api/projects/{project_id}/file", json={"path": "slow.py", "content": script})
        timed = client.post(f"/api/projects/{project_id}/run", json={"path": "slow.py", "timeout": 1}).json()
        assert timed["exit_code"] == 124
        assert "اتوقف" in timed["stderr"]


def test_settings_do_not_echo_the_key(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("MIDAD_PROVIDER", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with _client(tmp_path, seed=False) as client:
        saved = client.put("/api/settings", json={"api_key": "sk-test-1234", "model": "gpt-4o-mini"})
        assert saved.status_code == 200
        body = saved.json()
        assert body["key_set"] is True
        assert body["key_hint"].endswith("1234")
        assert "sk-test-1234" not in saved.text
        assert "sk-test-1234" not in client.get("/api/settings").text


def test_extract_json_accepts_fenced_objects():
    data = extract_json('```json\n{"reply_ar":"تمام","operations":[]}\n```')
    assert data["reply_ar"] == "تمام"


def _apply(client: TestClient, project: str, preview: dict) -> dict:
    applied = client.post(
        f"/api/projects/{project}/apply",
        json={"pending_id": preview["pending"]["id"]},
    )
    assert applied.status_code == 200, applied.text
    return applied.json()


def test_demo_studio_builds_site_game_image_and_sound_without_touching_existing_files(tmp_path: Path):
    with _client(tmp_path) as client:
        before = _text(client, "main.py")
        notes = _text(client, "notes.txt")
        site = client.post(
            "/api/projects/calculator/chat",
            json={"message": "موقع لاستوديو عمارة", "mode": "site", "engine": "demo"},
        ).json()
        assert site["ok"] is True
        assert "web/index.html" in site["pending"]["summary"]
        _apply(client, "calculator", site)
        page = _text(client, "web/index.html")
        assert "بيت النور" in page
        assert "مسقط فناء" in page
        assert _text(client, "main.py") == before

        game = client.post(
            "/api/projects/calculator/chat",
            json={"message": "لعبة شرارة", "mode": "game"},
        ).json()
        _apply(client, "calculator", game)
        game_js = _text(client, "play/game.js")
        assert "requestAnimationFrame" in game_js
        assert "hold(" in game_js
        assert "بيت النور" in _text(client, "web/index.html")

        image = client.post(
            "/api/projects/calculator/chat",
            json={"message": "فانوس", "mode": "image"},
        ).json()
        _apply(client, "calculator", image)
        assert "فانوس" in _text(client, "assets/lantern.svg")

        sound = client.post(
            "/api/projects/calculator/chat",
            json={"message": "أصوات", "mode": "sound"},
        ).json()
        _apply(client, "calculator", sound)
        assert "صوت الجمع" in _text(client, "sound/index.html")
        assert "Woosh" in sound["reply"] or "غير تجارية" in sound["reply"]

        again = client.post(
            "/api/projects/calculator/chat",
            json={"message": "موقع تاني", "mode": "site"},
        ).json()
        assert again["ok"] is True
        assert again["pending"] is None
        assert _text(client, "main.py") == before
        assert _text(client, "notes.txt") == notes

        preview = client.get("/preview/calculator/web/index.html")
        assert preview.status_code == 200
        assert "بيت النور" in preview.text
        game_page = client.get("/preview/calculator/play/index.html")
        assert game_page.status_code == 200
        assert "شرارة" in game_page.text

        assert client.post("/api/projects/calculator/undo").json()["ok"] is True
        missing = client.get("/api/projects/calculator/file", params={"path": "sound/index.html"})
        assert missing.status_code == 404
        assert "فانوس" in _text(client, "assets/lantern.svg")


def test_image_bytes_are_previewed_then_written_and_undo_removes_them(tmp_path: Path):
    class ImageStub:
        name = "gemini-image"

        def plan(self, request):
            return Plan(
                reply="صورة جاهزة",
                blobs=[{"path": "assets/gemini.png", "data": b"\x89PNG\r\n\x1a\n", "mime": "image/png"}],
            )

    with _client(tmp_path, provider=ImageStub()) as client:
        before = _text(client, "main.py")
        preview = client.post(
            "/api/projects/calculator/chat",
            json={"message": "صورة فانوس", "mode": "image", "engine": "gemini"},
        ).json()
        assert preview["ok"] is True
        assert preview["pending"]["assets"][0]["path"] == "assets/gemini.png"
        assert not (tmp_path / "projects" / "calculator" / "assets" / "gemini.png").exists()
        applied = _apply(client, "calculator", preview)
        assert "assets/gemini.png" in applied["changed"]
        target = tmp_path / "projects" / "calculator" / "assets" / "gemini.png"
        assert target.read_bytes().startswith(b"\x89PNG")
        shown = client.get("/preview/calculator/assets/gemini.png")
        assert shown.status_code == 200
        assert shown.content.startswith(b"\x89PNG")
        blocked = client.post(
            "/api/projects/calculator/chat",
            json={"message": "صورة تانية", "mode": "image"},
        ).json()
        assert blocked["ok"] is False
        assert target.read_bytes().startswith(b"\x89PNG")
        client.post("/api/projects/calculator/undo")
        assert not target.exists()
        assert _text(client, "main.py") == before


def test_claude_and_gemini_return_plans_and_images(tmp_path: Path):
    from midad.engines import ClaudeProvider, GeminiImageProvider, GeminiTextProvider, parse_gemini_image

    def claude_handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["x-api-key"] == "ant-secret"
        assert request.headers["anthropic-version"] == "2023-06-01"
        body = json.loads(request.content)
        assert "Mode website" in body["system"]
        plan = {
            "reply_ar": "هضيف صفحة",
            "operations": [{"op": "create", "path": "web/extra.html", "content": "<p>حي الملقا</p>\n"}],
        }
        return httpx.Response(200, json={"content": [{"type": "text", "text": json.dumps(plan, ensure_ascii=False)}]})

    claude = ClaudeProvider("ant-secret", transport=httpx.MockTransport(claude_handler))
    with _client(tmp_path, provider=claude) as client:
        preview = client.post(
            "/api/projects/calculator/chat",
            json={"message": "موقع", "mode": "site"},
        ).json()
        assert preview["provider"] == "claude"
        _apply(client, "calculator", preview)
        assert "الملقا" in _text(client, "web/extra.html")

    def gemini_handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["x-goog-api-key"] == "gem-secret"
        assert "gemini-3.1-pro-preview" in str(request.url)
        plan = {"reply_ar": "مفيش تعديل", "operations": []}
        return httpx.Response(
            200,
            json={"candidates": [{"content": {"parts": [{"thought": True, "text": "hide"}, {"text": json.dumps(plan)}]}}]},
        )

    gemini = GeminiTextProvider("gem-secret", transport=httpx.MockTransport(gemini_handler))
    with _client(tmp_path, provider=gemini) as client:
        preview = client.post("/api/projects/calculator/chat", json={"message": "راجع", "mode": "edit"}).json()
        assert preview["ok"] is True
        assert preview["pending"] is None
        assert "def add" in _text(client, "main.py")

    png = "iVBORw0KGgo="
    snake = parse_gemini_image({"candidates": [{"content": {"parts": [{"inline_data": {"mime_type": "image/png", "data": png}}]}}]})
    assert snake[1] == "image/png"
    assert snake[0].startswith(b"\x89PNG")

    def image_handler(request: httpx.Request) -> httpx.Response:
        assert "gemini-3.1-flash-image" in str(request.url)
        return httpx.Response(
            200,
            json={"candidates": [{"content": {"parts": [{"inlineData": {"mimeType": "image/png", "data": png}}]}}]},
        )

    image = GeminiImageProvider("gem-secret", transport=httpx.MockTransport(image_handler))
    with _client(tmp_path, provider=image) as client:
        preview = client.post("/api/projects/calculator/chat", json={"message": "ارسم فانوس", "mode": "image"}).json()
        assert preview["pending"]["assets"][0]["mime"] == "image/png"
        _apply(client, "calculator", preview)
        blob = (tmp_path / "projects" / "calculator" / "assets" / "gemini.png").read_bytes()
        assert blob.startswith(b"\x89PNG")


def test_engine_selection_follows_the_saved_key(monkeypatch):
    from midad.engines import ClaudeProvider, GeminiImageProvider, GeminiTextProvider, MissingKeyProvider
    from midad.provider import DemoProvider, OpenAIProvider, resolve_provider

    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    assert isinstance(resolve_provider({}, environ={}, engine="demo", mode="site"), DemoProvider)
    assert isinstance(resolve_provider({}, environ={"MIDAD_PROVIDER": "demo"}, engine="claude"), DemoProvider)
    assert isinstance(resolve_provider({}, environ={}, engine="claude"), MissingKeyProvider)
    claude = resolve_provider({"anthropic_api_key": "ant"}, environ={}, engine="claude", mode="site")
    assert isinstance(claude, ClaudeProvider)
    assert claude.model == "claude-sonnet-5-5"
    image = resolve_provider({"gemini_api_key": "gem"}, environ={}, engine="chatgpt", mode="image")
    assert isinstance(image, GeminiImageProvider)
    assert image.model == "gemini-3.1-flash-image"
    text = resolve_provider({"gemini_api_key": "gem"}, environ={}, engine="gemini", mode="game")
    assert isinstance(text, GeminiTextProvider)
    assert text.model == "gemini-3.1-pro-preview"
    chat = resolve_provider({"api_key": "sk", "model": "gpt-4.1"}, environ={}, engine="chatgpt", mode="edit")
    assert isinstance(chat, OpenAIProvider)
    assert chat.model == "gpt-4.1"


def test_settings_hide_every_engine_key(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("MIDAD_PROVIDER", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    with _client(tmp_path, seed=False) as client:
        saved = client.put(
            "/api/settings",
            json={
                "api_key": "sk-openai-9999",
                "anthropic_api_key": "sk-ant-8888",
                "gemini_api_key": "AIza-7777",
                "base_url": "https://api.openai.com/v1",
                "gemini_image_model": "gemini-3.1-flash-image",
            },
        )
        assert saved.status_code == 200
        body = saved.json()
        assert body["connected"] == ["ChatGPT", "Claude", "Gemini"]
        assert body["engines"]["claude"]["hint"].endswith("8888")
        assert body["engines"]["gemini"]["hint"].endswith("7777")
        assert body["engines"]["gemini"]["text_model"] == "gemini-3.1-pro-preview"
        assert "sk-openai-9999" not in saved.text
        assert "sk-ant-8888" not in saved.text
        assert "AIza-7777" not in saved.text
        cleared = client.put(
            "/api/settings",
            json={"clear_key": True, "clear_openai": True, "clear_anthropic": True, "clear_gemini": True},
        ).json()
        assert cleared["connected"] == []
        assert cleared["key_set"] is False
