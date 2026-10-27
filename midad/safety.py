"""قواعد التعديل: مسار جوه المشروع، موضع واحد، وفحص قبل الكتابة."""

from __future__ import annotations

import ast
import hashlib
import json
import re
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

DELETE_INTENT = re.compile(r"(حذف|احذف|امسح|إمسح|شيل|delete|remove)", re.IGNORECASE)
MAX_OPS = 20
MAX_FILE_CHARS = 100_000


class SafetyError(Exception):
    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


@dataclass
class Operation:
    op: str
    path: str
    content: str = ""
    search: str = ""
    replace: str = ""


def safe_rel(path: str) -> str:
    if not isinstance(path, str) or not path.strip():
        raise SafetyError("مسار الملف فاضي.")
    raw = path.replace("\\", "/").strip()
    if raw.startswith("/") or re.match(r"^[A-Za-z]:", raw):
        raise SafetyError("المسار لازم يكون جوه المشروع.")
    parts = [part for part in raw.split("/") if part not in ("", ".")]
    if not parts or any(part == ".." for part in parts):
        raise SafetyError("المسار خارج المشروع.")
    if any("\x00" in part or len(part) > 180 for part in parts):
        raise SafetyError("اسم الملف غير مسموح.")
    if len(parts) > 12:
        raise SafetyError("المسار أعمق من اللازم.")
    return "/".join(parts)


def digest(files: dict[str, str]) -> str:
    hasher = hashlib.sha256()
    for path in sorted(files):
        hasher.update(path.encode("utf-8"))
        hasher.update(b"\0")
        hasher.update(files[path].encode("utf-8"))
        hasher.update(b"\0")
    return hasher.hexdigest()


def simulate(
    files: dict[str, str],
    operations: list[Operation],
    message: str,
    occupied: set[str] | None = None,
) -> dict[str, str]:
    if len(operations) > MAX_OPS:
        raise SafetyError("عدد التعديلات في الخطوة دي أكبر من الحد، فملفاتك ما اتغيرتش.")
    occupied_paths = set(files if occupied is None else occupied)
    result = dict(files)
    for operation in operations:
        path = safe_rel(operation.path)
        if operation.op == "create":
            if path in occupied_paths or path in result:
                raise SafetyError(f"الملف {path} موجود. التعديل على الموجود بيكون بقطعة صغيرة، مش بإعادة كتابة الملف.")
            if len(operation.content) > MAX_FILE_CHARS:
                raise SafetyError("الملف الناتج أكبر من الحد المسموح.")
            result[path] = operation.content
            occupied_paths.add(path)
        elif operation.op == "replace":
            if path not in result:
                if path in occupied_paths:
                    raise SafetyError(f"{path} مش ملف نصي، فمش هعدّله آليًا.")
                raise SafetyError(f"الملف {path} مش موجود. مفيش حاجة اتكتبت.")
            if not operation.search:
                raise SafetyError("التعديل فاضي ومش آمن، فسيبت الملف زي ما هو.")
            count = result[path].count(operation.search)
            if count == 0:
                raise SafetyError(f"مش لاقي النص المطلوب في {path}، فسيبت الملف زي ما هو.")
            if count > 1:
                raise SafetyError(f"النص المطلوب متكرر في {path}، فرفضت التعديل عشان ما يغيّرش أكتر من موضع.")
            updated = result[path].replace(operation.search, operation.replace, 1)
            if len(updated) > MAX_FILE_CHARS:
                raise SafetyError("الملف الناتج أكبر من الحد المسموح.")
            result[path] = updated
        elif operation.op == "delete":
            if not DELETE_INTENT.search(message or ""):
                raise SafetyError("رفضت الحذف لأن الطلب ما قالش صراحة إن الملف يتمسح.")
            if path not in result and path not in occupied_paths:
                raise SafetyError(f"الملف {path} مش موجود.")
            result.pop(path, None)
            occupied_paths.discard(path)
        else:
            raise SafetyError("نوع التعديل مش مفهوم، فملفاتك ما اتغيرتش.")
    return result


def changed_paths(old: dict[str, str], new: dict[str, str]) -> list[str]:
    names = set(old) | set(new)
    return sorted(path for path in names if old.get(path) != new.get(path))


def syntax_error(path: str, content: str | None) -> str | None:
    if content is None:
        return None
    suffix = Path(path).suffix.lower()
    if suffix == ".py":
        try:
            ast.parse(content)
        except SyntaxError as exc:
            return f"Python في {path}: سطر {exc.lineno}: {exc.msg}"
        return None
    if suffix == ".json":
        try:
            json.loads(content)
        except json.JSONDecodeError as exc:
            return f"JSON في {path}: {exc.msg}"
        return None
    if suffix in {".js", ".mjs", ".cjs"}:
        return _node_check(path, content)
    return None


def _node_check(path: str, content: str) -> str | None:
    try:
        with tempfile.NamedTemporaryFile("w", suffix=Path(path).suffix, encoding="utf-8", delete=False) as handle:
            handle.write(content)
            temp_name = handle.name
        completed = subprocess.run(
            ["node", "--check", temp_name],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=15,
            check=False,
        )
    except FileNotFoundError:
        return "فحص JavaScript محتاج Node، فمش هكتب الملف من غير فحص."
    except subprocess.TimeoutExpired:
        return f"فحص {path} اتأخر، فسيبت الملفات زي ما هي."
    finally:
        try:
            Path(temp_name).unlink(missing_ok=True)
        except UnboundLocalError:
            pass
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "خطأ صياغة").strip()
        return f"JavaScript في {path}: {detail.splitlines()[-1][:400]}"
    return None


def precheck(old: dict[str, str], new: dict[str, str]) -> str | None:
    messages = []
    for path in changed_paths(old, new):
        error = syntax_error(path, new.get(path))
        if error:
            messages.append(error)
    if not messages:
        return None
    return "الكود الناتج فيه خطأ، فسيبت الملفات زي ما هي.\n" + "\n".join(messages)
