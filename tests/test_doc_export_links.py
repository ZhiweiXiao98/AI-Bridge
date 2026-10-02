from urllib.parse import quote

from app.core.services.doc_organizer_service import DocOrganizerService
from app.core.services import doc_organizer_service


def test_export_resolves_links_from_markdown_directory(tmp_path):
    docs = tmp_path / "docs"
    docs.mkdir()
    source = docs / "入口.md"
    source.write_text(
        '# 入口\n\n## 导航\n'
        '[说明](../README.md#install)\n'
        '[中文](指南.md?view=1#章节)\n'
        '[网站](https://example.com/docs?q=1&v=2)\n'
        '[段落](#导航)\n', encoding="utf-8"
    )
    output = DocOrganizerService(output_dir=docs / "导出HTML").convert_file(source)
    rendered = output.read_text(encoding="utf-8")
    assert 'href="../../README.md#install"' in rendered
    assert f'href="../{quote("指南.md")}?view=1#章节"' in rendered
    assert 'href="https://example.com/docs?q=1&amp;v=2"' in rendered
    assert 'href="#导航"' in rendered


def test_export_index_does_not_link_to_itself(tmp_path):
    (tmp_path / "指南.html").write_text("page", encoding="utf-8")
    service = DocOrganizerService(output_dir=tmp_path)
    service.generate_index()
    index = service.generate_index()
    rendered = index.read_text(encoding="utf-8")
    assert 'href="指南.html"' in rendered
    assert 'href="index.html"' not in rendered


def test_export_across_drives_uses_file_uri(tmp_path, monkeypatch):
    source = tmp_path / "入口.md"
    source.write_text('# 入口\n\n## 导航\n[说明](README.md#install)\n', encoding="utf-8")

    def different_drives(*args):
        raise ValueError("path is on a different mount")

    with monkeypatch.context() as patch:
        patch.setattr(doc_organizer_service.os.path, "relpath", different_drives)
        output = DocOrganizerService(output_dir=tmp_path / "export").convert_file(source)
    target = (tmp_path / "README.md").as_uri()
    assert f'href="{target}#install"' in output.read_text(encoding="utf-8")
