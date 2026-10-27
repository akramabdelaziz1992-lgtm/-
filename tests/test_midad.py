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
