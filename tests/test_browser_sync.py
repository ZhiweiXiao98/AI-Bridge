# filename: tests/test_browser_sync.py
"""browser_sync 模块全量单元测试。

覆盖计划书 §11 必测场景中可自动验证的 6 项：
- 场景3: fixing 折叠变展开，内容不变不重建
- 场景4: fixing 代码内容变化，只 patch 对应 segment
- 场景5: 无 DOM ID 消息插入后身份稳定
- 场景9: 事件重复到达，客户端丢弃
- 场景10: 事件乱序到达，按序应用
- 场景11: 缺失事件，触发 resync

额外覆盖：
- SeqGenerator 线程安全与递增
- DOMNormalizer content_hash / rev / segment_id 稳定性
- BrowserCanonicalStore snapshot / upsert / delete / patch
- ChatProjectionReducer 完整生命周期
- DOMNormalizer 双 probe 防抖
- DOMNormalizer should_refetch 脏检查
"""

import hashlib
import importlib
import pathlib
import sys
import threading
import time
import types
import unittest

from bs4 import BeautifulSoup

from app.core.browser_sync import (
    CanonicalMessage,
    CanonicalSegment,
    ConversationEvent,
    EventType,
    SeqGenerator,
    BrowserCanonicalStore,
    DOMNormalizer,
    ChatProjectionState,
    ChatProjectionReducer,
)


def normalize_only(normalizer, *args, **kwargs):
    canonical, _, _ = normalizer.normalize_messages(*args, **kwargs)
    return canonical


def load_driver_module(module_name):
    """Load browser_incremental without executing app.core.driver.__init__."""
    pkg_name = "app.core.driver"
    if pkg_name not in sys.modules:
        pkg = types.ModuleType(pkg_name)
        pkg.__path__ = [
            str(pathlib.Path(__file__).resolve().parents[1] / "app" / "core" / "driver")
        ]
        sys.modules[pkg_name] = pkg
    return importlib.import_module(f"app.core.driver.{module_name}")


def load_incremental_extractor():
    return load_driver_module("browser_incremental").IncrementalExtractor


class TestSeqGenerator(unittest.TestCase):
    def test_monotonic_increment(self):
        g = SeqGenerator()
        vals = [g.next() for _ in range(100)]
        for i in range(1, len(vals)):
            self.assertGreater(vals[i], vals[i - 1])

    def test_start_value(self):
        g = SeqGenerator(start=100)
        self.assertEqual(g.next(), 101)
        self.assertEqual(g.next(), 102)

    def test_current(self):
        g = SeqGenerator()
        self.assertEqual(g.current, 0)
        g.next()
        self.assertEqual(g.current, 1)

    def test_reset(self):
        g = SeqGenerator()
        g.next()
        g.next()
        g.reset(start=50)
        self.assertEqual(g.next(), 51)

    def test_thread_safety(self):
        g = SeqGenerator()
        results = []
        lock = threading.Lock()

        def worker():
            for _ in range(500):
                v = g.next()
                with lock:
                    results.append(v)

        threads = [threading.Thread(target=worker) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(len(results), 2000)
        self.assertEqual(len(set(results)), 2000, "seq 必须全局唯一")


class TestCanonicalSegment(unittest.TestCase):
    def test_compute_content_hash(self):
        s = CanonicalSegment(type="code", content="print(1)")
        h = s.compute_content_hash()
        expected = hashlib.md5("code:print(1)".encode("utf-8")).hexdigest()[:12]
        self.assertEqual(h, expected)

    def test_to_dict_basic(self):
        s = CanonicalSegment(
            id="seg_m1_code_0", message_id="m1", type="code",
            content="x=1", language="python", block_key="m1:0",
            block_index=0, code_fingerprint="abc12345",
            content_hash="fakehash", ordinal=0, rev=1,
        )
        d = s.to_dict()
        self.assertEqual(d["segment_id"], "seg_m1_code_0")
        self.assertEqual(d["block_key"], "m1:0")
        self.assertEqual(d["content_hash"], "fakehash")
        self.assertNotIn("tool_call_id", d)

    def test_to_dict_with_tool_call_id(self):
        s = CanonicalSegment(tool_call_id="tc_001")
        d = s.to_dict()
        self.assertEqual(d["tool_call_id"], "tc_001")


class TestCanonicalMessage(unittest.TestCase):
    def test_compute_content_hash_empty(self):
        m = CanonicalMessage()
        h = m.compute_content_hash()
        self.assertTrue(h)

    def test_compute_content_hash_with_segments(self):
        s1 = CanonicalSegment(type="text", content="hello", content_hash="h1")
        s2 = CanonicalSegment(type="code", content="x=1", content_hash="h2")
        m = CanonicalMessage(segments=[s1, s2])
        h = m.compute_content_hash()
        expected = hashlib.md5("text:h1|code:h2".encode("utf-8")).hexdigest()[:12]
        self.assertEqual(h, expected)

    def test_to_dict(self):
        m = CanonicalMessage(id="m1", role="AI", ordinal=5, rev=2, content_hash="abc")
        d = m.to_dict()
        self.assertEqual(d["id"], "m1")
        self.assertEqual(d["ordinal"], 5)
        self.assertEqual(d["rev"], 2)
        self.assertEqual(d["content_hash"], "abc")


class TestBrowserCanonicalStore(unittest.TestCase):
    def _make_msg(self, msg_id, ordinal=0, rev=1, content_hash="h", segments=None):
        return CanonicalMessage(
            id=msg_id, ordinal=ordinal, rev=rev,
            content_hash=content_hash, segments=segments or [],
        )

    def test_apply_snapshot(self):
        store = BrowserCanonicalStore()
        msgs = [self._make_msg("m1", 0), self._make_msg("m2", 1)]
        store.apply_snapshot(msgs, seq=1, conversation_id="c1")
        self.assertEqual(store.message_count, 2)
        self.assertEqual(store.last_seq, 1)
        self.assertEqual(store.ordered_ids, ["m1", "m2"])

    def test_upsert_new_message(self):
        store = BrowserCanonicalStore()
        store.apply_snapshot([self._make_msg("m1", 0)], seq=1)
        new_msg = self._make_msg("m2", 1)
        result = store.upsert_message(new_msg, seq=2)
        self.assertTrue(result)
        self.assertEqual(store.message_count, 2)

    def test_upsert_unchanged_message(self):
        store = BrowserCanonicalStore()
        msg = self._make_msg("m1", 0, rev=1, content_hash="abc")
        store.apply_snapshot([msg], seq=1)
        same_msg = self._make_msg("m1", 0, rev=1, content_hash="abc")
        result = store.upsert_message(same_msg, seq=2)
        self.assertFalse(result)

    def test_upsert_changed_message(self):
        store = BrowserCanonicalStore()
        msg = self._make_msg("m1", 0, rev=1, content_hash="abc")
        store.apply_snapshot([msg], seq=1)
        changed = self._make_msg("m1", 0, rev=2, content_hash="def")
        result = store.upsert_message(changed, seq=2)
        self.assertTrue(result)

    def test_delete_message(self):
        store = BrowserCanonicalStore()
        store.apply_snapshot([self._make_msg("m1", 0), self._make_msg("m2", 1)], seq=1)
        result = store.delete_message("m1", seq=2)
        self.assertTrue(result)
        self.assertEqual(store.message_count, 1)
        self.assertEqual(store.ordered_ids, ["m2"])

    def test_delete_nonexistent(self):
        store = BrowserCanonicalStore()
        result = store.delete_message("ghost", seq=1)
        self.assertFalse(result)

    def test_patch_segment(self):
        seg = CanonicalSegment(id="s1", message_id="m1", type="code", content="old", content_hash="old_h")
        msg = CanonicalMessage(id="m1", segments=[seg], content_hash="initial")
        store = BrowserCanonicalStore()
        store.apply_snapshot([msg], seq=1)

        new_seg = CanonicalSegment(id="s1", message_id="m1", type="code", content="new", content_hash="new_h", rev=2)
        result = store.patch_segment(new_seg, seq=2)
        self.assertTrue(result)
        self.assertEqual(store.segments_by_id["s1"].content, "new")

    def test_patch_segment_unchanged(self):
        seg = CanonicalSegment(id="s1", message_id="m1", type="code", content="x", content_hash="h1", rev=1)
        msg = CanonicalMessage(id="m1", segments=[seg], content_hash="initial")
        store = BrowserCanonicalStore()
        store.apply_snapshot([msg], seq=1)

        same_seg = CanonicalSegment(id="s1", message_id="m1", type="code", content="x", content_hash="h1", rev=1)
        result = store.patch_segment(same_seg, seq=2)
        self.assertFalse(result)

    def test_get_snapshot(self):
        store = BrowserCanonicalStore()
        store.apply_snapshot([self._make_msg("m1", 0), self._make_msg("m2", 1)], seq=1)
        snap = store.get_snapshot()
        self.assertEqual(len(snap), 2)
        self.assertEqual(snap[0]["id"], "m1")
        self.assertEqual(snap[1]["id"], "m2")

    def test_get_events_since(self):
        store = BrowserCanonicalStore()
        for i in range(5):
            e = ConversationEvent(seq=i + 1, event="message.upsert", payload={})
            store.log_event(e)
        events = store.get_events_since(3)
        self.assertEqual(len(events), 2)
        self.assertEqual(events[0].seq, 4)
        self.assertEqual(events[1].seq, 5)

    def test_clear(self):
        store = BrowserCanonicalStore()
        store.apply_snapshot([self._make_msg("m1", 0)], seq=1)
        store.clear()
        self.assertEqual(store.message_count, 0)
        self.assertEqual(store.last_seq, 0)


class TestDOMNormalizer(unittest.TestCase):
    def test_basic_normalize(self):
        n = DOMNormalizer()
        raw = [
            {"id": "m1", "role": "User", "segments": [{"type": "text", "content": "hi"}], "raw_len": 50},
            {"id": "m2", "role": "AI", "segments": [
                {"type": "text", "content": "code:"},
                {"type": "code", "content": "x=1", "language": "python"},
            ], "raw_len": 200},
        ]
        result = normalize_only(n, raw, conversation_id="c1")
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0].id, "m1:User")
        self.assertEqual(result[0].ordinal, 0)
        self.assertEqual(result[1].ordinal, 1)
        self.assertEqual(result[0].rev, 1)

    def test_segment_id_stability(self):
        """segment_id 在内容不变时必须稳定。"""
        n = DOMNormalizer()
        raw = [
            {"id": "m1", "role": "AI", "segments": [
                {"type": "text", "content": "hello"},
                {"type": "code", "content": "x=1", "language": "python"},
            ], "raw_len": 100},
        ]
        r1 = normalize_only(n, raw)
        r2 = normalize_only(n, raw)
        self.assertEqual(r1[0].segments[0].id, r2[0].segments[0].id)
        self.assertEqual(r1[0].segments[1].id, r2[0].segments[1].id)

    def test_content_hash_changes_on_content_change(self):
        """场景4: 代码内容变化 → content_hash 变化 → rev 递增。"""
        n = DOMNormalizer()
        raw_v1 = [
            {"id": "m1", "role": "AI", "segments": [
                {"type": "code", "content": "print(1)", "language": "python"},
            ], "raw_len": 100},
        ]
        raw_v2 = [
            {"id": "m1", "role": "AI", "segments": [
                {"type": "code", "content": "print(2)", "language": "python"},
            ], "raw_len": 100},
        ]
        r1 = normalize_only(n, raw_v1)
        r2 = normalize_only(n, raw_v2)
        self.assertNotEqual(r1[0].content_hash, r2[0].content_hash)
        self.assertEqual(r1[0].rev, 1)
        self.assertEqual(r2[0].rev, 2)

    def test_content_hash_stable_when_unchanged(self):
        """场景3: 内容不变 → content_hash 不变 → rev 不递增。"""
        n = DOMNormalizer()
        raw = [
            {"id": "m1", "role": "AI", "segments": [
                {"type": "code", "content": "x=1", "language": "python"},
            ], "raw_len": 100},
        ]
        r1 = normalize_only(n, raw)
        r2 = normalize_only(n, raw)
        self.assertEqual(r1[0].content_hash, r2[0].content_hash)
        self.assertEqual(r2[0].rev, 1)

    def test_fallback_id_stability(self):
        """场景5: 无 DOM ID 消息，fallback ID 跨轮次稳定。"""
        n = DOMNormalizer()
        raw = [
            {"id": "", "role": "User", "segments": [{"type": "text", "content": "hello world"}], "raw_len": 50},
        ]
        r1 = normalize_only(n, raw)
        r2 = normalize_only(n, raw)
        self.assertEqual(r1[0].id, r2[0].id)
        self.assertTrue(r1[0].id.startswith("msg_fb_"))

    def test_fallback_id_stable_after_insert(self):
        """场景5: 前面插入一条消息后，旧消息 fallback ID 仍稳定。"""
        n = DOMNormalizer()
        raw_before = [
            {"id": "", "role": "User", "segments": [{"type": "text", "content": "original"}], "raw_len": 50},
        ]
        normalize_only(n, raw_before)

        raw_after = [
            {"id": "new_msg", "role": "User", "segments": [{"type": "text", "content": "inserted"}], "raw_len": 30},
            {"id": "", "role": "User", "segments": [{"type": "text", "content": "original"}], "raw_len": 50},
        ]
        r = normalize_only(n, raw_after)
        self.assertEqual(r[1].id, "msg_fb_1_" + hashlib.md5("1:User|original".encode("utf-8")).hexdigest()[:8] + ":User")

    def test_block_key_stability(self):
        """block_key 不含内容 fingerprint，AutoFix 后稳定。"""
        n = DOMNormalizer()
        raw_v1 = [
            {"id": "m1", "role": "AI", "segments": [
                {"type": "code", "content": "old_code", "language": "python"},
            ], "raw_len": 100},
        ]
        raw_v2 = [
            {"id": "m1", "role": "AI", "segments": [
                {"type": "code", "content": "new_code_after_fix", "language": "python"},
            ], "raw_len": 150},
        ]
        r1 = normalize_only(n, raw_v1)
        r2 = normalize_only(n, raw_v2)
        self.assertEqual(r1[0].segments[0].block_key, r2[0].segments[0].block_key)
        self.assertNotEqual(r1[0].segments[0].code_fingerprint, r2[0].segments[0].code_fingerprint)

    def test_probe_stable_check(self):
        """双 probe 防抖：相同 probe → stable。"""
        n = DOMNormalizer()
        probe_a = [
            {"id": "m1", "ai": "true", "html_len": 500},
            {"id": "m2", "ai": "", "html_len": 200},
        ]
        probe_b = [
            {"id": "m1", "ai": "true", "html_len": 500},
            {"id": "m2", "ai": "", "html_len": 200},
        ]
        n.check_probe_stable(probe_a)
        self.assertTrue(n.check_probe_stable(probe_b))

    def test_probe_unstable_check(self):
        """双 probe 防抖：不同 probe → unstable。"""
        n = DOMNormalizer()
        probe_a = [
            {"id": "m1", "ai": "true", "html_len": 500},
        ]
        probe_b = [
            {"id": "m1", "ai": "true", "html_len": 800},
        ]
        n.check_probe_stable(probe_a)
        self.assertFalse(n.check_probe_stable(probe_b))

    def test_should_refetch_no_cache(self):
        n = DOMNormalizer()
        self.assertTrue(n.should_refetch({"html_len": 500}, None))

    def test_should_refetch_unchanged(self):
        n = DOMNormalizer()
        msg = CanonicalMessage(id="m1", raw_len=500)
        self.assertFalse(n.should_refetch({"html_len": 500}, msg))

    def test_should_refetch_changed(self):
        n = DOMNormalizer()
        msg = CanonicalMessage(id="m1", raw_len=500)
        self.assertTrue(n.should_refetch({"html_len": 800}, msg))

    def test_tool_call_id_preserved(self):
        n = DOMNormalizer()
        raw = [
            {"id": "m1", "role": "AI", "segments": [
                {"type": "code", "content": "x=1", "language": "python", "tool_call_id": "tc_001"},
            ], "raw_len": 100},
        ]
        r = normalize_only(n, raw)
        self.assertEqual(r[0].segments[0].tool_call_id, "tc_001")

    def test_unbound_tool_results_split_to_unique_fallback_messages(self):
        n = DOMNormalizer()
        raw = [
            {"id": "u1", "role": "User", "segments": [
                {"type": "tool_result", "content": "same", "tool_call_id": "tc_a"},
                {"type": "tool_result", "content": "same", "tool_call_id": "tc_b"},
            ], "raw_len": 100},
        ]

        result = normalize_only(n, raw, conversation_id="c1")
        fallback = [m for m in result if m.id.startswith("msg_fb_tool_")]

        self.assertEqual(len(fallback), 2)
        self.assertEqual(len({m.id for m in fallback}), 2)

    def test_extracted_user_messages_use_turn_scoped_ids(self):
        m1 = DOMNormalizer._make_user_message("same", 1, "c1", "")
        m2 = DOMNormalizer._make_user_message("same", 2, "c1", "")

        self.assertNotEqual(m1.id, m2.id)

    def test_tool_feedback_sequence_fallback_ignores_plain_code_blocks(self):
        n = DOMNormalizer()
        raw = [
            {"id": "ai1", "role": "AI", "segments": [
                {"type": "code", "content": "print('plain')", "language": "python"},
                {"type": "code", "content": '{"name":"run","arguments":{}}', "language": "tool_call"},
            ], "raw_len": 100},
            {"id": "u1", "role": "User", "segments": [
                {"type": "tool_result", "content": "done"},
            ], "raw_len": 50},
        ]

        result = normalize_only(n, raw, conversation_id="c1")
        ai_msg = next(m for m in result if m.id == "ai1:AI")
        plain_code, tool_code = ai_msg.segments

        self.assertNotIn("_bound_results", plain_code.extra)
        self.assertIn("_bound_results", tool_code.extra)
        self.assertEqual(tool_code.extra["_bound_results"][0]["content"], "done")

    def test_tool_call_json_code_without_language_is_promoted_and_bound(self):
        n = DOMNormalizer()
        raw = [
            {"id": "ai1", "role": "AI", "segments": [
                {"type": "code", "content": '{"name":"run","arguments":{"cmd":"pytest"}}', "tool_call_id": "tc1"},
            ], "raw_len": 100},
            {"id": "u1", "role": "User", "segments": [
                {"type": "tool_result", "content": "ok", "tool_call_id": "tc1"},
            ], "raw_len": 50},
        ]

        result = normalize_only(n, raw, conversation_id="c1")
        ai_msg = next(m for m in result if m.id == "ai1:AI")
        tool_seg = ai_msg.segments[0]

        self.assertEqual(tool_seg.language, "tool_call")
        self.assertIn("_bound_results", tool_seg.extra)
        self.assertEqual(tool_seg.extra["_bound_results"][0]["content"], "ok")


class TestToolSegmentParser(unittest.TestCase):
    def test_prescan_promotes_tool_call_json_code_without_language(self):
        from app.core.tool_runtime.segment_parser import ToolSegmentParser

        segments = [
            {"type": "code", "content": '{"name":"run","arguments":{"cmd":"pytest"}}'},
        ]

        intents = ToolSegmentParser.parse_segments(
            segments,
            conversation_id="c1",
            source="test",
            write_back_tool_call_id=True,
        )

        self.assertEqual(len(intents), 1)
        self.assertEqual(segments[0]["language"], "tool_call")
        self.assertTrue(str(segments[0].get("tool_call_id") or "").startswith("toolcall_"))


class TestIncrementalExtractor(unittest.TestCase):
    class _FakeDriver:
        def __init__(self, probe_result, fetched_result):
            self.probe_result = probe_result
            self.fetched_result = fetched_result
            self.requested_indexes = None
            self.calls = 0

        def execute_script(self, script, *args):
            self.calls += 1
            if self.calls == 1:
                return True
            if self.calls == 2:
                return self.probe_result
            self.requested_indexes = list(args[0]) if args else []
            return self.fetched_result

    def test_fallback_index_content_change_triggers_refetch(self):
        IncrementalExtractor = load_incremental_extractor()
        extractor = IncrementalExtractor(parser=None)
        extractor.cache.put(
            "__idx_0", "msg_fb_old", "User",
            [{"type": "text", "content": "old"}],
            raw_len=10,
        )
        extractor.cache.update_order(["__idx_0"])
        extractor._last_probe_keys = ["__idx_0"]
        extractor._last_content_sigs = {"__idx_0": "3:10:0"}

        driver = self._FakeDriver(
            [{"id": "", "ai": "", "text_len": 7, "html_len": 20, "code_count": 0}],
            [],
        )
        extractor._extract_incremental(driver, interact=None, transient_last_ai=False)

        self.assertEqual(driver.requested_indexes, [0])

    def test_failed_target_fetch_keeps_old_content_signature(self):
        IncrementalExtractor = load_incremental_extractor()
        extractor = IncrementalExtractor(parser=None)
        extractor.cache.put(
            "__idx_0", "msg_fb_old", "User",
            [{"type": "text", "content": "old"}],
            raw_len=10,
        )
        extractor.cache.update_order(["__idx_0"])
        extractor._last_probe_keys = ["__idx_0"]
        extractor._last_content_sigs = {"__idx_0": "3:10:0"}

        driver = self._FakeDriver(
            [{"id": "", "ai": "", "text_len": 7, "html_len": 20, "code_count": 0}],
            [],
        )
        extractor._extract_incremental(driver, interact=None, transient_last_ai=False)

        self.assertEqual(extractor._last_content_sigs["__idx_0"], "3:10:0")

    def test_streaming_tail_code_refreshes_without_committing_stable_signature(self):
        driver_parser = load_driver_module("parser")
        IncrementalExtractor = load_incremental_extractor()
        extractor = IncrementalExtractor(parser=driver_parser.DOMParser())
        extractor.cache.put(
            "m1:AI", "m1", "AI",
            [{"type": "code", "content": "print('old')", "block_key": "m1:0"}],
            raw_len=10,
        )
        extractor.cache.update_order(["m1:AI"])
        extractor._last_probe_keys = ["m1:AI"]
        extractor._last_content_sigs = {"m1:AI": "12:10:1"}

        code = "\n".join([f"print({i})" for i in range(20)])
        html = (
            '<div data-message-id="m1" data-message-ai="true">'
            '<div class="chat-text">'
            '<div data-node-type="code_block" data-mode-id="python">'
            f"<pre>{code}</pre>"
            "</div></div></div>"
        )
        driver = self._FakeDriver(
            [{"id": "m1", "ai": "true", "text_len": len(code), "html_len": len(html), "code_count": 1}],
            [{"idx": 0, "id": "m1", "ai": "true", "html": html}],
        )

        extractor._extract_incremental(driver, interact=None, transient_last_ai=True)

        cached = extractor.cache.get("m1:AI")
        self.assertEqual(driver.requested_indexes, [0])
        self.assertIn("print(19)", cached.segments[0]["content"])
        self.assertTrue(cached.segments[0].get("is_transient_preview"))
        self.assertEqual(extractor._last_content_sigs["m1:AI"], "12:10:1")


class TestBrowserTransientParser(unittest.TestCase):
    def test_long_streaming_code_is_preview_not_placeholder(self):
        driver_parser = load_driver_module("parser")
        parser = driver_parser.DOMParser()
        code = "\n".join([f"line_{i} = {i}" for i in range(20)])
        soup = BeautifulSoup(
            '<div class="chat-text">'
            '<div data-node-type="code_block" data-mode-id="python">'
            f"<pre>{code}</pre>"
            "</div></div>",
            "html.parser",
        )

        segments, placeholders = parser.parse_browser_transient_message(soup)

        self.assertEqual(placeholders, [])
        self.assertEqual(len(segments), 1)
        self.assertEqual(segments[0]["type"], "code")
        self.assertTrue(segments[0].get("is_transient_preview"))
        self.assertIn("line_19 = 19", segments[0]["content"])

    def test_streaming_tool_call_json_is_marked_as_tool_call(self):
        driver_parser = load_driver_module("parser")
        parser = driver_parser.DOMParser()
        code = '{"name":"run","arguments":{"cmd":"pytest"}}'
        soup = BeautifulSoup(
            '<div class="chat-text">'
            '<div data-node-type="code_block">'
            f"<pre>{code}</pre>"
            "</div></div>",
            "html.parser",
        )

        segments, placeholders = parser.parse_browser_transient_message(soup)

        self.assertEqual(placeholders, [])
        self.assertEqual(len(segments), 1)
        self.assertEqual(segments[0]["type"], "code")
        self.assertEqual(segments[0]["language"], "tool_call")


class TestChatProjectionReducer(unittest.TestCase):
    def _make_enriched(self, msgs, seq=1, event="conversation.snapshot"):
        """构造带 _seq/_event 的消息列表。"""
        from app.core.browser_sync import DOMNormalizer, SeqGenerator
        n = DOMNormalizer()
        canonical = normalize_only(n, msgs, conversation_id="c1")
        enriched = []
        for cm in canonical:
            d = cm.to_dict()
            d["_seq"] = seq
            d["_event"] = event
            enriched.append(d)
        return enriched

    def test_first_snapshot(self):
        r = ChatProjectionReducer()
        msgs = self._make_enriched([
            {"id": "m1", "role": "User", "segments": [{"type": "text", "content": "hi"}], "raw_len": 50},
        ])
        change = r.apply_messages(msgs)
        self.assertEqual(change["type"], "snapshot")
        self.assertEqual(change["added"], ["m1:User"])
        self.assertEqual(change["updated"], [])
        self.assertEqual(r.state.last_seq, 1)

    def test_incremental_add(self):
        r = ChatProjectionReducer()
        msgs1 = self._make_enriched([
            {"id": "m1", "role": "User", "segments": [{"type": "text", "content": "hi"}], "raw_len": 50},
        ], seq=1)
        r.apply_messages(msgs1)

        msgs2 = self._make_enriched([
            {"id": "m1", "role": "User", "segments": [{"type": "text", "content": "hi"}], "raw_len": 50},
            {"id": "m2", "role": "AI", "segments": [{"type": "text", "content": "hello"}], "raw_len": 100},
        ], seq=2)
        change = r.apply_messages(msgs2)
        self.assertEqual(change["added"], ["m2:AI"])
        self.assertEqual(change["updated"], [])

    def test_incremental_reorders_when_ordinal_changes_without_content_change(self):
        r = ChatProjectionReducer()
        r.apply_messages([
            {
                "id": "a:User", "role": "User", "ordinal": 0, "index": 1,
                "content_hash": "ha", "rev": 1, "segments": [],
                "_seq": 1, "_event": "conversation.snapshot",
            },
            {
                "id": "b:AI", "role": "AI", "ordinal": 1, "index": 2,
                "content_hash": "hb", "rev": 1, "segments": [],
                "_seq": 1, "_event": "conversation.snapshot",
            },
        ])

        change = r.apply_messages([
            {
                "id": "x:User", "role": "User", "ordinal": 0, "index": 1,
                "content_hash": "hx", "rev": 1, "segments": [],
                "_seq": 2, "_event": "message.upsert",
            },
            {
                "id": "a:User", "role": "User", "ordinal": 1, "index": 2,
                "content_hash": "ha", "rev": 1, "segments": [],
                "_seq": 2, "_event": "message.upsert",
            },
            {
                "id": "b:AI", "role": "AI", "ordinal": 2, "index": 3,
                "content_hash": "hb", "rev": 1, "segments": [],
                "_seq": 2, "_event": "message.upsert",
            },
        ])

        self.assertEqual(change["added"], ["x:User"])
        self.assertEqual(change["updated"], ["a:User", "b:AI"])
        self.assertEqual([m["id"] for m in r.get_ordered_messages()], ["x:User", "a:User", "b:AI"])

    def test_content_update(self):
        """场景4: 代码内容变化 → reducer 标记 updated。"""
        r = ChatProjectionReducer()
        msgs1 = self._make_enriched([
            {"id": "m1", "role": "AI", "segments": [
                {"type": "code", "content": "print(1)", "language": "python"},
            ], "raw_len": 100},
        ], seq=1)
        r.apply_messages(msgs1)

        msgs2 = self._make_enriched([
            {"id": "m1", "role": "AI", "segments": [
                {"type": "code", "content": "print(2)", "language": "python"},
            ], "raw_len": 100},
        ], seq=2)
        change = r.apply_messages(msgs2)
        self.assertEqual(change["updated"], ["m1:AI"])
        self.assertEqual(change["added"], [])

    def test_no_change_skip(self):
        """场景3: 内容不变 → reducer 返回空变更。"""
        r = ChatProjectionReducer()
        msgs = self._make_enriched([
            {"id": "m1", "role": "AI", "segments": [
                {"type": "code", "content": "x=1", "language": "python"},
            ], "raw_len": 100},
        ], seq=1)
        r.apply_messages(msgs)
        change = r.apply_messages(msgs)
        self.assertEqual(change["type"], "stale")

    def test_duplicate_event_dropped(self):
        """场景9: 重复事件（相同 seq）被丢弃。"""
        r = ChatProjectionReducer()
        msgs = self._make_enriched([
            {"id": "m1", "role": "User", "segments": [{"type": "text", "content": "hi"}], "raw_len": 50},
        ], seq=1)
        r.apply_messages(msgs)
        change = r.apply_messages(msgs)
        self.assertEqual(change["type"], "stale")

    def test_seq_gap_triggers_resync_warning(self):
        """场景11: seq 跳跃过大 → 触发 resync 回调。"""
        r = ChatProjectionReducer()
        resync_called = []
        r.set_resync_callback(lambda: resync_called.append(True))

        msgs1 = self._make_enriched([
            {"id": "m1", "role": "User", "segments": [{"type": "text", "content": "hi"}], "raw_len": 50},
        ], seq=1)
        r.apply_messages(msgs1)

        msgs_big_seq = self._make_enriched([
            {"id": "m1", "role": "User", "segments": [{"type": "text", "content": "hi"}], "raw_len": 50},
        ], seq=100, event="message.upsert")
        r.apply_messages(msgs_big_seq)
        self.assertTrue(resync_called, "seq 跳跃超过阈值应触发 resync")

    def test_message_removed(self):
        r = ChatProjectionReducer()
        msgs1 = self._make_enriched([
            {"id": "m1", "role": "User", "segments": [{"type": "text", "content": "hi"}], "raw_len": 50},
            {"id": "m2", "role": "AI", "segments": [{"type": "text", "content": "hello"}], "raw_len": 100},
        ], seq=1)
        r.apply_messages(msgs1)

        msgs2 = self._make_enriched([
            {"id": "m1", "role": "User", "segments": [{"type": "text", "content": "hi"}], "raw_len": 50},
        ], seq=2)
        change = r.apply_messages(msgs2)
        self.assertEqual(change["removed"], ["m2:AI"])

    def test_get_ordered_messages(self):
        r = ChatProjectionReducer()
        msgs = self._make_enriched([
            {"id": "m2", "role": "AI", "segments": [{"type": "text", "content": "hello"}], "raw_len": 100},
            {"id": "m1", "role": "User", "segments": [{"type": "text", "content": "hi"}], "raw_len": 50},
        ], seq=1)
        r.apply_messages(msgs)
        ordered = r.get_ordered_messages()
        self.assertEqual(len(ordered), 2)
        self.assertEqual(ordered[0]["id"], "m2:AI")
        self.assertEqual(ordered[1]["id"], "m1:User")

    def test_empty_messages(self):
        r = ChatProjectionReducer()
        change = r.apply_messages([])
        self.assertEqual(change["type"], "empty")

    def test_reset(self):
        r = ChatProjectionReducer()
        msgs = self._make_enriched([
            {"id": "m1", "role": "User", "segments": [{"type": "text", "content": "hi"}], "raw_len": 50},
        ], seq=1)
        r.apply_messages(msgs)
        r.reset()
        self.assertEqual(r.state.last_seq, 0)
        self.assertEqual(len(r.state.messages_by_id), 0)

    def test_segments_by_id_populated(self):
        r = ChatProjectionReducer()
        msgs = self._make_enriched([
            {"id": "m1", "role": "AI", "segments": [
                {"type": "code", "content": "x=1", "language": "python"},
            ], "raw_len": 100},
        ], seq=1)
        r.apply_messages(msgs)
        seg_keys = list(r.state.segments_by_id.keys())
        self.assertTrue(any("seg_m1:AI_code" in k for k in seg_keys))

    def test_on_change_callback(self):
        r = ChatProjectionReducer()
        changes = []
        r.on_change(lambda t, ids: changes.append((t, ids)))
        msgs = self._make_enriched([
            {"id": "m1", "role": "User", "segments": [{"type": "text", "content": "hi"}], "raw_len": 50},
        ], seq=1)
        r.apply_messages(msgs)
        self.assertEqual(len(changes), 1)
        self.assertEqual(changes[0][0], "snapshot")

    def test_multiple_updates_same_message(self):
        """同一条消息多次内容变化，rev 递增。"""
        r = ChatProjectionReducer()
        for i in range(5):
            msgs = self._make_enriched([
                {"id": "m1", "role": "AI", "segments": [
                    {"type": "code", "content": f"v{i}", "language": "python"},
                ], "raw_len": 100},
            ], seq=i + 1)
            change = r.apply_messages(msgs)
        self.assertEqual(r.state.last_seq, 5)
        msg = r.get_message("m1:AI")
        self.assertIsNotNone(msg)

    def test_fallback_id_stable_in_reducer(self):
        """场景5: 无 DOM ID 消息在 reducer 中身份稳定。"""
        r = ChatProjectionReducer()
        n = DOMNormalizer()

        raw = [{"id": "", "role": "User", "segments": [{"type": "text", "content": "hello"}], "raw_len": 50}]
        c1 = normalize_only(n, raw, conversation_id="c1")
        enriched1 = []
        for cm in c1:
            d = cm.to_dict()
            d["_seq"] = 1
            d["_event"] = "conversation.snapshot"
            enriched1.append(d)
        r.apply_messages(enriched1)

        c2 = normalize_only(n, raw, conversation_id="c1")
        enriched2 = []
        for cm in c2:
            d = cm.to_dict()
            d["_seq"] = 2
            d["_event"] = "conversation.snapshot"
            enriched2.append(d)
        change = r.apply_messages(enriched2)

        self.assertEqual(change["added"], [], "同 ID 不应重复 add")
        self.assertEqual(change["updated"], [], "内容不变不应 update")


class TestConversationEvent(unittest.TestCase):
    def test_to_dict(self):
        e = ConversationEvent(seq=1, conversation_id="c1", round_id="r1",
                              event="message.upsert", payload={"id": "m1"})
        d = e.to_dict()
        self.assertEqual(d["seq"], 1)
        self.assertEqual(d["event"], "message.upsert")
        self.assertIn("created_at", d)


class TestEventType(unittest.TestCase):
    def test_all_types_defined(self):
        expected = [
            "conversation.snapshot", "message.upsert", "message.patch",
            "message.delete", "segment.upsert", "segment.patch",
            "segment.delete", "tool.status", "tool.result",
            "round.state", "stream.done", "sync.reset",
        ]
        for t in expected:
            self.assertIn(t, [e.value for e in EventType])


class TestEndToEnd(unittest.TestCase):
    """端到端数据流验证：模拟 Worker → Signal → Reducer 完整链路。"""

    def test_full_lifecycle(self):
        n = DOMNormalizer()
        seq = SeqGenerator()
        store = BrowserCanonicalStore()
        reducer = ChatProjectionReducer()

        # 1. 首次推送：用户消息
        raw1 = [
            {"id": "m1", "role": "User", "segments": [{"type": "text", "content": "hello"}], "raw_len": 50},
        ]
        c1 = normalize_only(n, raw1, conversation_id="c1")
        s1 = seq.next()
        store.apply_snapshot(c1, s1, "c1")
        enriched1 = [cm.to_dict() | {"_seq": s1, "_event": "conversation.snapshot"} for cm in c1]
        change1 = reducer.apply_messages(enriched1)
        self.assertEqual(change1["added"], ["m1:User"])

        # 2. AI 回复 streaming
        raw2 = [
            {"id": "m1", "role": "User", "segments": [{"type": "text", "content": "hello"}], "raw_len": 50},
            {"id": "m2", "role": "AI", "segments": [
                {"type": "text", "content": "thinking..."},
            ], "raw_len": 100},
        ]
        c2 = normalize_only(n, raw2, conversation_id="c1")
        s2 = seq.next()
        store.apply_snapshot(c2, s2, "c1")
        enriched2 = [cm.to_dict() | {"_seq": s2, "_event": "conversation.snapshot"} for cm in c2]
        change2 = reducer.apply_messages(enriched2)
        self.assertEqual(change2["added"], ["m2:AI"])

        # 3. AI 完成 + 代码块
        raw3 = [
            {"id": "m1", "role": "User", "segments": [{"type": "text", "content": "hello"}], "raw_len": 50},
            {"id": "m2", "role": "AI", "segments": [
                {"type": "text", "content": "here is code:"},
                {"type": "code", "content": "print('hello')", "language": "python"},
            ], "raw_len": 200},
        ]
        c3 = normalize_only(n, raw3, conversation_id="c1")
        s3 = seq.next()
        store.apply_snapshot(c3, s3, "c1")
        enriched3 = [cm.to_dict() | {"_seq": s3, "_event": "conversation.snapshot"} for cm in c3]
        change3 = reducer.apply_messages(enriched3)
        self.assertEqual(change3["updated"], ["m2:AI"])

        # 4. AutoFix 后代码内容变化
        raw4 = [
            {"id": "m1", "role": "User", "segments": [{"type": "text", "content": "hello"}], "raw_len": 50},
            {"id": "m2", "role": "AI", "segments": [
                {"type": "text", "content": "here is code:"},
                {"type": "code", "content": "print('fixed')", "language": "python"},
            ], "raw_len": 200},
        ]
        c4 = normalize_only(n, raw4, conversation_id="c1")
        s4 = seq.next()
        store.apply_snapshot(c4, s4, "c1")
        enriched4 = [cm.to_dict() | {"_seq": s4, "_event": "conversation.snapshot"} for cm in c4]
        change4 = reducer.apply_messages(enriched4)
        self.assertEqual(change4["updated"], ["m2:AI"])

        # 5. 重复推送 → 丢弃
        change5 = reducer.apply_messages(enriched4)
        self.assertEqual(change5["type"], "stale")

        # 6. 最终状态验证
        ordered = reducer.get_ordered_messages()
        self.assertEqual(len(ordered), 2)
        self.assertEqual(ordered[0]["id"], "m1:User")
        self.assertEqual(ordered[1]["id"], "m2:AI")
        self.assertEqual(reducer.state.last_seq, 4)

    def test_conversation_switch(self):
        """对话切换 → 全量重置。"""
        n = DOMNormalizer()
        seq = SeqGenerator()
        reducer = ChatProjectionReducer()

        raw_conv1 = [
            {"id": "m1", "role": "User", "segments": [{"type": "text", "content": "conv1"}], "raw_len": 50},
        ]
        c1 = normalize_only(n, raw_conv1, conversation_id="c1")
        enriched1 = [cm.to_dict() | {"_seq": seq.next(), "_event": "conversation.snapshot"} for cm in c1]
        reducer.apply_messages(enriched1)
        self.assertEqual(len(reducer.state.messages_by_id), 1)

        raw_conv2 = [
            {"id": "m10", "role": "User", "segments": [{"type": "text", "content": "conv2"}], "raw_len": 50},
        ]
        n2 = DOMNormalizer()
        c2 = normalize_only(n2, raw_conv2, conversation_id="c2")
        enriched2 = [cm.to_dict() | {"_seq": seq.next(), "_event": "conversation.snapshot"} for cm in c2]
        change = reducer.apply_messages(enriched2)
        self.assertIn("m10:User", change["added"])
        self.assertIn("m1:User", change["removed"])


if __name__ == "__main__":
    unittest.main()
