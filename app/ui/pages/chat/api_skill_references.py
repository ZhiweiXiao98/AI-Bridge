"""Skill reference helper for API chat input.

This is intentionally conversation-oriented.  Typing "/" in the API input
offers Skill references and exact "/skill_name ..." input is normalized to the
Codex-style "$skill_name ..." mention before sending to the model.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from typing import Callable, Iterable, Optional

from app.core.app_constants import APP_ROOT
from app.core.skills.loader import SkillLoader


@dataclass(frozen=True)
class SkillReference:
    name: str
    description: str = ""
    category: str = ""

    @property
    def mention(self) -> str:
        return f"${self.name}"


@dataclass(frozen=True)
class SkillReferenceResult:
    handled: bool
    send_text: Optional[str] = None
    suggestions: tuple[str, ...] = ()
    status: str = ""


def _skill_dirs() -> list[str]:
    root = os.path.join(APP_ROOT, "app", "core", "skills")
    return [
        os.path.join(root, "core"),
        os.path.join(root, "extended"),
        os.path.join(root, "external"),
    ]


@lru_cache(maxsize=1)
def load_api_skill_references() -> tuple[SkillReference, ...]:
    skills: list[SkillReference] = []
    seen: set[str] = set()
    for directory in _skill_dirs():
        if not os.path.isdir(directory):
            continue
        for item in sorted(os.listdir(directory)):
            path = os.path.join(directory, item)
            if not os.path.isdir(path) or item.startswith((".", "__")):
                continue
            ok, data, _error = SkillLoader.load_skill_md(path)
            if not ok or not isinstance(data, dict):
                continue
            meta = data.get("metadata") if isinstance(data.get("metadata"), dict) else {}
            name = str(meta.get("name") or item).strip()
            if not name or name in seen:
                continue
            seen.add(name)
            skills.append(SkillReference(
                name=name,
                description=str(meta.get("description") or meta.get("scenario") or "").strip(),
                category=str(meta.get("category") or "").strip(),
            ))
    return tuple(sorted(skills, key=lambda s: s.name))


def _normalize_query(value: str) -> str:
    return str(value or "").strip().lower().replace("-", "_")


def _match_skills(query: str, skills: Iterable[SkillReference], limit: int = 8) -> list[SkillReference]:
    needle = _normalize_query(query)
    ranked: list[tuple[int, SkillReference]] = []
    for skill in skills:
        name = _normalize_query(skill.name)
        desc = _normalize_query(skill.description)
        if not needle:
            score = 0
        elif name == needle:
            score = -10
        elif name.startswith(needle):
            score = -5
        elif needle in name:
            score = -3
        elif needle in desc:
            score = -1
        else:
            continue
        ranked.append((score, skill))
    ranked.sort(key=lambda item: (item[0], item[1].name))
    return [skill for _score, skill in ranked[:limit]]


def _exact_skill(name: str, skills: Iterable[SkillReference]) -> Optional[SkillReference]:
    needle = _normalize_query(name)
    for skill in skills:
        if _normalize_query(skill.name) == needle:
            return skill
    return None


class ApiSkillReferenceHandler:
    def __init__(self, page, skills_provider: Optional[Callable[[], Iterable[SkillReference]]] = None):
        self.page = page
        self.skills_provider = skills_provider or load_api_skill_references
        self._slash_suggestion_active = False

    def resolve(self, text: str) -> SkillReferenceResult:
        raw = str(text or "")
        stripped = raw.strip()
        if not stripped.startswith("/"):
            return SkillReferenceResult(handled=False)

        body = stripped[1:].strip()
        skills = tuple(self.skills_provider())
        if not body:
            suggestions = tuple(skill.mention for skill in _match_skills("", skills))
            return SkillReferenceResult(
                handled=True,
                suggestions=suggestions,
                status="选择一个 Skill 引用",
            )

        token, _, rest = body.partition(" ")
        exact = _exact_skill(token, skills)
        if exact:
            mention = exact.mention
            send_text = f"{mention} {rest.strip()}".strip()
            return SkillReferenceResult(handled=True, send_text=send_text)

        matches = _match_skills(token, skills)
        suggestions = tuple(skill.mention for skill in matches)
        status = f"没有匹配的 Skill: /{token}" if not suggestions else "选择一个 Skill 引用"
        return SkillReferenceResult(handled=True, suggestions=suggestions, status=status)

    def handle(self, text: str) -> tuple[bool, Optional[str]]:
        result = self.resolve(text)
        if not result.handled:
            return False, text
        if result.send_text is not None:
            return False, result.send_text

        input_area = getattr(self.page, "api_input_area", None)
        if input_area and hasattr(input_area, "show_suggestions") and result.suggestions:
            input_area.show_suggestions(list(result.suggestions))

        header = getattr(self.page, "header", None)
        if header and hasattr(header, "set_status") and result.status:
            header.set_status(result.status)
        return True, None

    def update_suggestions_for_input(self):
        input_area = getattr(self.page, "api_input_area", None)
        input_box = getattr(input_area, "input_box", None)
        if not input_area or not input_box:
            return

        text = input_box.toPlainText()
        cursor = input_box.textCursor()
        pos = cursor.position()
        token = self._token_before_cursor(text, pos)
        if token.startswith("/"):
            query = token[1:]
            skills = tuple(self.skills_provider())
            suggestions = tuple(skill.mention for skill in _match_skills(query, skills))
            if suggestions:
                input_area.show_suggestions(list(suggestions))
                self._slash_suggestion_active = True
                return

        if self._slash_suggestion_active:
            suggestion_bar = getattr(input_area, "suggestion_bar", None)
            if suggestion_bar is not None:
                suggestion_bar.hide()
            self._slash_suggestion_active = False

    @staticmethod
    def _token_before_cursor(text: str, cursor_pos: int) -> str:
        text = str(text or "")
        cursor_pos = max(0, min(len(text), int(cursor_pos or 0)))
        start = cursor_pos
        while start > 0 and not text[start - 1].isspace():
            start -= 1
        return text[start:cursor_pos]
