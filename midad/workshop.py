"""تنسيق المحادثة والتطبيق: المعاينة الأول، والكتابة بعد الفحص."""

from __future__ import annotations

import difflib
import uuid

from midad.provider import PlanRequest, ProviderError, visible_files
from midad.runner import run_file
from midad.safety import Operation, SafetyError, changed_paths, digest, precheck, safe_rel, simulate
from midad.store import Store, public_meta


def project_view(store: Store, project_id: str) -> dict:
    meta = store.read_meta(project_id)
    tree, _texts = store.snapshot_files(project_id)
    view = public_meta(meta)
    view["tree"] = tree
    return view


def handle_chat(store: Store, provider, project_id: str, message: str, active_file: str | None) -> dict:
    message = (message or "").strip()
    if not message:
        raise ValueError("اكتب الطلب الأول.")
    if len(message) > 8000:
        raise ValueError("الطلب أطول من اللازم.")
    with store.lock:
        meta = store.read_meta(project_id)
        tree, files = store.snapshot_files(project_id)
        try:
            plan = provider.plan(
                PlanRequest(
                    message=message,
                    tree=tree,
                    files=visible_files(files),
                    history=meta.get("chat", []),
                    active_file=active_file,
                )
            )
            proposed = simulate(files, plan.operations, message, occupied=set(tree))
            error = precheck(files, proposed)
            if error:
                raise SafetyError(error)
        except (SafetyError, ProviderError) as exc:
            reply = exc.message
            meta.setdefault("chat", []).append({"role": "user", "content": message})
            meta["chat"].append({"role": "assistant", "content": reply})
            meta["pending"] = None
            store.write_meta(meta)
            view = project_view(store, project_id)
            view.update({"ok": False, "reply": reply, "provider": getattr(provider, "name", "demo")})
            return view
        paths = changed_paths(files, proposed)
        pending = None
        if paths:
            pending = {
                "id": uuid.uuid4().hex,
                "summary": _summary(paths),
                "diffs": [_diff(path, files.get(path, ""), proposed.get(path, "")) for path in paths],
                "operations": [_op_dict(operation) for operation in plan.operations],
                "digest": digest(files),
                "message": message,
            }
        meta.setdefault("chat", []).append({"role": "user", "content": message})
        meta["chat"].append({"role": "assistant", "content": plan.reply})
        meta["pending"] = pending
        store.write_meta(meta)
        view = project_view(store, project_id)
        view.update({"ok": True, "reply": plan.reply, "provider": getattr(provider, "name", "demo")})
        return view


def handle_apply(store: Store, project_id: str, pending_id: str) -> dict:
    with store.lock:
        meta = store.read_meta(project_id)
        pending = meta.get("pending")
        if not pending or pending.get("id") != pending_id:
            raise SafetyError("المعاينة دي خلصت. اطلب التعديل من جديد، ومفيش حاجة اتكتبت زيادة.")
        tree, files = store.snapshot_files(project_id)
        if digest(files) != pending.get("digest"):
            meta["pending"] = None
            store.write_meta(meta)
            raise SafetyError("المشروع اتغير بعد المعاينة. اطلب التعديل من جديد، والملفات لسه زي ما هي.")
        operations = [Operation(**item) for item in pending.get("operations", [])]
        try:
            proposed = simulate(files, operations, pending.get("message", ""), occupied=set(tree))
            error = precheck(files, proposed)
            if error:
                raise SafetyError(error)
        except (SafetyError, ProviderError):
            meta["pending"] = None
            store.write_meta(meta)
            raise
        paths = changed_paths(files, proposed)
        if not paths:
            meta["pending"] = None
            store.write_meta(meta)
            view = project_view(store, project_id)
            view.update({"ok": True, "changed": [], "rolled_back": False})
            return view
        revision = store.snapshot(project_id)
        try:
            store.materialize(project_id, files, proposed)
        except Exception as exc:
            store.restore(project_id, revision)
            raise SafetyError("حصل خطأ وأنا بكتب، ورجّعت الملفات زي ما كانت.") from exc
        store.push_undo(project_id, revision)
        meta = store.read_meta(project_id)
        meta["pending"] = None
        meta.setdefault("chat", []).append({"role": "assistant", "content": "اتطبق التعديل على: " + "، ".join(paths)})
        store.write_meta(meta)
        view = project_view(store, project_id)
        view.update({"ok": True, "changed": paths, "rolled_back": False})
        return view


def handle_cancel(store: Store, project_id: str) -> dict:
    with store.lock:
        meta = store.read_meta(project_id)
        meta["pending"] = None
        store.write_meta(meta)
        return project_view(store, project_id)


def handle_undo(store: Store, project_id: str) -> dict:
    with store.lock:
        meta = store.read_meta(project_id)
        undo = meta.get("undo") or []
        if not undo:
            raise SafetyError("مفيش تعديل أرجّعه.")
        revision = undo.pop()
        store.restore(project_id, revision)
        meta["undo"] = undo
        meta["pending"] = None
        meta.setdefault("chat", []).append({"role": "assistant", "content": "رجّعت المشروع للي قبل آخر تعديل."})
        store.write_meta(meta)
        view = project_view(store, project_id)
        view.update({"ok": True})
        return view


def handle_save(store: Store, project_id: str, relative: str, content: str) -> dict:
    if len(content) > 100_000:
        raise SafetyError("الملف أكبر من الحد المسموح.")
    with store.lock:
        tree, files = store.snapshot_files(project_id)
        path = safe_rel(relative)
        if path in set(tree) - set(files):
            raise SafetyError("الملف مش نصي.")
        if files.get(path) == content:
            view = project_view(store, project_id)
            view.update({"ok": True, "changed": False})
            return view
        proposed = dict(files)
        proposed[path] = content
        revision = store.snapshot(project_id)
        try:
            store.materialize(project_id, files, proposed)
        except Exception as exc:
            store.restore(project_id, revision)
            raise SafetyError("الحفظ فشل والملف رجع زي ما كان.") from exc
        store.push_undo(project_id, revision)
        meta = store.read_meta(project_id)
        meta["pending"] = None
        store.write_meta(meta)
        view = project_view(store, project_id)
        view.update({"ok": True, "changed": True})
        return view


def handle_run(store: Store, project_id: str, relative: str | None, timeout: float = 8) -> dict:
    directory = store.project_dir(project_id)
    tree, _files = store.snapshot_files(project_id)
    chosen = relative or _default_entry(tree)
    if not chosen:
        raise SafetyError("مفيش ملف أقدر أشغّله.")
    return run_file(directory, chosen, timeout=timeout)


def import_zip(store: Store, name: str, payload: bytes) -> dict:
    import io
    import zipfile

    if len(payload) > 20 * 1024 * 1024:
        raise SafetyError("ملف zip أكبر من ٢٠ ميجا.")
    try:
        archive = zipfile.ZipFile(io.BytesIO(payload))
    except zipfile.BadZipFile as exc:
        raise SafetyError("الملف مش zip صالح.") from exc
    members = [info for info in archive.infolist() if not info.is_dir()]
    if not members or len(members) > 200:
        raise SafetyError("الأرشيف فاضي أو فيه ملفات أكتر من الحد.")
    if sum(info.file_size for info in members) > 20 * 1024 * 1024:
        raise SafetyError("محتوى الأرشيف أكبر من الحد.")
    safe_names = [safe_rel(info.filename) for info in members]
    project = store.create_project(name or "مشروع مستورد")
    directory = store.project_dir(project["id"]).resolve()
    for info, safe in zip(members, safe_names):
        target = (directory / safe).resolve()
        if directory not in target.parents:
            raise SafetyError("الأرشيف فيه مسار خارج المشروع.")
        target.parent.mkdir(parents=True, exist_ok=True)
        with archive.open(info) as source, target.open("wb") as dest:
            dest.write(source.read())
    return project


def export_zip(store: Store, project_id: str) -> bytes:
    import io
    import zipfile

    directory = store.project_dir(project_id)
    tree, _texts = store.snapshot_files(project_id)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for relative in tree:
            archive.write(directory / relative, relative)
    return buffer.getvalue()


def _diff(path: str, old: str, new: str) -> dict:
    lines = difflib.unified_diff(
        old.splitlines(),
        new.splitlines(),
        fromfile=path,
        tofile=path,
        lineterm="",
    )
    return {"path": path, "unified": "\n".join(lines)}


def _summary(paths: list[str]) -> str:
    if len(paths) == 1:
        return f"التعديل على {paths[0]} بس"
    return "التعديل على: " + "، ".join(paths)


def _op_dict(operation) -> dict:
    return {
        "op": operation.op,
        "path": operation.path,
        "content": operation.content,
        "search": operation.search,
        "replace": operation.replace,
    }


def _default_entry(tree: list[str]) -> str | None:
    for candidate in ("main.py", "app.py", "index.js", "main.js", "index.html"):
        if candidate in tree:
            return candidate
    for relative in tree:
        if relative.endswith((".py", ".js", ".html", ".htm")):
            return relative
    return None
