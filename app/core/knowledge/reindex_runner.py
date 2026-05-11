import logging
import os
from pathlib import Path

from app.core.config import ConfigManager
from app.core.services.knowledge_service import knowledge_engine
from app.core.logging import get_logger

logger = get_logger("app.core.knowledge.reindex_runner", side="worker")


def _parse_multiline(value):
    text = str(value or "")
    items = []
    for raw in text.replace(",", "\n").splitlines():
        item = raw.strip()
        if item:
            items.append(item)
    return items


def _normalize_rel(path_str: str) -> str:
    return str(path_str or "").replace(chr(92), "/")


def _should_keep(rel: str, include_prefixes) -> bool:
    if not include_prefixes:
        return True
    return any(rel.startswith(prefix) for prefix in include_prefixes)


def _iter_files(root: Path, target_exts, skip_dirs, include_prefixes):
    for current_root, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in skip_dirs]
        base = Path(current_root)
        for name in files:
            p = base / name
            if p.suffix.lower() not in target_exts:
                continue
            rel = _normalize_rel(p.relative_to(root))
            if _should_keep(rel, include_prefixes):
                yield p, rel


def _load_rules():
    config = ConfigManager.load()
    return {
        "enabled": bool(config.get("knowledge_reindex_enabled", True)),
        "target_exts": {item.lower() for item in _parse_multiline(config.get("knowledge_reindex_target_exts", ""))},
        "skip_dirs": set(_parse_multiline(config.get("knowledge_reindex_skip_dirs", ""))),
        "include_prefixes": [_normalize_rel(item) for item in _parse_multiline(config.get("knowledge_reindex_include_prefixes", ""))],
        "forced_delete_prefixes": [_normalize_rel(item) for item in _parse_multiline(config.get("knowledge_reindex_forced_delete_prefixes", ""))],
        "only_non_empty": bool(config.get("knowledge_reindex_only_non_empty", True)),
        "delete_stale": bool(config.get("knowledge_reindex_delete_stale", True)),
    }


def _is_path_allowed(rel: str, target_exts, skip_dirs, include_prefixes) -> bool:
    rel = _normalize_rel(rel)
    path_obj = Path(rel)
    if target_exts and path_obj.suffix.lower() not in target_exts:
        return False
    parts = path_obj.parts
    if skip_dirs and any(part in skip_dirs for part in parts[:-1]):
        return False
    return _should_keep(rel, include_prefixes)


def reindex_project(root_dir=".", progress_callback=None):
    def emit_progress(stage, **extra):
        if progress_callback:
            payload = {"stage": stage}
            payload.update(extra)
            progress_callback(payload)

    rules = _load_rules()
    root = Path(root_dir).resolve()

    enabled = rules["enabled"]
    if not enabled:
        emit_progress("disabled")
        return {
            "enabled": False,
            "keep": 0,
            "deleted": 0,
            "ok": 0,
            "fail": 0,
            "skip": 0,
        }

    target_exts = rules["target_exts"]
    skip_dirs = rules["skip_dirs"]
    include_prefixes = rules["include_prefixes"]
    forced_delete_prefixes = rules["forced_delete_prefixes"]
    only_non_empty = rules["only_non_empty"]
    delete_stale = rules["delete_stale"]

    emit_progress("prepare", root=str(root))
    emit_progress("scan_start")
    keep = []
    keep_set = set()
    for p, rel in _iter_files(root, target_exts, skip_dirs, include_prefixes):
        keep.append((p, rel))
        keep_set.add(rel)
    emit_progress("scan_done", total=len(keep))

    indexed_paths = set(_normalize_rel(p) for p in knowledge_engine.list_indexed_paths())
    stale_paths = set()
    if delete_stale:
        stale_paths.update(indexed_paths - keep_set)
        stale_paths.update(
            p for p in indexed_paths
            if any(p.startswith(prefix) for prefix in forced_delete_prefixes)
        )

    deleted = 0
    if stale_paths:
        emit_progress("delete_start", total=len(stale_paths))
        deleted = knowledge_engine.delete_paths(sorted(stale_paths))
        emit_progress("delete_done", deleted=deleted)
    else:
        emit_progress("delete_done", deleted=0)

    ok = fail = skip = 0
    total = len(keep)
    emit_progress("index_start", total=total)
    for idx, (p, rel) in enumerate(keep, start=1):
        try:
            txt = p.read_text(encoding="utf-8", errors="replace")
            if only_non_empty and not txt.strip():
                skip += 1
                emit_progress("index_progress", current=idx, total=total, file=rel, ok=ok, fail=fail, skip=skip, status="skip")
                continue
            knowledge_engine.update_file_index(rel, txt)
            ok += 1
            emit_progress("index_progress", current=idx, total=total, file=rel, ok=ok, fail=fail, skip=skip, status="ok")
        except Exception:
            fail += 1
            emit_progress("index_progress", current=idx, total=total, file=rel, ok=ok, fail=fail, skip=skip, status="fail")

    summary = {
        "enabled": True,
        "keep": len(keep_set),
        "deleted": deleted,
        "ok": ok,
        "fail": fail,
        "skip": skip,
    }
    emit_progress("done", **summary)
    return summary


def reindex_changed_files(changed_files, root_dir=".", progress_callback=None):
    def emit_progress(stage, **extra):
        if progress_callback:
            payload = {"stage": stage}
            payload.update(extra)
            progress_callback(payload)

    rules = _load_rules()
    root = Path(root_dir).resolve()

    enabled = rules["enabled"]
    if not enabled:
        emit_progress("disabled")
        return {
            "enabled": False,
            "keep": 0,
            "deleted": 0,
            "ok": 0,
            "fail": 0,
            "skip": 0,
        }

    target_exts = rules["target_exts"]
    skip_dirs = rules["skip_dirs"]
    include_prefixes = rules["include_prefixes"]
    forced_delete_prefixes = rules["forced_delete_prefixes"]
    only_non_empty = rules["only_non_empty"]

    normalized = []
    seen = set()
    for item in changed_files or []:
        rel = _normalize_rel(item).strip()
        if rel and rel not in seen:
            seen.add(rel)
            normalized.append(rel)

    emit_progress("prepare", root=str(root), changed=len(normalized))
    emit_progress("scan_start")
    emit_progress("scan_done", total=len(normalized))

    deleted_paths = []
    to_index = []

    for rel in normalized:
        abs_path = root / rel
        forced_delete = any(rel.startswith(prefix) for prefix in forced_delete_prefixes)
        allowed = _is_path_allowed(rel, target_exts, skip_dirs, include_prefixes)

        if forced_delete or not abs_path.exists() or not allowed:
            deleted_paths.append(rel)
        else:
            to_index.append((abs_path, rel))

    deleted = 0
    if deleted_paths:
        emit_progress("delete_start", total=len(deleted_paths))
        deleted = knowledge_engine.delete_paths(sorted(set(deleted_paths)))
        emit_progress("delete_done", deleted=deleted)
    else:
        emit_progress("delete_done", deleted=0)

    ok = fail = skip = 0
    total = len(to_index)
    emit_progress("index_start", total=total)
    for idx, (p, rel) in enumerate(to_index, start=1):
        try:
            txt = p.read_text(encoding="utf-8", errors="replace")
            if only_non_empty and not txt.strip():
                knowledge_engine.delete_paths([rel])
                skip += 1
                emit_progress("index_progress", current=idx, total=total, file=rel, ok=ok, fail=fail, skip=skip, status="skip")
                continue
            knowledge_engine.update_file_index(rel, txt)
            ok += 1
            emit_progress("index_progress", current=idx, total=total, file=rel, ok=ok, fail=fail, skip=skip, status="ok")
        except Exception:
            fail += 1
            emit_progress("index_progress", current=idx, total=total, file=rel, ok=ok, fail=fail, skip=skip, status="fail")

    summary = {
        "enabled": True,
        "keep": len(normalized),
        "deleted": deleted,
        "ok": ok,
        "fail": fail,
        "skip": skip,
    }
    emit_progress("done", **summary)
    return summary
