# filename: app/core/driver/parser.py
import re
import copy
import json
from bs4 import BeautifulSoup, NavigableString, Tag


class DOMParser:
    def _split_tool_feedback_text_segment(self, text):
        import json

        text = str(text or '').strip()
        if not text:
            return None
        # 剥离 process_rich_text 可能包裹的外层 HTML 标签（如 <p>...</p>）
        stripped = re.sub(r'^(?:\s*<[^>]+>\s*)+', '', text)
        stripped = re.sub(r'(?:\s*</[^>]+>\s*)+$', '', stripped)
        normalized = stripped.strip() if stripped.strip() else text.lstrip()

        if normalized.startswith('[TOOL_RESULTS_BEGIN'):
            lines = [line.rstrip('\n') for line in normalized.splitlines()]
            result_segments = []
            idx = 0
            while idx < len(lines):
                line = lines[idx].strip()
                if line.startswith('[TOOL_CALL_META] '):
                    call_meta_raw = line[len('[TOOL_CALL_META] '):].strip()
                    try:
                        call_meta = json.loads(call_meta_raw)
                    except Exception:
                        idx += 1
                        continue
                    result_segments.append({
                        'type': 'tool_call',
                        'tool_call_id': call_meta.get('tool_call_id'),
                        'block_key': call_meta.get('block_key'),
                        'tool_name': call_meta.get('tool_name') or 'tool_call',
                        'content': '',
                    })
                    idx += 1
                    continue
                if not line.startswith('[TOOL_RESULT_META] '):
                    idx += 1
                    continue
                meta_raw = line[len('[TOOL_RESULT_META] '):].strip()
                try:
                    meta = json.loads(meta_raw)
                except Exception:
                    idx += 1
                    continue

                idx += 1
                while idx < len(lines) and lines[idx].strip() != '[TOOL_RESULT_BODY]':
                    idx += 1
                if idx >= len(lines):
                    break
                idx += 1

                body_lines = []
                while idx < len(lines) and lines[idx].strip() != '[TOOL_RESULT_END]':
                    body_lines.append(lines[idx])
                    idx += 1

                content_text = '\n'.join(body_lines).strip()
                result_segments.append({
                    'type': 'tool_result',
                    'tool_name': meta.get('tool_name') or 'tool_result',
                    'tool_call_id': meta.get('tool_call_id'),
                    'block_key': meta.get('block_key'),
                    'task_id': meta.get('task_id'),
                    'success': meta.get('success'),
                    'content': content_text,
                })
                idx += 1

            user_msg_match = re.search(
                r'\[USER_MESSAGE_BEGIN\]\s*(.*?)\s*\[USER_MESSAGE_END\]',
                normalized,
                re.DOTALL,
            )
            if user_msg_match:
                user_text = user_msg_match.group(1).strip()
                if user_text:
                    result_segments.append({
                        'type': 'user_message',
                        'content': user_text,
                    })

            return result_segments or [{
                'type': 'tool_result',
                'tool_name': 'tool_result',
                'success': None,
                'content': normalized,
            }]

        if not normalized.startswith('🔧 [工具执行结果]') and not normalized.startswith('[工具执行结果]') and not normalized.startswith('工具执行结果'):
            return None

        lines = [line.rstrip() for line in normalized.splitlines()]
        body_lines = []
        started = False
        for line in lines:
            if not started:
                if line.strip().startswith('🔧 [工具执行结果]') or line.strip().startswith('[工具执行结果]') or line.strip().startswith('工具执行结果'):
                    started = True
                continue
            body_lines.append(line)

        body_text = '\n'.join(body_lines).strip()
        if not body_text:
            return [{
                'type': 'tool_result',
                'tool_name': 'tool_result',
                'success': None,
                'content': normalized,
            }]

        parts = re.split(r'(?=^🔧 \[工具调用\s*\d+\])', body_text, flags=re.MULTILINE)
        result_segments = []
        for part in parts:
            chunk = str(part or '').strip()
            if not chunk:
                continue
            first_line, _, remainder = chunk.partition('\n')
            tool_name = 'tool_result'
            success = None
            header_match = re.match(r'^🔧 \[工具调用\s*\d+\]\s*(.+?)\s*$', first_line.strip())
            content_text = remainder.strip() if remainder.strip() else chunk
            if header_match:
                tool_name = str(header_match.group(1) or '').strip() or 'tool_result'
            lowered = content_text.lower()
            if '❌' in content_text or 'failed' in lowered or 'error' in lowered:
                success = False
            elif '✅' in content_text or 'succeeded' in lowered or 'verified: true' in lowered or 'ok app/' in lowered:
                success = True
            result_segments.append({
                'type': 'tool_result',
                'tool_name': tool_name,
                'success': success,
                'content': content_text,
            })

        return result_segments or [{
            'type': 'tool_result',
            'tool_name': 'tool_result',
            'success': None,
            'content': normalized,
        }]

    def parse_browser_transient_message(self, root):
        segments = []
        if not root:
            return segments, []

        node_slots = root.select('[data-node-type]') if hasattr(root, 'select') else []
        if not node_slots:
            return self.clean_code_headers(self.parse_node(root)), []

        code_index = 0
        for slot in node_slots:
            node_type = str(slot.get('data-node-type', '') or '').strip().lower()
            if not node_type:
                continue
            if node_type == 'code_block':
                code_index += 1
                placeholder_lang = self._detect_code_placeholder_language(slot)
                preview_code = self._extract_transient_code_preview(slot)
                if placeholder_lang != 'tool_call' and self._looks_like_tool_call_json(preview_code):
                    placeholder_lang = 'tool_call'
                if self._should_render_transient_code_preview(preview_code):
                    segments.append({
                        'type': 'code',
                        'content': preview_code,
                        'language': placeholder_lang,
                        'is_transient_preview': True,
                    })
                    continue
                placeholder_text = f'AI 正在生成 {placeholder_lang} 代码块，稍后展示完整内容。'
                segments.append({
                    'type': 'code_placeholder',
                    'content': placeholder_text,
                    'code_block_count': code_index,
                    'placeholder_text': placeholder_text,
                    'language': placeholder_lang,
                })
                continue
            slot_segments = self.parse_node(slot)
            for seg in slot_segments:
                if seg.get('type') != 'text':
                    continue
                text = self._sanitize_transient_text(seg.get('content', ''))
                if not text:
                    continue
                segments.append({'type': 'text', 'content': text})

        merged = []
        for seg in segments:
            if (
                merged
                and merged[-1].get('type') == 'text'
                and seg.get('type') == 'text'
            ):
                merged[-1]['content'] += seg.get('content', '')
            else:
                merged.append(seg)
        return merged, []

    def _sanitize_transient_text(self, text):
        text = str(text or '')
        if not text:
            return ''
        text = text.replace('\xa0', ' ')
        text = re.sub(r'(复制|Copy)\s*$', '', text).strip()
        text = re.sub(r'((?:[A-Za-z0-9+/]{24,}={0,2})|(?:[\u2580-\u259f\u2500-\u257f]{6,})|(?:[�]{3,}))\s*$', '', text).strip()
        text = re.sub(r'\n{3,}', '\n\n', text)
        return text.strip()

    def _normalize_code_language(self, value):
        value = str(value or '').strip()
        if not value:
            return ''
        lowered = value.lower().replace('-', '_').replace(' ', '_')
        aliases = {
            'py': 'python',
            'python3': 'python',
            'js': 'javascript',
            'ts': 'typescript',
            'md': 'markdown',
            'mark_down': 'markdown',
            'toolcall': 'tool_call',
            'tool_calls': 'tool_call',
            'tool_use': 'tool_call',
        }
        return aliases.get(lowered, lowered)

    def _extract_code_language_from_dom(self, node):
        if not isinstance(node, Tag):
            return ''

        candidates = []
        current = node
        depth = 0
        while isinstance(current, Tag):
            for attr in ('data-mode-id', 'data-language', 'data-lang'):
                val = current.get(attr)
                if val:
                    candidates.append(val)
            class_str = ' '.join(current.get('class', []))
            if (
                current.get('data-node-type') == 'code_block'
                or 'code-block-container' in class_str
                or depth >= 8
            ):
                break
            current = current.parent
            depth += 1

        for child in node.select('[data-mode-id], [data-language], [data-lang]'):
            for attr in ('data-mode-id', 'data-language', 'data-lang'):
                val = child.get(attr)
                if val:
                    candidates.append(val)

        title = node.select_one('.code-header-title')
        if title:
            candidates.append(title.get_text(' ', strip=True))

        legacy_lang = node.find('span', class_=lambda x: x and 'font-mono' in x)
        if legacy_lang:
            candidates.append(legacy_lang.get_text(' ', strip=True))

        for raw in candidates:
            lang = self._normalize_code_language(raw)
            if lang and lang not in ('code', 'plaintext', 'text'):
                return lang
        return ''

    def _detect_code_placeholder_language(self, slot):
        dom_lang = self._extract_code_language_from_dom(slot)
        if dom_lang:
            return dom_lang
        try:
            text = slot.get_text(' ', strip=True)
        except Exception:
            text = ''
        text = str(text or '').strip()
        lowered = text.lower()
        if 'tool_call' in lowered:
            return 'tool_call'
        if 'python' in lowered or '```python' in lowered or '```py' in lowered:
            return 'python'
        if 'markdown' in lowered:
            return 'markdown'
        if 'json' in lowered:
            return 'json'
        return 'code'

    def _extract_transient_code_preview(self, slot):
        try:
            preview = self.parse_code_block(slot)
        except Exception:
            preview = ''
        return str(preview or '').strip()

    def _looks_like_tool_call_json(self, text):
        text = str(text or '').strip()
        if not text:
            return False
        try:
            parsed = json.loads(text)
        except Exception:
            return False
        return isinstance(parsed, dict) and 'name' in parsed and 'arguments' in parsed

    def _should_render_transient_code_preview(self, preview_code):
        text = str(preview_code or '').strip()
        if not text:
            return False
        return True

    def process_rich_text(self, tag):
        if isinstance(tag, NavigableString):
            return str(tag).replace('<', '&lt;').replace('>', '&gt;')
        if isinstance(tag, Tag):
            if tag.name == 'img':
                return ''
            content = ''
            for child in tag.children:
                content += self.process_rich_text(child)

            tag_map = {
                'strong': f'<b>{content}</b>', 'b': f'<b>{content}</b>',
                'em': f'<i>{content}</i>', 'i': f'<i>{content}</i>',
                'u': f'<u>{content}</u>',
                'code': f'<span style="background-color:#444C56; color:#FF7B72; font-family:Consolas;">&nbsp;{content}&nbsp;</span>',
                'br': '<br>', 'p': f'<p>{content}</p>',
                'ul': f'<ul>{content}</ul>', 'ol': f'<ol>{content}</ol>', 'li': f'<li>{content}</li>',
                'table': f'<table border="1" cellspacing="0" cellpadding="5" style="border-collapse:collapse; border-color:#374151;">{content}</table>',
                'thead': f'<thead style="background-color:#1F2937;">{content}</thead>',
                'tr': f'<tr>{content}</tr>',
                'th': f'<th style="background-color:#374151; font-weight:bold;">{content}</th>',
                'td': f'<td>{content}</td>'
            }
            if tag.name in ['h1', 'h2', 'h3']:
                return f'<b>{content}</b><br>'
            return tag_map.get(tag.name, content)
        return ''

    def parse_code_block(self, node):
        lines_dom = node.find_all(class_='view-line')

        if not lines_dom:
            soup = copy.copy(node)
            for overlay in soup.find_all(class_=lambda x: x and ('margin-view-overlays' in x or 'margin' == x)):
                overlay.decompose()
            for tag in soup.find_all(True):
                c_str = ' '.join(tag.get('class', [])).lower()
                if any(x in c_str for x in ['line-number', 'index', 'copy', 'button']):
                    tag.decompose()
            return soup.get_text(separator='\n').replace('\xa0', ' ').strip()

        line_num_tops = set()
        editor_root = node.find_parent(class_='monaco-editor')
        if editor_root:
            nums = editor_root.find_all(class_=lambda x: x and 'line-numbers' in x)
            for n in nums:
                style = (n.parent.get('style', '') or '') + (n.get('style', '') or '')
                m = re.search(r'top:\s*(\d+)px', style)
                if m:
                    line_num_tops.add(int(m.group(1)))

        indexed_lines = []
        for line_el in lines_dom:
            style = line_el.get('style', '')
            match = re.search(r'top:\s*(\d+)px', style)
            if match:
                # 移除行号元素后再提取文本，避免 "12class TypingRenderer" 混入
                line_copy = copy.copy(line_el)
                for num_el in line_copy.find_all(class_=lambda x: x and 'line-numbers' in x):
                    num_el.decompose()
                for num_el in line_copy.find_all(class_=lambda x: x and 'line-number' in x):
                    num_el.decompose()
                raw_text = line_copy.get_text().replace('\xa0', ' ')
                indexed_lines.append((int(match.group(1)), raw_text))
        indexed_lines.sort(key=lambda x: x[0])

        full_code = ''
        for i, (top, text) in enumerate(indexed_lines):
            if i == 0:
                full_code = text
                continue

            is_new_line = True
            if line_num_tops:
                is_new_line = any(t in line_num_tops for t in range(top - 2, top + 3))

            if is_new_line:
                full_code += '\n' + text
            else:
                full_code += text.lstrip()

        return full_code.strip()

    def _extract_best_image_src(self, img_node):
        if not img_node:
            return None
        srcset = img_node.get('srcset')
        if srcset:
            try:
                candidates = srcset.split(',')
                best_candidate = candidates[-1].strip().split(' ')[0]
                if best_candidate:
                    return best_candidate
            except Exception:
                pass
        data_src = img_node.get('data-src')
        if data_src:
            return data_src
        return img_node.get('src')

    def parse_node(self, node):
        segments = []
        if isinstance(node, NavigableString):
            text = node.strip()
            clean_text = re.sub(r'\s+', '', text)
            if clean_text.isdigit() and len(clean_text) > 5:
                return segments
            if text:
                segments.append({'type': 'text', 'content': text})
            return segments

        classes = node.get('class', []) if isinstance(node, Tag) else []
        class_str = ' '.join(classes)

        if 'code-block-header' in class_str:
            language = self._extract_code_language_from_dom(node)
            if language:
                return [{'type': 'lang_tag', 'content': language}]
            return []

        if 'margin-view-overlays' in class_str or 'margin' in classes:
            if 'view-lines' not in classes:
                return []

        if 'view-lines' in classes or node.name == 'pre':
            code = self.parse_code_block(node)
            segment = {'type': 'code', 'content': code}
            language = self._extract_code_language_from_dom(node)
            if language:
                segment['language'] = language
            segments.append(segment)
            return segments

        if node.find(class_='view-lines') or node.find('pre') or node.find('img'):
            for child in node.children:
                segments.extend(self.parse_node(child))
            return segments

        if node.name == 'img':
            src = self._extract_best_image_src(node)
            if src:
                segments.append({'type': 'image', 'content': src})
            return segments

        inner_img = node.find('img', recursive=False)
        if not inner_img and 'n-image' in classes:
            inner_img = node.find('img')

        if inner_img:
            src = self._extract_best_image_src(inner_img)
            if src:
                segments.append({'type': 'image', 'content': src})
            return segments

        rich = self.process_rich_text(node)
        if rich.strip():
            segments.append({'type': 'text', 'content': rich})
        return segments

    def clean_code_headers(self, segments):
        cleaned = []
        pending_lang = None
        seen_images = set()

        for seg in segments:
            if seg['type'] == 'lang_tag':
                pending_lang = seg['content']
                continue

            if seg['type'] == 'code':
                if pending_lang:
                    seg['language'] = pending_lang
                    pending_lang = None
                cleaned.append(seg)

            elif seg['type'] == 'text':
                txt = seg['content'].strip()
                if not txt:
                    continue
                if len(txt) < 30 and ('等待' in txt or 'Generating' in txt):
                    continue
                if len(txt) < 50 and (txt.endswith('复制') or txt.endswith('Copy')):
                    if not pending_lang:
                        detected = txt.replace('复制', '').replace('Copy', '').strip()
                        if detected:
                            pending_lang = detected
                    continue
                tool_feedback_segments = self._split_tool_feedback_text_segment(txt)
                if tool_feedback_segments:
                    cleaned.extend(tool_feedback_segments)
                    continue
                cleaned.append(seg)

            elif seg['type'] == 'image':
                src = seg['content']
                if src in seen_images:
                    continue
                seen_images.add(src)
                cleaned.append(seg)

            else:
                cleaned.append(seg)

        final = []
        if cleaned:
            curr = cleaned[0]
            for j in range(1, len(cleaned)):
                next_seg = cleaned[j]
                if curr['type'] == 'text' and next_seg['type'] == 'text':
                    curr['content'] += next_seg['content']
                else:
                    final.append(curr)
                    curr = next_seg
            final.append(curr)
        return final
