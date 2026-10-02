from __future__ import annotations

import os
import re
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any, Iterable, List, Optional

from app.core.app_constants import APP_ROOT
from app.core.skills.base import BaseSkill, SkillMetadata, SkillParameter


DATE_RE = re.compile(r"(?P<date>\d{4}-\d{2}-\d{2})")
HEADING_RE = re.compile(r"^##\s+(?P<title>.+?)\s*$")


@dataclass
class Heading:
    source: str
    path: Path
    line_no: int
    title: str
    parsed_date: Optional[date]


class JournalSearchSkill(BaseSkill):
    """Query AI_JOURNAL without loading the whole archive into context."""

    @property
    def metadata(self) -> SkillMetadata:
        return SkillMetadata(
            name="journal_search",
            display_name="行驶记录查询",
            category="system",
            description="按需查询 AI_JOURNAL 行驶记录和完整历史归档，返回标题、片段或指定条目",
            scenario="需要追溯项目历史决策、Bug 修复记录、用户约束、长期记忆证据时",
            version="1.0.0",
            author="System",
            parameters=[
                SkillParameter("mode", "str", False, "search/latest/index/entry/stats", "search"),
                SkillParameter("query", "str", False, "搜索关键词或标题片段", ""),
                SkillParameter("date_from", "str", False, "起始日期 YYYY-MM-DD", ""),
                SkillParameter("date_to", "str", False, "结束日期 YYYY-MM-DD", ""),
                SkillParameter("limit", "int", False, "返回条数，默认 8，最大 30", 8),
                SkillParameter("source", "str", False, "current/archive/all", "all"),
                SkillParameter("max_chars", "int", False, "最大返回字符数，默认 8000，最大 20000", 8000),
            ],
            examples=[
                "journal_search(mode='search', query='项目切换')",
                "journal_search(mode='latest', limit=10)",
                "journal_search(mode='entry', query='UI 热切换项目')",
            ],
            dangerous=False,
        )

    def _get_parameters_schema(self) -> dict:
        return {
            "mode": {
                "type": "string",
                "enum": ["search", "latest", "index", "entry", "stats"],
                "description": "查询模式",
                "default": "search",
            },
            "query": {"type": "string", "description": "搜索关键词或标题片段", "default": ""},
            "date_from": {"type": "string", "description": "起始日期 YYYY-MM-DD", "default": ""},
            "date_to": {"type": "string", "description": "结束日期 YYYY-MM-DD", "default": ""},
            "limit": {"type": "integer", "description": "返回条数，默认 8，最大 30", "default": 8},
            "source": {
                "type": "string",
                "enum": ["current", "archive", "all"],
                "description": "查询数据源",
                "default": "all",
            },
            "max_chars": {
                "type": "integer",
                "description": "最大返回字符数，默认 8000，最大 20000",
                "default": 8000,
            },
        }

    def _get_required_parameters(self) -> list:
        return []

    def execute(
        self,
        mode: str = "search",
        query: str = "",
        date_from: str = "",
        date_to: str = "",
        limit: int = 8,
        source: str = "all",
        max_chars: int = 8000,
        **kwargs,
    ) -> Any:
        mode = self._normalize_mode(mode)
        source = self._normalize_source(source)
        limit = self._clamp_int(limit, 8, 1, 30)
        max_chars = self._clamp_int(max_chars, 8000, 1000, 20000)
        query = str(query or "").strip()

        if mode == "stats":
            return self._limit_output(self._stats(source), max_chars)

        if mode == "latest":
            return self._limit_output(self._latest(source, limit), max_chars)

        if mode == "index":
            return self._limit_output(
                self._index(source, query, date_from, date_to, limit),
                max_chars,
            )

        if mode == "entry":
            return self._limit_output(
                self._entry(source, query, date_from, date_to, max_chars),
                max_chars,
            )

        return self._limit_output(
            self._search(source, query, date_from, date_to, limit),
            max_chars,
        )

    def _journal_files(self, source: str) -> list[tuple[str, Path]]:
        root = Path(APP_ROOT)
        current = root / "AI_JOURNAL.md"
        archive_dir = root / "docs" / "归档"

        files: list[tuple[str, Path]] = []
        if source in ("current", "all"):
            files.append(("current", current))
        if source in ("archive", "all"):
            # 日期归档自动接入查询；标题索引不匹配此模式，避免重复命中。
            archives = sorted(archive_dir.glob("AI行驶记录完整归档_*.md"), reverse=True)
            files.extend(("archive", path) for path in archives)
        return [(label, path) for label, path in files if path.is_file()]

    def _read_lines(self, path: Path) -> list[str]:
        return path.read_text(encoding="utf-8-sig", errors="replace").splitlines()

    def _headings(self, source: str) -> list[Heading]:
        headings: list[Heading] = []
        for label, path in self._journal_files(source):
            for idx, line in enumerate(self._read_lines(path), start=1):
                match = HEADING_RE.match(line)
                if not match:
                    continue
                title = match.group("title").strip()
                headings.append(Heading(label, path, idx, title, self._parse_date(title)))
        return headings

    def _stats(self, source: str) -> str:
        rows = ["# AI_JOURNAL 统计", ""]
        total_bytes = 0
        total_headings = 0
        all_headings = self._headings(source)
        for label, path in self._journal_files(source):
            size = path.stat().st_size
            lines = len(self._read_lines(path))
            headings = [h for h in all_headings if h.path == path]
            total_bytes += size
            total_headings += len(headings)
            rows.append(f"- `{label}` `{self._rel(path)}`: {size:,} bytes, {lines:,} lines, {len(headings)} headings")
        rows.append("")
        rows.append(f"合计：{total_bytes:,} bytes, {total_headings} headings")
        return "\n".join(rows)

    def _latest(self, source: str, limit: int) -> str:
        headings = [h for h in self._headings(source) if h.parsed_date]
        headings.sort(key=lambda h: (h.parsed_date or date.min, h.path.as_posix(), h.line_no), reverse=True)
        return self._format_heading_list("# 最近行驶记录", headings[:limit])

    def _index(self, source: str, query: str, date_from: str, date_to: str, limit: int) -> str:
        headings = self._filter_headings(self._headings(source), query, date_from, date_to)
        headings.sort(key=lambda h: (h.parsed_date or date.min, h.path.as_posix(), h.line_no), reverse=True)
        return self._format_heading_list("# 行驶记录标题索引", headings[:limit])

    def _search(self, source: str, query: str, date_from: str, date_to: str, limit: int) -> str:
        if not query:
            return "❌ search 模式需要 query。示例：journal_search(mode='search', query='项目切换')"

        terms = self._terms(query)
        date_start = self._parse_date_arg(date_from)
        date_end = self._parse_date_arg(date_to)
        matches: list[str] = []

        for label, path in self._journal_files(source):
            lines = self._read_lines(path)
            heading_for_line = self._heading_lookup(lines)
            for idx, line in enumerate(lines):
                if not self._contains_all(line, terms):
                    continue
                heading = heading_for_line[idx]
                heading_date = self._parse_date(heading) if heading else None
                if not self._date_in_range(heading_date, date_start, date_end):
                    continue
                snippet = self._snippet(lines, idx, context=2)
                matches.append(
                    f"## {len(matches) + 1}. `{label}` {self._rel(path)}:{idx + 1}\n"
                    f"**Entry**: {heading or '(no heading)'}\n\n"
                    f"```text\n{snippet}\n```"
                )
                if len(matches) >= limit:
                    return "# 行驶记录搜索结果\n\n" + "\n\n".join(matches)

        if not matches:
            return f"未找到匹配：{query}"
        return "# 行驶记录搜索结果\n\n" + "\n\n".join(matches)

    def _entry(self, source: str, query: str, date_from: str, date_to: str, max_chars: int) -> str:
        headings = self._filter_headings(self._headings(source), query, date_from, date_to)
        if not headings:
            if query:
                return f"未找到标题匹配：{query}"
            return "❌ entry 模式需要 query 或 date_from/date_to。"

        headings.sort(key=lambda h: (h.parsed_date or date.min, h.path.as_posix(), h.line_no), reverse=True)
        selected = headings[0]
        lines = self._read_lines(selected.path)
        start = selected.line_no - 1
        end = len(lines)
        for i in range(start + 1, len(lines)):
            if HEADING_RE.match(lines[i]):
                end = i
                break
        body = "\n".join(lines[start:end]).strip()
        header = f"# 行驶记录条目\n\nSource: `{selected.source}` `{self._rel(selected.path)}:{selected.line_no}`\n\n"
        return header + body[: max_chars - len(header)]

    def _filter_headings(self, headings: Iterable[Heading], query: str, date_from: str, date_to: str) -> list[Heading]:
        terms = self._terms(query)
        date_start = self._parse_date_arg(date_from)
        date_end = self._parse_date_arg(date_to)
        result: list[Heading] = []
        for heading in headings:
            if terms and not self._contains_all(heading.title, terms):
                continue
            if not self._date_in_range(heading.parsed_date, date_start, date_end):
                continue
            result.append(heading)
        return result

    def _format_heading_list(self, title: str, headings: list[Heading]) -> str:
        if not headings:
            return f"{title}\n\n未找到匹配标题。"
        rows = [title, ""]
        for heading in headings:
            rows.append(f"- `{heading.source}` {self._rel(heading.path)}:{heading.line_no} — {heading.title}")
        return "\n".join(rows)

    def _heading_lookup(self, lines: list[str]) -> list[str]:
        current = ""
        lookup: list[str] = []
        for line in lines:
            match = HEADING_RE.match(line)
            if match:
                current = match.group("title").strip()
            lookup.append(current)
        return lookup

    def _snippet(self, lines: list[str], idx: int, context: int = 2) -> str:
        start = max(0, idx - context)
        end = min(len(lines), idx + context + 1)
        return "\n".join(f"{i + 1}: {lines[i]}" for i in range(start, end))

    def _terms(self, query: str) -> list[str]:
        return [t.lower() for t in re.split(r"\s+", str(query or "").strip()) if t]

    def _contains_all(self, text: str, terms: list[str]) -> bool:
        lower = text.lower()
        return all(term in lower for term in terms)

    def _parse_date(self, text: str) -> Optional[date]:
        match = DATE_RE.search(str(text or ""))
        if not match:
            return None
        try:
            return datetime.strptime(match.group("date"), "%Y-%m-%d").date()
        except ValueError:
            return None

    def _parse_date_arg(self, value: str) -> Optional[date]:
        value = str(value or "").strip()
        if not value:
            return None
        try:
            return datetime.strptime(value, "%Y-%m-%d").date()
        except ValueError:
            return None

    def _date_in_range(self, value: Optional[date], start: Optional[date], end: Optional[date]) -> bool:
        if not start and not end:
            return True
        if not value:
            return False
        if start and value < start:
            return False
        if end and value > end:
            return False
        return True

    def _normalize_mode(self, mode: str) -> str:
        mode = str(mode or "search").strip().lower()
        return mode if mode in {"search", "latest", "index", "entry", "stats"} else "search"

    def _normalize_source(self, source: str) -> str:
        source = str(source or "all").strip().lower()
        return source if source in {"current", "archive", "all"} else "all"

    def _clamp_int(self, value: Any, default: int, low: int, high: int) -> int:
        try:
            parsed = int(value)
        except Exception:
            parsed = default
        return max(low, min(high, parsed))

    def _limit_output(self, text: str, max_chars: int) -> str:
        if len(text) <= max_chars:
            return text
        return text[:max_chars] + f"\n\n...（已截断，总长度 {len(text)} 字符；可缩小 query 或提高 max_chars）"

    def _rel(self, path: Path) -> str:
        try:
            return os.path.relpath(path, APP_ROOT).replace("\\", "/")
        except Exception:
            return str(path)


__skill__ = JournalSearchSkill
