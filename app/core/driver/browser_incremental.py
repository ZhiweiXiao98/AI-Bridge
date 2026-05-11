# filename: app/core/driver/browser_incremental.py
"""
浏览器消息增量提取 —— probe → 结构对比 → 定向提取 → 解析 → 更新缓存。

核心流程：
1. execute_script(CHAT_CONTENT_PROBE) → [{id, ai}, ...] （1 次 IPC，~2KB）
2. 构建 (id, ai) 有序列表 vs 上轮 _last_probe_keys 对比 → has_structural_change
3. 对缓存未命中的索引 execute_script(CHAT_CONTENT_BY_INDEX, [indexes]) （1 次 IPC）
4. BS4 解析变化的元素，更新缓存
5. 组装完整消息列表 + has_structural_change 返回

关键设计：
- 缓存 key = "{message_id}:{role}"，同一 data-message-id 下 User 和 AI 是两条不同消息
- 结构变化 = probe 返回的 [(id, ai), ...] 有序列表与上轮不同
- 不再使用 html_len / raw_len 等内容指纹做命中判断
- 状态机事件驱动缓存失效（通过 cache.invalidate_message()）

依赖：
- browser_js.py: JS 脚本
- browser_cache.py: 缓存管理
- parser.py: DOM 解析
- config.py: SELECTORS
"""

import hashlib
import logging
import re

from bs4 import BeautifulSoup

from .browser_cache import BrowserMessageCache
from .browser_js import (
    BATCH_CHAT_CONTENT,
    CHAT_CONTENT_BY_INDEX,
    CHAT_CONTENT_PROBE,
)
from .config import SELECTORS, SCRIPTS

logger = logging.getLogger(__name__)


def _filter_top_level_nodes(nodes):
    """只保留顶层节点，去除被其他节点包含的子节点。

    场景：WebAI 的 DOM 中 blockquote 的 aa-html-content 嵌套在 markdown-renderer 内，
    两者都会被 content_blocks 选择器匹配，导致 parse_node 对同一文本递归两次。
    只保留外层节点即可——parse_node 会递归处理子元素。
    """
    if len(nodes) <= 1:
        return nodes
    node_ids = set(id(n) for n in nodes)
    top_level = []
    for node in nodes:
        parent = node.parent
        while parent is not None:
            if id(parent) in node_ids:
                break  # 有祖先也在 valid_nodes 中 → 跳过
            parent = parent.parent
        else:
            top_level.append(node)
    return top_level


def parse_single_message(parser, soup, role, is_transient=False):
    """
    解析单条消息的 HTML soup → segments 列表。

    从 get_chat_content() L278-310 提取的公共逻辑。
    parser: DOMParser 实例
    soup: BeautifulSoup 对象（单条消息的 outerHTML）
    role: 'AI' / 'User'
    is_transient: 是否使用 transient 解析路径
    """
    primary_nodes = soup.select('.chat-text')
    all_segments = []
    transient_placeholders = []

    if primary_nodes:
        for node in primary_nodes:
            if is_transient:
                segs, placeholders = parser.parse_browser_transient_message(node)
                all_segments.extend(segs)
                transient_placeholders.extend(placeholders)
            else:
                all_segments.extend(parser.parse_node(node))
    else:
        valid_nodes = soup.find_all(
            class_=lambda x: x and any(
                b in x for b in SELECTORS['content_blocks']
            )
        )
        valid_nodes = _filter_top_level_nodes(valid_nodes)
        if not valid_nodes:
            if is_transient:
                segs, placeholders = parser.parse_browser_transient_message(soup)
                all_segments = list(segs)
                transient_placeholders.extend(placeholders)
            else:
                all_segments = parser.parse_node(soup)
        else:
            for node in valid_nodes:
                if is_transient:
                    segs, placeholders = parser.parse_browser_transient_message(node)
                    all_segments.extend(segs)
                    transient_placeholders.extend(placeholders)
                else:
                    all_segments.extend(parser.parse_node(node))

    final = parser.clean_code_headers(all_segments)
    if is_transient and transient_placeholders:
        final.extend(transient_placeholders)
    return final


def resolve_message_id(item_id, role, raw_text, index):
    """
    确定消息 ID。优先用 DOM 属性，缺失时生成 fallback hash。

    item_id: JS 返回的 id（来自 data-message-id / data-id / id）
    role: 'AI' / 'User'
    raw_text: 消息纯文本（用于 fallback hash）
    index: 元素在列表中的索引
    """
    if item_id:
        return item_id, False

    ts_match = re.search(r'\b\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}\b', raw_text)
    ts_text = ts_match.group(0) if ts_match else ''
    preview = raw_text[:120]
    fallback_source = (
        f"{role}|{ts_text}|{preview}"
        if (ts_text or preview)
        else f"{role}|chat-item-{index}"
    )
    fallback_hash = hashlib.md5(fallback_source.encode('utf-8')).hexdigest()[:8]
    return f"msg_fallback_{fallback_hash}", True


def resolve_role(ai_attr, soup):
    """
    从 data-message-ai 属性或 DOM class 判断角色。
    """
    ai_val = str(ai_attr or '').strip().lower()
    if ai_val == 'true':
        return 'AI'
    if ai_val == 'false':
        return 'User'
    # fallback: 从 class 推断
    first_div = soup.find('div')
    if first_div:
        class_str = ' '.join(first_div.get('class', []))
        if 'user' in class_str or 'human' in class_str:
            return 'User'
    return 'AI'


def stamp_code_blocks(segments, message_id):
    """
    给 code segment 打上 message_id / block_index / block_key / segment_id / content_hash 标记。
    block_key = "{message_id}:{code_index}"，不含内容 fingerprint，保证 AutoFix 后身份稳定。
    segment_id = "seg_{message_id}_code_{code_index}"，全局稳定身份。
    code_fingerprint 保留用于内容变化诊断。
    content_hash = md5(type:content)[:12]，用于 reducer 判断内容是否变化。
    """
    code_index = 0
    for seg in segments:
        if seg.get('type') != 'code':
            continue
        code_content = str(seg.get('content', '') or '')
        code_fp = hashlib.md5(code_content.encode('utf-8')).hexdigest()[:8]
        old_block_key = seg.get('block_key', '')
        seg['message_id'] = message_id
        seg['block_index'] = code_index
        seg['code_fingerprint'] = code_fp
        seg['block_key'] = f"{message_id}:{code_index}"
        seg['segment_id'] = f"seg_{message_id}_code_{code_index}"
        seg['content_hash'] = hashlib.md5(f"code:{code_content}".encode('utf-8')).hexdigest()[:12]
        if old_block_key and str(old_block_key) != seg['block_key']:
            logger.debug("[stamp_code_blocks] block_key变化 | msg=%s | idx=%s | old=%s | new=%s",
                         str(message_id)[:12], code_index, str(old_block_key)[:25], seg['block_key'][:25])
        code_index += 1


def stamp_text_segments(segments, message_id):
    """给 text segment 打上 segment_id 和 content_hash 标记。"""
    text_index = 0
    for seg in segments:
        if seg.get('type') != 'text':
            continue
        content = str(seg.get('content', '') or '')
        seg['segment_id'] = f"seg_{message_id}_text_{text_index}"
        seg['content_hash'] = hashlib.md5(f"text:{content}".encode('utf-8')).hexdigest()[:12]
        text_index += 1


class IncrementalExtractor:
    """
    增量消息提取器。

    持有 BrowserMessageCache，每轮通过 probe → 结构对比 → 定向提取 → 缓存更新
    实现增量同步。

    用法：
        extractor = IncrementalExtractor(parser)
        messages, is_at_bottom, has_structural_change = extractor.extract(driver, interact, transient_last_ai=False)
    """

    def __init__(self, parser):
        self._parser = parser
        self._cache = BrowserMessageCache()
        self._last_probe_keys: list = []
        self._last_content_sigs: dict = {}

    @property
    def cache(self) -> BrowserMessageCache:
        return self._cache

    def clear_cache(self):
        """会话切换时调用。"""
        self._cache.clear()
        self._last_probe_keys = []
        self._last_content_sigs = {}

    def extract(self, driver, interact, transient_last_ai=False):
        """
        增量提取消息。返回 (structured_msgs, is_at_bottom, has_structural_change)。

        has_structural_change:
            True  → probe 返回的 [(id, ai), ...] 有序列表与上轮不同（消息新增/删除/顺序变化）
            False → 结构完全一致，无变化

        流程：
        1. probe 获取 (id, ai) 列表
        2. 与上轮对比判定结构变化
        3. 对缓存未命中的索引定向提取 HTML
        4. 解析 + 更新缓存
        5. 组装完整列表返回

        如果 probe 失败，降级到全量提取。
        """
        try:
            return self._extract_incremental(driver, interact, transient_last_ai)
        except Exception as e:
            logger.warning("[增量提取] 增量模式异常，降级到全量: %s", e)
            return self._extract_full(driver, interact, transient_last_ai)

    def _extract_incremental(self, driver, interact, transient_last_ai):
        """增量提取核心逻辑。"""
        # Step 1: 轻量探测（1 次 IPC，~2KB）
        is_at_bottom = driver.execute_script(SCRIPTS['scroll_check'])
        probe_result = driver.execute_script(CHAT_CONTENT_PROBE)

        if not isinstance(probe_result, list):
            logger.debug("[增量提取] probe 返回非列表，降级全量")
            return self._extract_full(driver, interact, transient_last_ai)

        # Step 2: 构建当前 probe 的 (id, ai) 有序键列表，判定结构变化
        current_probe_keys = []
        current_content_sigs = {}
        for i, item in enumerate(probe_result):
            item_id = str(item.get('id') or '').strip()
            item_ai = str(item.get('ai') or '').strip().lower()
            role = 'AI' if item_ai == 'true' else 'User'
            probe_key = BrowserMessageCache.make_key(item_id, role) if item_id else f"__idx_{i}"
            current_probe_keys.append(probe_key)
            text_len = int(item.get('text_len') or 0)
            html_len = int(item.get('html_len') or 0)
            code_count = int(item.get('code_count') or 0)
            sig = f"{text_len}:{html_len}:{code_count}"
            current_content_sigs[probe_key] = sig

        has_structural_change = (current_probe_keys != self._last_probe_keys)
        self._last_probe_keys = current_probe_keys

        # Step 3: 比对缓存，找出需要提取的索引
        changed_indexes = []
        total = len(probe_result)

        for i, item in enumerate(probe_result):
            item_id = str(item.get('id') or '').strip()
            ai_attr = str(item.get('ai') or '').strip().lower()
            role = 'AI' if ai_attr == 'true' else 'User'

            if item_id:
                cache_key = BrowserMessageCache.make_key(item_id, role)
            else:
                cache_key = f"__idx_{i}"

            cached = self._cache.get(cache_key)
            if cached is None:
                changed_indexes.append(i)
            elif transient_last_ai and role == 'AI' and i == total - 1:
                changed_indexes.append(i)
            else:
                old_sig = self._last_content_sigs.get(cache_key)
                new_sig = current_content_sigs.get(cache_key)
                if old_sig is not None and new_sig is not None and old_sig != new_sig:
                    changed_indexes.append(i)
                    logger.debug(
                        "[增量提取] 内容签名变化 | key=%s | old_sig=%s | new_sig=%s",
                        cache_key[:24], old_sig, new_sig,
                    )

        # 更新顺序
        order_keys = []
        for i, item in enumerate(probe_result):
            item_id = str(item.get('id') or '').strip()
            ai_attr = str(item.get('ai') or '').strip().lower()
            role = 'AI' if ai_attr == 'true' else 'User'
            if item_id:
                order_keys.append(BrowserMessageCache.make_key(item_id, role))
            else:
                order_keys.append(f"__idx_{i}")
        self._cache.update_order(order_keys)

        cache_hits = total - len(changed_indexes)
        if changed_indexes:
            logger.debug(
                "[增量提取] probe=%d 条, 缓存命中=%d, 需提取=%d, 结构变化=%s",
                total, cache_hits, len(changed_indexes), has_structural_change,
            )
        else:
            logger.debug(
                "[增量提取] probe=%d 条, 全部缓存命中, 结构变化=%s",
                total, has_structural_change,
            )
            # 全部命中，直接组装返回
            return self._assemble_from_cache(probe_result, is_at_bottom, has_structural_change)

        # Step 4: 定向提取缓存未命中的元素（1 次 IPC）
        fetched_items = driver.execute_script(
            CHAT_CONTENT_BY_INDEX, changed_indexes
        )
        if not isinstance(fetched_items, list):
            logger.warning("[增量提取] 定向提取返回非列表，降级全量")
            return self._extract_full(driver, interact, transient_last_ai)

        # 建立 idx → fetched_item 的映射
        fetched_map = {}
        for item in fetched_items:
            fetched_map[int(item.get('idx', -1))] = item

        # Step 5: 解析变化的元素，更新缓存
        for i in changed_indexes:
            fetched = fetched_map.get(i)
            if not fetched:
                continue
            parsed = self._parse_and_cache(
                fetched, i, total, probe_result, transient_last_ai
            )
            if parsed:
                item = probe_result[i] if i < len(probe_result) else {}
                item_id = str(item.get('id') or '').strip()
                ai_attr = str(item.get('ai') or '').strip().lower()
                role = 'AI' if ai_attr == 'true' else 'User'
                sig_key = BrowserMessageCache.make_key(item_id, role) if item_id else f"__idx_{i}"
                sig = current_content_sigs.get(sig_key)
                is_streaming_tail = bool(transient_last_ai and role == 'AI' and i == total - 1)
                if sig is not None and not is_streaming_tail:
                    self._last_content_sigs[sig_key] = sig

        # Step 6: 组装完整列表
        return self._assemble_from_cache(probe_result, is_at_bottom, has_structural_change)

    def _parse_and_cache(self, fetched, index, total, probe_result, transient_last_ai):
        """解析单条 fetched 元素并写入缓存。"""
        html = str(fetched.get('html') or '')
        item_id = str(fetched.get('id') or '').strip()
        ai_attr = str(fetched.get('ai') or '').strip()

        if not html:
            return False

        soup = BeautifulSoup(html, 'html.parser')
        role = resolve_role(ai_attr, soup)

        # 提取纯文本用于 fallback id
        raw_text = soup.get_text(separator=' ', strip=True)[:200]

        # 确定 message_id
        message_id, is_fallback = resolve_message_id(
            item_id, role, raw_text, index
        )
        if is_fallback:
            logger.debug(
                "[增量提取] 消息缺少 data-message-id | index=%d | role=%s | fallback_id=%s",
                index, role, message_id,
            )

        # cache_key = message_id:role
        cache_key = BrowserMessageCache.make_key(message_id, role)
        # fallback 情况用 index 兜底
        if not item_id:
            cache_key = f"__idx_{index}"

        # 判断是否用 transient 解析
        is_transient = bool(
            transient_last_ai and role == 'AI' and index == total - 1
        )


        # 解析 segments
        segments = parse_single_message(
            self._parser, soup, role, is_transient=is_transient
        )
        if not segments:
            return False

        # 给 code segment 打标记
        stamp_code_blocks(segments, message_id)
        stamp_text_segments(segments, message_id)

        # 写入缓存（不再传 html_len）
        self._cache.put(
            cache_key, message_id, role, segments, raw_len=len(html)
        )
        return True

    def _assemble_from_cache(self, probe_result, is_at_bottom, has_structural_change):
        """从缓存组装完整消息列表。"""
        structured_msgs = []
        for i, item in enumerate(probe_result):
            item_id = str(item.get('id') or '').strip()
            ai_attr = str(item.get('ai') or '').strip().lower()
            role = 'AI' if ai_attr == 'true' else 'User'

            if item_id:
                cache_key = BrowserMessageCache.make_key(item_id, role)
            else:
                cache_key = f"__idx_{i}"

            cached = self._cache.get(cache_key)
            if cached is None:
                continue
            structured_msgs.append({
                'id': cached.message_id,
                'role': cached.role,
                'segments': cached.segments,
                'raw_len': cached.raw_len,
            })
        return structured_msgs, is_at_bottom, has_structural_change

    def _extract_full(self, driver, interact, transient_last_ai):
        """
        全量提取（降级路径 / 首次加载 / 会话切换）。
        用 BATCH_CHAT_CONTENT 一次 IPC 获取所有元素。
        """
        is_at_bottom = driver.execute_script(SCRIPTS['scroll_check'])
        batch_result = driver.execute_script(BATCH_CHAT_CONTENT)

        if not isinstance(batch_result, list):
            logger.warning("[全量提取] batch 返回非列表")
            return [], False, True  # 全量提取视为有结构变化

        self._cache.clear()
        total = len(batch_result)
        structured_msgs = []
        fallback_count = 0

        # 构建 probe_keys（全量提取后用于后续增量对比）
        probe_keys = []

        for i, item in enumerate(batch_result):
            html = str(item.get('html') or '')
            item_id = str(item.get('id') or '').strip()
            ai_attr = str(item.get('ai') or '').strip()

            if not html:
                continue

            soup = BeautifulSoup(html, 'html.parser')
            role = resolve_role(ai_attr, soup)
            raw_text = soup.get_text(separator=' ', strip=True)[:200]

            message_id, is_fallback = resolve_message_id(
                item_id, role, raw_text, i
            )
            if is_fallback:
                fallback_count += 1

            # cache_key
            if item_id:
                cache_key = BrowserMessageCache.make_key(message_id, role)
            else:
                cache_key = f"__idx_{i}"
            probe_keys.append(cache_key)

            is_transient = bool(
                transient_last_ai and role == 'AI' and i == total - 1
            )
            segments = parse_single_message(
                self._parser, soup, role, is_transient=is_transient
            )
            if not segments:
                continue

            stamp_code_blocks(segments, message_id)
            stamp_text_segments(segments, message_id)

            self._cache.put(
                cache_key, message_id, role, segments, raw_len=len(html)
            )
            structured_msgs.append({
                'id': message_id,
                'role': role,
                'segments': segments,
                'raw_len': len(html),
            })

        # 更新顺序和 probe_keys
        self._cache.update_order(probe_keys)
        self._last_probe_keys = []
        for i, item in enumerate(batch_result):
            if not str(item.get('html') or ''):
                continue
            item_id = str(item.get('id') or '').strip()
            role = 'AI' if str(item.get('ai') or '').strip().lower() == 'true' else 'User'
            self._last_probe_keys.append(
                BrowserMessageCache.make_key(item_id, role) if item_id else f"__idx_{i}"
            )
        self._last_content_sigs = {}
        for i, item in enumerate(batch_result):
            html = str(item.get('html') or '')
            item_id = str(item.get('id') or '').strip()
            if not html:
                continue
            soup_tmp = BeautifulSoup(html, 'html.parser')
            role = resolve_role(str(item.get('ai') or '').strip(), soup_tmp)
            is_streaming_tail = bool(
                transient_last_ai and role == 'AI' and i == total - 1
            )
            if is_streaming_tail:
                continue
            text_len = len(soup_tmp.get_text() or '')
            code_count = len(soup_tmp.find_all('code'))
            sig_key = BrowserMessageCache.make_key(item_id, role) if item_id else f"__idx_{i}"
            self._last_content_sigs[sig_key] = f"{text_len}:{len(html)}:{code_count}"

        if fallback_count > 0:
            logger.debug(
                "[全量提取] %d 条消息缺少 data-message-id", fallback_count
            )
        logger.debug(
            "[全量提取] 完成 | 消息=%d | 缓存=%d",
            len(structured_msgs), self._cache.size,
        )
        return structured_msgs, is_at_bottom, True  # 全量提取视为有结构变化
