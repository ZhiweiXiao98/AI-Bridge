from typing import List, Dict


class MarkdownCodeBlockParser:
    """解析 API 回复中的 fenced code blocks，输出兼容 UI 的 segments。"""

    @staticmethod
    def _build_tool_summary(tool_name: str, operation: str, target: str, query: str) -> str:
        tool = (tool_name or '').strip()
        op = (operation or '').strip()
        tgt = (target or '').strip()
        q = (query or '').strip()

        if tool == 'file_operations':
            mapping = {
                'read_file': '🛠 查看文件',
                'list_files': '🛠 查看目录',
                'write_file': '🛠 写入文件',
                'append_file': '🛠 追加文件',
                'replace_in_file': '🛠 修改文件',
                'insert_after': '🛠 在文件后插入',
                'insert_before': '🛠 在文件前插入',
                'file_exists': '🛠 检查文件是否存在',
                'stat_file': '🛠 查看文件信息',
            }
            base = mapping.get(op, '🛠 文件操作')
            return f'{base} {tgt}'.strip()

        if tool == 'knowledge_search':
            return f'🔍 搜索代码 {q}'.strip()

        if tool == 'web_search':
            return f'🌐 搜索网页 {q}'.strip()

        if tool == 'code_execution':
            return '▶ 执行 Python 代码'

        summary = tool or 'tool_call'
        if op:
            summary += f' · {op}'
        if tgt:
            summary += f' · {tgt}'
        elif q:
            summary += f' · {q}'
        return summary

    @staticmethod
    def _extract_tool_meta(language: str, code_content: str):
        lang = (language or '').strip().lower()
        text = code_content or ''
        compact = text.strip()
        if not compact:
            return None

        if lang == 'tool_call':
            tool_name = ''
            operation = ''
            target = ''
            query = ''
            for line in text.split('\n'):
                s = line.strip()
                if '"name"' in s and ':' in s and not tool_name:
                    tool_name = s.split(':', 1)[1].strip().strip(',').strip().strip('"')
                if '"operation"' in s and ':' in s and not operation:
                    operation = s.split(':', 1)[1].strip().strip(',').strip().strip('"')
                if '"path"' in s and ':' in s and not target:
                    target = s.split(':', 1)[1].strip().strip(',').strip().strip('"')
                if '"query"' in s and ':' in s and not query:
                    query = s.split(':', 1)[1].strip().strip(',').strip().strip('"')
            summary = MarkdownCodeBlockParser._build_tool_summary(tool_name, operation, target, query)
            return {
                'kind': 'tool_call',
                'tool_name': tool_name,
                'operation': operation,
                'target': target,
                'query': query,
                'summary': summary,
            }

        if lang == 'python':
            first_non_empty = ''
            for line in text.split('\n'):
                s = line.strip()
                if s:
                    first_non_empty = s
                    break
            if first_non_empty.startswith('# EXEC') or first_non_empty.startswith('# RUN') or first_non_empty.startswith('# EXECUTE'):
                return {
                    'kind': 'executable_python',
                    'tool_name': 'code_execution',
                    'operation': 'exec',
                    'target': '',
                    'summary': 'code_execution · 执行 Python 代码',
                }
        return None

    @staticmethod
    def parse_segments(text: str) -> List[Dict]:
        source = text or ''
        if not source:
            return []

        normalized = source.replace('\r\n', '\n').replace('\r', '\n')
        lines = normalized.split('\n')
        segments: List[Dict] = []
        text_buffer: List[str] = []

        in_code = False
        code_lines: List[str] = []
        code_lang = ''
        fence_open_raw = ''

        def flush_text():
            if not text_buffer:
                return
            content = '\n'.join(text_buffer)
            if content.strip():
                segments.append({
                    'type': 'text',
                    'content': content,
                })
            text_buffer.clear()

        def flush_code(closed: bool):
            raw_lines = []
            if fence_open_raw:
                raw_lines.append(fence_open_raw)
            raw_lines.extend(code_lines)
            if closed:
                raw_lines.append('```')
            raw_content = '\n'.join(raw_lines)
            code_content = '\n'.join(code_lines)
            tool_meta = MarkdownCodeBlockParser._extract_tool_meta(code_lang, code_content)
            segment = {
                'type': 'code',
                'content': code_content,
                'language': code_lang,
                'code': code_content,
                'raw_content': raw_content,
                'closed': closed,
            }
            if tool_meta:
                segment['tool_meta'] = tool_meta
            segments.append(segment)

        for line in lines:
            stripped = line.strip()
            if not in_code:
                if stripped.startswith('```'):
                    flush_text()
                    in_code = True
                    code_lines = []
                    code_lang = stripped[3:].strip()
                    fence_open_raw = line
                else:
                    text_buffer.append(line)
                continue

            if stripped == '```':
                flush_code(closed=True)
                in_code = False
                code_lines = []
                code_lang = ''
                fence_open_raw = ''
            else:
                code_lines.append(line)

        if in_code:
            flush_code(closed=False)

        flush_text()
        return segments
