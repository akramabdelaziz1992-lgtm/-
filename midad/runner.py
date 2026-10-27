"""تشغيل ملف واحد من غير shell، وبوقت أقصى."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from midad.safety import SafetyError, safe_rel

SCRUB_NAMES = {"OPENAI_API_KEY", "ANTHROPIC_API_KEY", "MIDAD_PROVIDER"}
PREVIEW_SUFFIXES = {".html", ".htm", ".css", ".js", ".mjs", ".svg", ".png", ".jpg", ".jpeg", ".webp", ".txt", ".md"}


def run_file(project_dir: Path, relative: str, timeout: float = 8) -> dict:
    safe = safe_rel(relative)
    target = (project_dir / safe).resolve()
    root = project_dir.resolve()
    if target != root and root not in target.parents:
        raise SafetyError("المسار خارج المشروع.")
    if not target.is_file() or target.is_symlink():
        raise FileNotFoundError(relative)
    suffix = target.suffix.lower()
    if suffix in {".html", ".htm"}:
        return {
            "ok": True,
            "kind": "preview",
            "command": safe,
            "exit_code": 0,
            "stdout": "",
            "stderr": "",
            "preview_url": "/preview/" + project_dir.name + "/" + safe,
        }
    if suffix == ".py":
        command = [sys.executable, safe]
        display = f"python3 {safe}"
    elif suffix in {".js", ".mjs", ".cjs"}:
        command = ["node", safe]
        display = f"node {safe}"
    else:
        raise SafetyError("التشغيل متاح لملفات Python وJavaScript وHTML.")
    env = os.environ.copy()
    for name in list(env):
        if name in SCRUB_NAMES or name.endswith(("_SECRET", "_TOKEN")):
            env.pop(name, None)
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    try:
        completed = subprocess.run(
            command,
            cwd=project_dir,
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )
    except FileNotFoundError as exc:
        raise SafetyError("أداة التشغيل مش موجودة على الجهاز.") from exc
    except subprocess.TimeoutExpired:
        return {
            "ok": False,
            "kind": "process",
            "command": display,
            "exit_code": 124,
            "stdout": "",
            "stderr": "التشغيل اتوقف لأنه عدّى الوقت المسموح.",
            "preview_url": None,
        }
    return {
        "ok": completed.returncode == 0,
        "kind": "process",
        "command": display,
        "exit_code": completed.returncode,
        "stdout": _clip(completed.stdout),
        "stderr": _clip(completed.stderr),
        "preview_url": None,
    }


def preview_file(project_dir: Path, relative: str) -> Path:
    safe = safe_rel(relative)
    if Path(safe).suffix.lower() not in PREVIEW_SUFFIXES:
        raise SafetyError("المعاينة مش متاحة لنوع الملف ده.")
    target = (project_dir / safe).resolve()
    root = project_dir.resolve()
    if not target.is_file() or target.is_symlink() or (target != root and root not in target.parents):
        raise FileNotFoundError(relative)
    return target


def _clip(text: str) -> str:
    if len(text) <= 50_000:
        return text
    return text[:50_000] + "\n... [مقطوع]"
