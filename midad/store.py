"""تخزين المشاريع واللقطات. اللقطة بتتحفظ قبل الكتابة عشان التراجع."""

from __future__ import annotations

import json
import os
import re
import shutil
import threading
import time
import uuid
from pathlib import Path

from midad.safety import SafetyError, safe_rel

SKIP_DIRS = {".git", "__pycache__", "node_modules", ".venv"}
TEXT_LIMIT = 200_000


class Store:
    def __init__(self, root: Path):
        self.root = root
        self.projects = root / "projects"
        self.meta_dir = root / "meta"
        self.history = root / "history"
        self.settings_path = root / "settings.json"
        self.lock = threading.RLock()
        self.projects.mkdir(parents=True, exist_ok=True)
        self.meta_dir.mkdir(parents=True, exist_ok=True)
        self.history.mkdir(parents=True, exist_ok=True)

    def seed_example(self, example: Path, project_id: str = "calculator", name: str = "آلة حاسبة") -> None:
        with self.lock:
            if any(self.meta_dir.glob("*.json")) or any(self.projects.iterdir()):
                return
            destination = self.projects / project_id
            shutil.copytree(example, destination)
            self._write_meta(
                {
                    "id": project_id,
                    "name": name,
                    "created_at": _now(),
                    "chat": [],
                    "undo": [],
                    "pending": None,
                }
            )

    def list_projects(self) -> list[dict]:
        with self.lock:
            projects = []
            for path in sorted(self.meta_dir.glob("*.json")):
                meta = json.loads(path.read_text(encoding="utf-8"))
                projects.append({"id": meta["id"], "name": meta["name"]})
            return projects

    def create_project(self, name: str) -> dict:
        with self.lock:
            project_id = uuid.uuid4().hex[:8]
            (self.projects / project_id).mkdir(parents=True)
            meta = {
                "id": project_id,
                "name": (name or "مشروع").strip()[:80] or "مشروع",
                "created_at": _now(),
                "chat": [],
                "undo": [],
                "pending": None,
            }
            self._write_meta(meta)
            return public_meta(meta)

    def read_meta(self, project_id: str) -> dict:
        path = self._meta_path(project_id)
        if not path.is_file():
            raise KeyError(project_id)
        return json.loads(path.read_text(encoding="utf-8"))

    def write_meta(self, meta: dict) -> None:
        with self.lock:
            self._write_meta(meta)

    def project_dir(self, project_id: str) -> Path:
        self.read_meta(project_id)
        directory = (self.projects / project_id).resolve()
        root = self.projects.resolve()
        if directory.parent != root:
            raise SafetyError("مشروع غير معروف.")
        return directory

    def snapshot_files(self, project_id: str) -> tuple[list[str], dict[str, str]]:
        directory = self.project_dir(project_id)
        tree: list[str] = []
        texts: dict[str, str] = {}
        for path in sorted(directory.rglob("*")):
            if not path.is_file() or _skipped(path, directory):
                continue
            relative = path.relative_to(directory).as_posix()
            tree.append(relative)
            if path.stat().st_size > TEXT_LIMIT or path.is_symlink():
                continue
            try:
                texts[relative] = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
        return tree, texts

    def resolve(self, project_id: str, relative: str) -> Path:
        directory = self.project_dir(project_id)
        safe = safe_rel(relative)
        target = (directory / safe).resolve()
        if target != directory and directory not in target.parents:
            raise SafetyError("المسار خارج المشروع.")
        return target

    def read_text(self, project_id: str, relative: str) -> str:
        target = self.resolve(project_id, relative)
        if not target.is_file() or target.is_symlink():
            raise FileNotFoundError(relative)
        try:
            return target.read_text(encoding="utf-8")
        except UnicodeDecodeError as exc:
            raise SafetyError("الملف مش نصي.") from exc

    def snapshot(self, project_id: str) -> str:
        revision = f"{int(time.time() * 1000)}-{uuid.uuid4().hex[:8]}"
        destination = self.history / project_id / revision
        shutil.copytree(self.project_dir(project_id), destination, symlinks=False)
        return revision

    def restore(self, project_id: str, revision: str) -> None:
        source = self.history / project_id / revision
        if not source.is_dir():
            raise SafetyError("لقطة التراجع مش موجودة.")
        destination = self.project_dir(project_id)
        for child in destination.iterdir():
            if child.is_symlink() or child.is_file():
                child.unlink()
            else:
                shutil.rmtree(child)
        for child in source.iterdir():
            target = destination / child.name
            if child.is_dir():
                shutil.copytree(child, target)
            else:
                shutil.copy2(child, target)

    def push_undo(self, project_id: str, revision: str) -> None:
        meta = self.read_meta(project_id)
        undo = meta.get("undo", [])
        undo.append(revision)
        while len(undo) > 10:
            old = undo.pop(0)
            shutil.rmtree(self.history / project_id / old, ignore_errors=True)
        meta["undo"] = undo
        self._write_meta(meta)

    def materialize(self, project_id: str, old: dict[str, str], new: dict[str, str]) -> None:
        for path in sorted(set(old) - set(new)):
            target = self.resolve(project_id, path)
            if target.is_file() and not target.is_symlink():
                target.unlink()
        for path in sorted(set(old) | set(new)):
            if old.get(path) == new.get(path) or path not in new:
                continue
            target = self.resolve(project_id, path)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(new[path], encoding="utf-8")

    def save_settings(self, settings: dict) -> None:
        with self.lock:
            self.settings_path.write_text(json.dumps(settings, ensure_ascii=False, indent=2), encoding="utf-8")
            os.chmod(self.settings_path, 0o600)

    def load_settings(self) -> dict:
        with self.lock:
            if not self.settings_path.is_file():
                return {}
            return json.loads(self.settings_path.read_text(encoding="utf-8"))

    def _meta_path(self, project_id: str) -> Path:
        if not re_fullmatch_id(project_id):
            raise KeyError(project_id)
        return self.meta_dir / f"{project_id}.json"

    def _write_meta(self, meta: dict) -> None:
        path = self._meta_path(meta["id"])
        path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")


def public_meta(meta: dict) -> dict:
    pending = meta.get("pending")
    public_pending = None
    if pending:
        public_pending = {
            "id": pending["id"],
            "summary": pending.get("summary", ""),
            "diffs": pending.get("diffs", []),
        }
    return {
        "id": meta["id"],
        "name": meta["name"],
        "chat": meta.get("chat", []),
        "can_undo": bool(meta.get("undo")),
        "pending": public_pending,
    }


def re_fullmatch_id(project_id: str) -> bool:
    return bool(re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,31}", project_id or ""))


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _skipped(path: Path, root: Path) -> bool:
    relative_parts = path.relative_to(root).parts
    return any(part in SKIP_DIRS for part in relative_parts)
