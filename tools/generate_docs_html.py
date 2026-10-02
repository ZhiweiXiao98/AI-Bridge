#!/usr/bin/env python3
"""
资料整理 Agent - Markdown → HTML 交付展示页生成器

手动触发入口，调用 app.core.services.doc_organizer_service

用法:
  python tools/generate_docs_html.py docs/资料整理Agent实施计划书.md
  python tools/generate_docs_html.py docs/资料整理Agent实施计划书.md -o docs/导出HTML/
  python tools/generate_docs_html.py docs/ --batch
"""

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.core.services.doc_organizer_service import DocOrganizerService

DEFAULT_INPUT_DIR = PROJECT_ROOT / "docs"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "docs" / "导出HTML"


def main():
    parser = argparse.ArgumentParser(
        description="资料整理 Agent - Markdown → HTML 交付展示页生成器"
    )
    parser.add_argument("input", help="输入 Markdown 文件或 docs/ 目录（批量模式）")
    parser.add_argument("-o", "--output", default=str(DEFAULT_OUTPUT_DIR), help="输出目录")
    parser.add_argument("--batch", action="store_true", help="批量转换模式")
    parser.add_argument("--index", action="store_true", help="同时生成索引页")
    parser.add_argument("--open", action="store_true", help="转换后自动打开浏览器")
    args = parser.parse_args()

    input_path = Path(args.input)
    output_dir = Path(args.output)
    service = DocOrganizerService(output_dir=output_dir)
    output_path = None

    if not input_path.exists():
        print(f"错误：输入路径不存在 - {input_path}")
        sys.exit(1)

    if args.batch or input_path.is_dir():
        input_dir = input_path if input_path.is_dir() else input_path.parent
        service_with_dir = DocOrganizerService(input_dir=input_dir, output_dir=output_dir)
        print(f"批量转换: {input_dir} -> {output_dir}")
        results = service_with_dir.batch_convert()
        print(f"\n完成！共转换 {len(results)} 个文件")
        if results:
            output_path = results[0]
    else:
        output_path = service.convert_file(input_path)
        if output_path:
            print(f"转换完成: {input_path} -> {output_path}")
        else:
            print(f"转换失败: {input_path}")
            sys.exit(1)

    if args.index:
        idx_path = service.generate_index()
        if idx_path:
            print(f"索引页已生成: {idx_path}")

    if args.open and output_path:
        import webbrowser
        webbrowser.open(output_path.as_uri())


if __name__ == "__main__":
    main()
