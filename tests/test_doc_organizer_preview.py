from pathlib import Path

from app.core.app_constants import PROJECT_ROOT
from app.core.services.doc_status_tracker import DocStatusTracker
from app.ui.components.panels import doc_organizer_panel_logic as logic_module


class DummyPanel:
    pass


def test_doc_organizer_open_html_uses_embedded_browser_opener(monkeypatch, tmp_path):
    output_dir = tmp_path / "导出HTML"
    output_dir.mkdir()
    html_path = output_dir / "计划书.html"
    html_path.write_text("<html><body>plan</body></html>", encoding="utf-8")
    opened = []

    monkeypatch.setattr(logic_module, "DEFAULT_OUTPUT_DIR", output_dir)

    logic = logic_module.DocOrganizerPanelLogic(
        panel=DummyPanel(),
        html_opener=lambda path, filename: opened.append((Path(path), filename)),
    )

    logic.open_html("计划书.md")

    assert opened == [(html_path, "计划书.md")]


def test_doc_organizer_default_output_dir_uses_project_docs():
    assert logic_module.DEFAULT_OUTPUT_DIR == Path(PROJECT_ROOT) / "docs" / "导出HTML"


def test_doc_status_tracker_prunes_deleted_markdown_entries(tmp_path):
    docs_dir = tmp_path / "docs"
    output_dir = tmp_path / "导出HTML"
    docs_dir.mkdir()
    output_dir.mkdir()

    old_doc = docs_dir / "旧文档.md"
    old_doc.write_text("# old", encoding="utf-8")

    tracker = DocStatusTracker(docs_dir=docs_dir, output_dir=output_dir)
    tracker.scan_all()
    assert tracker.get_status("旧文档.md").status == "missing"

    old_doc.unlink()
    new_doc = docs_dir / "新文档.md"
    new_doc.write_text("# new", encoding="utf-8")

    statuses = tracker.scan_all()

    assert [s.filename for s in statuses] == ["新文档.md"]
    assert [s.filename for s in tracker.get_outdated()] == ["新文档.md"]
    assert tracker.get_status("旧文档.md").status == "missing"
