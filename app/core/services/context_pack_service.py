# filename: app/core/services/context_pack_service.py
import os
import glob
from dataclasses import dataclass
from typing import Dict, List, Optional, Set, Tuple
from app.core.project_context import ProjectContext


@dataclass(frozen=True)
class PackDef:
    key: str
    title: str
    description: str
    includes: List[str]
    excludes: List[str]


class ContextPackService:
    """
    Build a single large text payload that can be sent to an AI web input (text-only).

    Goals:
    - Text-only (no attachments).
    - Deterministic ordering (stable diffs).
    - Reduce "AI guessing" by embedding relevant module source directly.
    - Keep sensitive/runtime files out of the pack (config/db/keys/layout/state).
    """

    _ALLOWED_EXTS: Set[str] = {
        ".py", ".pyw", ".md", ".txt", ".ini", ".qss", ".json", ".yaml", ".yml",
        ".cs", ".csproj", ".xml", ".sln",
    }

    _IGNORE_FILES: Set[str] = {
        ".secret.key",
        "config.json",
        "server_config.json",
        "session_states.json",
        "layout.ini",
        "layout copy.ini",
        "user_data.db",
        "crash_log.txt",
        "FULL_PROJECT_CONTEXT.txt",
        "docs/PROJECT_STRUCTURE_DUMP.md",
        "ignored_blocks.json",
        ".coverage",
        "coverage.json",
    }

    _IGNORE_DIRS: Set[str] = {
        ".git", ".idea", ".vscode",
        "__pycache__", "venv", ".venv",
        "build", "dist", "egg-info",
        "update_cache", "backup", "temp_uploads",
        "export",
        "Chrome_143_Clean_Data", "chrome_user_data",
        "htmlcov", ".pytest_cache",
        "bin", "obj",
        "AI_Bridge_Client_Dist",
    }

    def __init__(self, project_root: Optional[str] = None):
        self.project_root = os.path.abspath(project_root or ProjectContext.get().get_project_root())

    def get_pack_defs(self) -> Dict[str, PackDef]:
        # Keep packs focused; you can expand later with manual/auto selection.
        return {
            "ui_chat": PackDef(
                key="ui_chat",
                title="UI (Chat)",
                description="Chat page module and core UI widgets/components.",
                includes=[
                    "app/ui/pages/chat/**",
                    "app/ui/components/**",
                    "app/ui/widgets.py",
                    "app/ui/main_window.py",
                    "app/ui/theme.py",
                ],
                excludes=[
                    # Avoid self-referential tool UI noise in UI packs.
                    "app/ui/settings_page.py",
                ],
            ),
            "worker_state": PackDef(
                key="worker_state",
                title="Worker + State",
                description="WorkerThread, Strategy E engine, scheduler/state/file safety.",
                includes=[
                    "app/core/worker.py",
                    "app/core/engine/**",
                    "app/core/services/state_service.py",
                    "app/core/services/scheduler_service.py",
                    "app/core/services/file_service.py",
                    "app/core/agent_manager.py",
                ],
                excludes=[],
            ),
            "update_ota": PackDef(
                key="update_ota",
                title="Update + OTA",
                description="Update pipeline and remote worker OTA logic.",
                includes=[
                    "app/core/remote_worker.py",
                    "app/core/self_update.py",
                    "app/core/services/update_service.py",
                    "start_client.py",
                    "start_server.py",
                ],
                excludes=[],
            ),
            "driver_web": PackDef(
                key="driver_web",
                title="Driver (Web)",
                description="Selenium connection/interaction/parser micro-kernel.",
                includes=[
                    "app/core/driver/**",
                ],
                excludes=[],
            ),
            "server_auth": PackDef(
                key="server_auth",
                title="Server + Auth",
                description="FastAPI server and auth/connection manager.",
                includes=[
                    "server.py",
                    "app/core/auth_service.py",
                    "app/core/connection_manager.py",
                ],
                excludes=[],
            ),
            "tests": PackDef(
                key="tests",
                title="Tests",
                description="Pytest configuration and tests.",
                includes=[
                    "pytest.ini",
                    "tests/**",
                ],
                excludes=[],
            ),
            "devtools": PackDef(
                key="devtools",
                title="DevTools (Settings/Console)",
                description="Developer tooling pages (settings/console) and helpers.",
                includes=[
                    "app/ui/settings_page.py",
                    "app/ui/pages/console_page.py",
                    "app/ui/components/preview_dialog.py",
                    "app/ui/components/theme_editor.py",
                ],
                excludes=[],
            ),
        }

    def list_packs(self) -> List[Tuple[str, str]]:
        packs = self.get_pack_defs()
        items = [(k, f"{p.title}") for k, p in packs.items()]
        items.sort(key=lambda x: x[0])
        return items

    def build_pack_text(
        self,
        pack_key: str,
        goal_text: str = "",
        include_ai_readme: bool = True,
        include_project_structure: bool = True,
    ) -> str:
        packs = self.get_pack_defs()
        if pack_key not in packs:
            raise ValueError(f"Unknown pack_key: {pack_key}")

        pack = packs[pack_key]
        files = self._collect_files(pack.includes, pack.excludes)

        header = self._build_header(pack, goal_text=goal_text)

        parts: List[str] = [header]

        # Optional but useful: put "constitution" / structure docs in front.
        if include_ai_readme:
            readme_path = os.path.join(self.project_root, "AI_README.md")
            if self._is_allowed_file(readme_path):
                parts.append(self._format_file_block("AI_README.md", self._read_text(readme_path)))

        if include_project_structure:
            ps_path = os.path.join(self.project_root, "docs", "PROJECT_STRUCTURE.md")
            if self._is_allowed_file(ps_path):
                parts.append(self._format_file_block("docs/PROJECT_STRUCTURE.md", self._read_text(ps_path)))

        for rel_path in files:
            abs_path = os.path.join(self.project_root, rel_path)
            parts.append(self._format_file_block(rel_path, self._read_text(abs_path)))

        return "\n\n".join(parts).rstrip() + "\n"

    def _build_header(self, pack: PackDef, goal_text: str = "") -> str:
        goal_text = (goal_text or "").strip()
        goal_line = f"Goal: {goal_text}" if goal_text else "Goal: (not provided)"

        # Repetition helps compliance.
        rules = [
            "Rules (must follow):",
            "1) Do NOT guess any file content. If something is missing, request it using: [TOOL: read_file path=\"...\"]",
            "2) Do NOT output code snippets. Always output FULL file content for any file you modify.",
            "3) Every code block you output MUST start with a filename injection line, e.g.:",
            "   - Python: # filename: path/to/file.py",
            "   - C#/Java: // filename: path/to/file.cs",
            "4) Preserve existing comments and unchanged code. Only change what is required.",
        ]

        meta = [
            "AI_BRIDGE_CONTEXT_PACK",
            f"Pack: {pack.key} | {pack.title}",
            f"Description: {pack.description}",
            goal_line,
            "",
            "\n".join(rules),
            "",
            "File blocks are delimited as:",
            "<<<AI_BRIDGE_FILE_START path=...>>>",
            "(full raw file content)",
            "<<<AI_BRIDGE_FILE_END path=...>>>",
        ]
        return "\n".join(meta).strip()

    def _format_file_block(self, rel_path: str, content: str) -> str:
        content = (content or "").replace("\r\n", "\n")
        rel_path = rel_path.replace("\\", "/")
        return (
            f"<<<AI_BRIDGE_FILE_START path={rel_path}>>>\n"
            f"{content}\n"
            f"<<<AI_BRIDGE_FILE_END path={rel_path}>>>"
        )

    def _collect_files(self, includes: List[str], excludes: List[str]) -> List[str]:
        excluded = set(self._expand_patterns(excludes))

        found: Set[str] = set()
        for spec in includes:
            for rel in self._expand_patterns([spec]):
                if rel in excluded:
                    continue
                abs_path = os.path.join(self.project_root, rel)
                if self._is_allowed_file(abs_path):
                    found.add(rel)

        return sorted(found)

    def _expand_patterns(self, patterns: List[str]) -> List[str]:
        results: Set[str] = set()
        for spec in patterns:
            spec = (spec or "").strip()
            if not spec:
                continue

            spec_norm = spec.replace("\\", "/")

            if spec_norm.endswith("/**"):
                base_dir = spec_norm[:-3]
                abs_dir = os.path.join(self.project_root, base_dir)
                if os.path.isdir(abs_dir):
                    for root, dirs, files in os.walk(abs_dir):
                        dirs[:] = [d for d in dirs if d not in self._IGNORE_DIRS]
                        for fn in files:
                            abs_path = os.path.join(root, fn)
                            rel = os.path.relpath(abs_path, self.project_root).replace("\\", "/")
                            results.add(rel)
                continue

            if any(ch in spec_norm for ch in ["*", "?", "["]):
                abs_glob = os.path.join(self.project_root, spec_norm)
                for abs_path in glob.glob(abs_glob, recursive=True):
                    if os.path.isdir(abs_path):
                        continue
                    rel = os.path.relpath(abs_path, self.project_root).replace("\\", "/")
                    results.add(rel)
                continue

            abs_path = os.path.join(self.project_root, spec_norm)
            if os.path.isdir(abs_path):
                for root, dirs, files in os.walk(abs_path):
                    dirs[:] = [d for d in dirs if d not in self._IGNORE_DIRS]
                    for fn in files:
                        p = os.path.join(root, fn)
                        rel = os.path.relpath(p, self.project_root).replace("\\", "/")
                        results.add(rel)
            elif os.path.isfile(abs_path):
                rel = os.path.relpath(abs_path, self.project_root).replace("\\", "/")
                results.add(rel)

        filtered: List[str] = []
        for rel in results:
            if self._is_ignored_rel(rel):
                continue
            filtered.append(rel.replace("\\", "/"))
        return sorted(set(filtered))

    def _is_ignored_rel(self, rel_path: str) -> bool:
        rel_path = rel_path.replace("\\", "/").lstrip("/")
        base = os.path.basename(rel_path)
        if base in self._IGNORE_FILES:
            return True

        parts = rel_path.split("/")
        for p in parts:
            if p in self._IGNORE_DIRS:
                return True

        _, ext = os.path.splitext(base)
        if ext and ext.lower() not in self._ALLOWED_EXTS:
            return True

        return False

    def _is_allowed_file(self, abs_path: str) -> bool:
        try:
            if not os.path.isfile(abs_path):
                return False

            rel = os.path.relpath(abs_path, self.project_root).replace("\\", "/")
            if self._is_ignored_rel(rel):
                return False

            _, ext = os.path.splitext(abs_path)
            if ext and ext.lower() not in self._ALLOWED_EXTS:
                return False

            return True
        except Exception:
            return False

    def _read_text(self, abs_path: str) -> str:
        try:
            with open(abs_path, "r", encoding="utf-8", errors="ignore") as f:
                return f.read().rstrip()
        except Exception as e:
            rel = os.path.relpath(abs_path, self.project_root).replace("\\", "/")
            return f"[Error reading file: {rel} | {e}]"