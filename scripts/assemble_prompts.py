#!/usr/bin/env python3
"""
assemble_prompts.py

读取仓库中 Prompt 目录下的三个系统提示词文件，并按顺序合并为一个文件：
  1. 兼容提示词.md
  2. Plan_SystemPrompt.md
  3. Build_SystemPrompt.md

输出到: Prompt\系统提示词.md

脚本会在每段之间插入短的中文衔接说明，保留原文不作改动。
"""
from pathlib import Path
from datetime import datetime


def read_file(path: Path) -> str:
    if not path.exists():
        return f"<!-- MISSING: {path.name} -->\n"
    return path.read_text(encoding="utf-8")


def main():
    repo_root = Path(__file__).resolve().parent.parent
    prompt_dir = repo_root / 'Prompt'

    files = [
        ('兼容提示词', prompt_dir / '兼容提示词.md'),
        ('计划提示词', prompt_dir / 'Plan_SystemPrompt.md'),
        ('执行提示词', prompt_dir / 'Build_SystemPrompt.md'),
    ]

    out_path = prompt_dir / '系统提示词.md'

    # For machine/system injection we produce a pure concatenation of the
    # source prompt files in the specified order without extra human-facing
    # headers, timestamps or explanatory comments. This keeps the output
    # minimal and suitable for direct use as a system prompt.
    # Produce a filtered concatenation: remove code examples, blockquotes,
    # HTML comments and common "human-facing" sections like 示例/注意事项/使用场景.
    def filter_text(text: str) -> str:
        lines = text.splitlines()
        out_lines = []
        in_code = False
        skip_section = False
        for i, line in enumerate(lines):
            stripped = line.strip()
            # toggle code fence blocks
            if stripped.startswith('```'):
                in_code = not in_code
                continue
            if in_code:
                continue

            # drop HTML comments
            if stripped.startswith('<!--') and stripped.endswith('-->'):
                continue
            if stripped.startswith('<!--'):
                # skip until closing -->
                # find the end
                j = i
                while j < len(lines) and '-->' not in lines[j]:
                    j += 1
                # advance the loop index by skipping (we'll rely on for loop advancing)
                continue

            # drop blockquotes
            if stripped.startswith('>'):
                continue

            # detect headings that indicate human-facing sections
            if stripped.startswith('#'):
                # get heading text without leading hashes
                title = stripped.lstrip('#').strip()
                human_keywords = ['示例', '注意', '使用场景', '使用原则', '常见模式', '快速参考', '注意事项', '示例对比', '示例']
                if any(kw in title for kw in human_keywords):
                    skip_section = True
                    continue
                else:
                    # encountering a new non-human heading stops skipping
                    skip_section = False

            if skip_section:
                continue

            out_lines.append(line)

        # trim leading/trailing blank lines
        # remove repeated consecutive blank lines
        cleaned = []
        prev_blank = False
        for l in out_lines:
            if l.strip() == '':
                if not prev_blank:
                    cleaned.append('')
                prev_blank = True
            else:
                cleaned.append(l)
                prev_blank = False

        return '\n'.join(cleaned).strip()

    parts = []
    for idx, (_, path) in enumerate(files):
        raw = read_file(path)
        filtered = filter_text(raw)
        if not filtered:
            continue

        # Insert minimal, explicit mode说明 between sections so the
        # resulting system prompt is unambiguous about the role/permission
        # expectations for the following block.
        if idx == 1:
            # Before the Plan/分析 section
            parts.append('【系统说明】下面为“计划模式”（只读）：用于分析现状、提出可执行方案与实施计划。')
        elif idx == 2:
            # Before the Build/执行 section
            parts.append('【系统说明】下面为“构建模式”（可写/可执行）：在用户确认方案后执行修改、验证并交付结果。')

        parts.append(filtered)

    out_text = "\n\n".join(p for p in parts if p) + "\n"

    out_path.write_text(out_text, encoding='utf-8')
    print(f'WROTE: {out_path}')


if __name__ == '__main__':
    main()
