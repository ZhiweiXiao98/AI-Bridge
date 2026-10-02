import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

TARGET_EXTS = {".py", ".md", ".txt", ".json", ".yaml", ".yml", ".toml", ".ini", ".cfg", ".cs"}
SKIP_DIRS = {
    ".git", "__pycache__", ".venv", "venv", "node_modules",
    "_docker_env", "_knowledge_base", "backup", "dist", "htmlcov",
    "export", "AI_Bridge_Client_Dist", "Chrome_143_Clean_Data", "temp_uploads", "images1"
}

def should_keep(rel: str) -> bool:
    return rel.startswith((
        "app/", "tools/", "tests/", "docs/", "rhino/", "rhino_plugin/",
        "server.py", "start_client.py", "start_server.py", "boot_remote.py",
        "README.md", "AI_README.md",
    ))

def iter_files():
    for cr, dirs, files in os.walk(ROOT):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        base = Path(cr)
        for name in files:
            p = base / name
            if p.suffix.lower() in TARGET_EXTS:
                rel = str(p.relative_to(ROOT)).replace("\\", "/")
                if should_keep(rel):
                    yield p, rel

def main():
    from app.core.services.knowledge_service import knowledge_engine

    keep = []
    keep_set = set()
    for p, rel in iter_files():
        norm = rel.replace(chr(92), '/')
        keep.append((p, norm))
        keep_set.add(norm)

    indexed_paths = set(knowledge_engine.list_indexed_paths())
    stale_paths = sorted(indexed_paths - keep_set)

    # 强制清理历史脏目录（兼容旧库中错误纳入的分发目录）
    banned_prefixes = (
        'AI_Bridge_Client_Dist/',
        'AI_Bridge_Client_Dist' + chr(92),
    )
    forced_paths = sorted(
        p for p in indexed_paths
        if any(p.startswith(prefix) for prefix in banned_prefixes)
    )
    stale_paths = sorted(set(stale_paths) | set(forced_paths))

    print("Start reindex with update_file_index")
    print(f"sync keep={len(keep_set)} indexed={len(indexed_paths)} stale={len(stale_paths)}")

    deleted = 0
    if stale_paths:
        deleted = knowledge_engine.delete_paths(stale_paths)
        print(f"deleted stale paths: {deleted}")

    ok = fail = skip = 0
    for i, (p, rel) in enumerate(keep, 1):
        try:
            txt = p.read_text(encoding="utf-8", errors="replace")
            if not txt.strip():
                skip += 1
                continue
            knowledge_engine.update_file_index(rel, txt)
            ok += 1
        except Exception as e:
            fail += 1
            print(f"warn {rel}: {e}")
        if i % 50 == 0:
            print(f"progress {i} | ok={ok} fail={fail} skip={skip} deleted={deleted}")
    print(f"DONE | ok={ok} fail={fail} skip={skip} deleted={deleted}")

if __name__ == "__main__":
    main()
