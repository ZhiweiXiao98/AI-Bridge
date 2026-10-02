"""归档轮换后仍能检索历史，且索引与统计不会重复计入。"""

import pytest

from app.core.skills.core.journal_search import skill as journal


@pytest.fixture
def journal_root(tmp_path, monkeypatch):
    monkeypatch.setattr(journal, "APP_ROOT", str(tmp_path))
    archive = tmp_path / "docs" / "归档"
    archive.mkdir(parents=True)
    (tmp_path / "AI_JOURNAL.md").write_text(
        "## 2026-09-05 | 项目整理\n当前记录\n", encoding="utf-8"
    )
    (archive / "AI行驶记录完整归档_2026-06-20.md").write_text(
        "## 2026-06-19 | 旧阶段\n旧记录\n", encoding="utf-8"
    )
    (archive / "AI行驶记录完整归档_2026-09-05.md").write_text(
        "## 2026-06-21 | 快照落盘\n重启后恢复快照\n"
        "## 2026-06-22 | 流式思考\n思考正文\n", encoding="utf-8"
    )
    (archive / "AI行驶记录完整归档索引_2026-09-05.md").write_text(
        "## 2026-09-05 | 不应命中的索引\n", encoding="utf-8"
    )
    return journal.JournalSearchSkill()


def test_search_and_entry_find_rotated_archive(journal_root):
    result = journal_root.execute(mode="search", query="重启后恢复快照", source="archive")
    assert "AI行驶记录完整归档_2026-09-05.md" in result
    result = journal_root.execute(mode="entry", query="快照落盘")
    assert "重启后恢复快照" in result
    assert "思考正文" not in result


def test_latest_and_date_filter_span_archives(journal_root):
    result = journal_root.execute(mode="latest", limit=10)
    assert result.index("项目整理") < result.index("流式思考") < result.index("旧阶段")
    assert "不应命中" not in result
    result = journal_root.execute(mode="index", date_from="2026-06-21", date_to="2026-06-21")
    assert "快照落盘" in result
    assert "旧阶段" not in result
    assert "流式思考" not in result


def test_stats_count_each_file_once(journal_root):
    result = journal_root.execute(mode="stats", source="all")
    assert ", 4 headings" in result
    assert ", 2 headings" in result
    assert "索引_" not in result
    assert ", 3 headings" in journal_root.execute(mode="stats", source="archive")
    assert ", 1 headings" in journal_root.execute(mode="stats", source="current")


def test_missing_archives_are_allowed(tmp_path, monkeypatch):
    monkeypatch.setattr(journal, "APP_ROOT", str(tmp_path))
    result = journal.JournalSearchSkill().execute(mode="stats")
    assert "合计：0 bytes, 0 headings" in result
