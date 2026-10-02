"""结构扫描输出隔离，避免覆盖人工文档或扫描调用者目录。"""

from tools import smart_update_structure as structure


def test_dump_preserves_navigation_and_uses_project_root(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    (root / "docs").mkdir(parents=True)
    navigation = root / "docs" / "项目结构导航.md"
    navigation.write_text("人工维护导航", encoding="utf-8")
    (root / "server.py").write_text("pass", encoding="utf-8")
    cache = root / "knowledge_bases"
    cache.mkdir()
    (cache / "local.db").write_text("cache", encoding="utf-8")
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "unrelated.py").write_text("pass", encoding="utf-8")
    monkeypatch.setattr(structure, "PROJECT_ROOT", str(root))
    target = root / "docs" / "PROJECT_STRUCTURE_DUMP.md"
    monkeypatch.setattr(structure, "TARGET_MD", str(target))
    monkeypatch.chdir(outside)

    structure.generate_structure()
    structure.generate_structure()

    output = target.read_text(encoding="utf-8")
    assert "`server.py`" in output
    assert "local.db" not in output
    assert "unrelated.py" not in output
    assert "`docs/PROJECT_STRUCTURE_DUMP.md`" not in output
    assert navigation.read_text(encoding="utf-8") == "人工维护导航"
