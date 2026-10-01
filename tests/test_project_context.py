import json
from pathlib import Path

from app.core.project_context import ProjectContext


def test_switching_projects_isolates_knowledge_and_restores_working_directory(tmp_path, monkeypatch):
    # ProjectContext still changes process cwd; keep both projects and persistence temporary.
    monkeypatch.chdir(tmp_path)
    app_root = tmp_path / "app"
    app_root.mkdir()
    monkeypatch.setattr("app.core.project_context.APP_ROOT", str(app_root))
    context = ProjectContext()
    project_a = tmp_path / "a" / "same_name"
    project_b = tmp_path / "b" / "same_name"
    project_a.mkdir(parents=True)
    project_b.mkdir(parents=True)

    assert context.switch_to(str(project_a))
    db_a = context.get_knowledge_db_path()
    Path("local.txt").write_text("project a", encoding="utf-8")
    assert context.switch_to(str(project_b))
    db_b = context.get_knowledge_db_path()
    assert db_b != db_a
    assert Path(db_a).parent == Path(db_b).parent == app_root / "knowledge_bases"
    assert not Path("local.txt").exists()
    Path("local.txt").write_text("project b", encoding="utf-8")
    assert context.switch_to(str(project_a))
    assert context.get_knowledge_db_path() == db_a
    assert Path("local.txt").read_text(encoding="utf-8") == "project a"
    assert (project_b / "local.txt").read_text(encoding="utf-8") == "project b"

    saved = json.loads((app_root / "projects.json").read_text(encoding="utf-8"))
    assert saved["last_project"] == str(project_a)
    assert [p["path"] for p in saved["recent"]] == [str(project_a), str(project_b)]
    assert not context.switch_to(str(tmp_path / "missing"))
    assert Path.cwd() == project_a
