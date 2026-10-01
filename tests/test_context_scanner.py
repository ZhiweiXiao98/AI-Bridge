from app.core.services.context_scanner import ContextScanner


def test_context_scanner_skips_generated_dependency_trees(tmp_path):
    project_root = tmp_path
    app_file = project_root / "app" / "main.py"
    app_file.parent.mkdir(parents=True)
    app_file.write_text("def ok():\n    return 1\n", encoding="utf-8")

    vendored_test = (
        project_root
        / "mobile"
        / "build"
        / "site-packages"
        / "arm64-v8a"
        / "passlib"
        / "tests"
        / "test_apache.py"
    )
    vendored_test.parent.mkdir(parents=True)
    vendored_test.write_text('pattern = "\\("\n', encoding="utf-8")

    scanner = ContextScanner(str(project_root))
    file_list, *_ = scanner.scan()
    rel_paths = {rel_path for rel_path, _ in file_list}

    assert "app/main.py" in rel_paths
    assert "mobile/build/site-packages/arm64-v8a/passlib/tests/test_apache.py" not in rel_paths
