import os
import hashlib
from pathlib import Path
from typing import Optional

from app.core.app_constants import PROJECT_ROOT as APP_PROJECT_ROOT
from app.core.logging import get_logger
from app.core.renderers.doc_html_renderer import parse_markdown, render_html

logger = get_logger("app.core.services.doc_organizer_service", side="worker")

PROJECT_ROOT = Path(APP_PROJECT_ROOT)
DEFAULT_INPUT_DIR = PROJECT_ROOT / "docs"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "docs" / "导出HTML"


class DocOrganizerService:
    def __init__(self, input_dir: Path = None, output_dir: Path = None):
        self._input_dir = input_dir or DEFAULT_INPUT_DIR
        self._output_dir = output_dir or DEFAULT_OUTPUT_DIR
        self._hash_cache: dict[str, str] = {}

    def convert_file(self, input_path: Path, output_dir: Path = None) -> Optional[Path]:
        if not input_path.exists():
            logger.warning("文件不存在: %s", input_path)
            return None

        md_text = input_path.read_text(encoding="utf-8")
        doc = parse_markdown(md_text)
        html_content = render_html(doc)

        out_dir = output_dir or self._output_dir
        out_dir.mkdir(parents=True, exist_ok=True)
        output_path = out_dir / (input_path.stem + ".html")
        output_path.write_text(html_content, encoding="utf-8")

        logger.info("转换完成: %s → %s", input_path.name, output_path)
        return output_path

    def convert_single(self, filename: str) -> Optional[Path]:
        input_path = self._input_dir / filename
        return self.convert_file(input_path)

    def batch_convert(self) -> list[Path]:
        results = []
        for md_file in sorted(self._input_dir.glob("*.md")):
            try:
                out = self.convert_file(md_file)
                if out:
                    results.append(out)
            except Exception as e:
                logger.warning("转换失败: %s | %s", md_file.name, e)
        return results

    def scan_changed(self) -> list[Path]:
        changed = []
        for md_file in sorted(self._input_dir.glob("*.md")):
            current_hash = self._file_hash(md_file)
            cached_hash = self._hash_cache.get(str(md_file))
            if cached_hash != current_hash:
                self._hash_cache[str(md_file)] = current_hash
                changed.append(md_file)
        return changed

    def convert_changed(self) -> list[Path]:
        changed = self.scan_changed()
        results = []
        for md_file in changed:
            try:
                out = self.convert_file(md_file)
                if out:
                    results.append(out)
            except Exception as e:
                logger.warning("增量转换失败: %s | %s", md_file.name, e)
        return results

    def generate_index(self) -> Optional[Path]:
        html_files = sorted(self._output_dir.glob("*.html"))
        if not html_files:
            return None

        items_html = ""
        for hf in html_files:
            name = hf.stem
            items_html += (
                f'<a href="{hf.name}" style="display:block;padding:16px 20px;'
                f'background:var(--surface);border:1px solid var(--border);'
                f'border-radius:var(--radius);color:var(--text);text-decoration:none;'
                f'font-size:15px;font-weight:600;transition:all .3s ease;">'
                f"📄 {name}</a>"
            )

        index_html = (
            f'<!DOCTYPE html><html lang="zh-CN"><head><meta charset="UTF-8">'
            f'<meta name="viewport" content="width=device-width,initial-scale=1.0">'
            f"<title>文档索引</title>"
            f'<style>:root{{--bg:#0f1117;--surface:#1a1d2e;--border:#2e3350;--text:#e8eaf6;--accent1:#6c63ff;--radius:12px}}*{{margin:0;padding:0;box-sizing:border-box}}body{{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif;background:var(--bg);color:var(--text);line-height:1.7;padding:40px 24px}}h1{{font-size:32px;font-weight:800;text-align:center;margin-bottom:40px;background:linear-gradient(135deg,#fff,var(--accent1));-webkit-background-clip:text;-webkit-text-fill-color:transparent;background-clip:text}}.grid{{max-width:800px;margin:0 auto;display:grid;gap:12px}}a:hover{{transform:translateY(-2px);box-shadow:0 8px 25px rgba(0,0,0,0.3);border-color:rgba(108,99,255,0.3)}}</style>'
            f"</head><body>"
            f"<h1>📚 文档索引</h1>"
            f'<div class="grid">{items_html}</div>'
            f"</body></html>"
        )

        index_path = self._output_dir / "index.html"
        index_path.write_text(index_html, encoding="utf-8")
        logger.info("索引页已生成: %s", index_path)
        return index_path

    def _file_hash(self, path: Path) -> str:
        content = path.read_bytes()
        return hashlib.md5(content).hexdigest()
