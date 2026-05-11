# filename: app/core/driver/__init__.py
import ast
import json
import logging
import time
import hashlib
import re
from bs4 import BeautifulSoup
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.by import By
from .connection import ConnectionManager
from .interaction import InteractionManager
from .parser import DOMParser
from .config import SELECTORS, SCRIPTS
from .browser_incremental import IncrementalExtractor
from app.core.app_constants import CHROME_PORT
from app.core.logging import get_logger

logger = get_logger("app.core.driver", side="worker")


class ChromeConnector:
    def __init__(self, port=CHROME_PORT):
        self.conn = ConnectionManager(port)
        self.parser = DOMParser()  # 复用 UI 的解析核心
        self.interact = None
        self.last_chat_id = None
        self._incremental = IncrementalExtractor(self.parser)

    @property
    def driver(self):
        return self.conn.driver

    def _ensure_live_window(self):
        if not self.driver:
            return False
        try:
            handles = list(self.driver.window_handles or [])
        except Exception as e:
            logger.warning(f"[Driver] 无法获取 window_handles: {e}")
            return False
        if not handles:
            logger.warning("[Driver] 当前没有可用浏览器窗口")
            return False
        try:
            current = self.driver.current_window_handle
            if current in handles:
                return True
        except Exception as e:
            logger.warning(f"[Driver] 当前窗口句柄已失效，尝试切换可用窗口: {e}")
        for handle in handles:
            try:
                self.driver.switch_to.window(handle)
                return True
            except Exception as e:
                logger.debug(f"[Driver] 切换窗口失败 handle={handle}: {e}")
        logger.warning("[Driver] 所有浏览器窗口均不可用")
        return False

    def connect(self):
        ok, msg = self.conn.connect()
        if ok:
            self.interact = InteractionManager(self.conn.driver)
            self.interact.switch_to_chat_tab()
        return ok, msg

    def is_busy(self):
        if self.interact:
            return self.interact.is_busy()
        return False

    def send_message(self, selector, text):
        logger.info("[Driver] send_message requested | selector=%s text_len=%d", selector, len(text or ""))
        return self.interact.send_message(text) if self.interact else (False, "未连接")

    def open_conversation_url(self, conversation_url, timeout=20):
        if not self.interact or not self.driver or not self._ensure_live_window():
            logger.warning("[Driver] open_conversation_url failed: browser_not_connected | url=%s", conversation_url)
            return False, {
                "stage": "switching_conversation",
                "error_code": "browser_not_connected",
            }
        try:
            current_url = self.driver.current_url
        except Exception:
            current_url = ""
        logger.info(
            "[Driver] open_conversation_url requested | target=%s current=%s timeout=%s",
            conversation_url,
            current_url,
            timeout,
        )
        return self.interact.open_conversation_url(conversation_url, timeout=timeout)

    def open_conversation_target(self, conversation_url="", conversation_name="", timeout=20):
        if not self.interact or not self.driver or not self._ensure_live_window():
            logger.warning(
                "[Driver] open_conversation_target failed: browser_not_connected | url=%s name=%s",
                conversation_url,
                conversation_name,
            )
            return False, {
                "stage": "switching_conversation",
                "error_code": "browser_not_connected",
            }
        try:
            current_url = self.driver.current_url
        except Exception:
            current_url = ""
        logger.info(
            "[Driver] open_conversation_target requested | target_url=%s target_name=%s current=%s timeout=%s",
            conversation_url or "(empty)",
            conversation_name or "(empty)",
            current_url,
            timeout,
        )
        return self.interact.open_conversation_target(
            conversation_url=conversation_url,
            conversation_name=conversation_name,
            timeout=timeout,
        )

    def clear_conversation(self, timeout=10):
        if not self.interact or not self.driver or not self._ensure_live_window():
            logger.warning("[Driver] clear_conversation failed: browser_not_connected")
            return False, {
                "stage": "resetting",
                "error_code": "browser_not_connected",
            }
        try:
            logger.info("[Driver] clear_conversation requested | current_url=%s timeout=%s", self.driver.current_url, timeout)
        except Exception:
            logger.info("[Driver] clear_conversation requested | current_url=(unavailable) timeout=%s", timeout)
        self.interact.switch_to_chat_tab()
        self.clear_message_cache()
        return self.interact.clear_conversation(timeout=timeout)

    def wait_until_idle(self, timeout=180, stable_seconds=1.0, progress_callback=None, progress_interval=0.8):
        if not self.interact or not self.driver or not self._ensure_live_window():
            return False, {
                "stage": "waiting",
                "error_code": "browser_not_connected",
            }
        deadline = time.time() + max(1, timeout)
        idle_since = None
        last_progress_at = 0.0
        while time.time() < deadline:
            if self.interact.is_busy():
                idle_since = None
                if progress_callback and time.time() - last_progress_at >= max(0.2, float(progress_interval or 0.8)):
                    last_progress_at = time.time()
                    try:
                        ok, info = self.extract_latest_ai_response(
                            request_id=None,
                            transient=True,
                            require_request_id=False,
                        )
                        if ok:
                            progress_callback(info)
                    except Exception as e:
                        logger.debug("[Driver] wait progress callback skipped: %s", e)
            else:
                if idle_since is None:
                    idle_since = time.time()
                if time.time() - idle_since >= stable_seconds:
                    return True, {
                        "stage": "waiting",
                        "wait_ms": int((timeout - max(0, deadline - time.time())) * 1000),
                    }
            time.sleep(0.25)
        return False, {
            "stage": "waiting",
            "error_code": "response_timeout",
            "timeout_seconds": timeout,
        }

    def extract_latest_ai_response(self, request_id=None, transient=False, require_request_id=True):
        if self.interact:
            try:
                ai_msg_id = self.get_last_ai_message_id()
                if not transient:
                    self.interact.scan_and_fix_last_message()
                if ai_msg_id and hasattr(self, "_incremental") and not transient:
                    self._incremental.cache.invalidate_message(ai_msg_id)
            except Exception as e:
                logger.debug("[Driver] final browser parse preparation skipped: %s", e)

        raw_msgs, _, _ = self.get_chat_content_incremental(transient_last_ai=bool(transient))
        if not raw_msgs:
            raw_msgs, _ = self.get_chat_content(auto_wake=False)
        last_ai_msg = None
        for msg in reversed(raw_msgs or []):
            if str(msg.get("role", "")).lower() == "ai":
                last_ai_msg = msg
                break
        if not last_ai_msg:
            return False, {
                "stage": "extracting",
                "error_code": "ai_response_not_found",
            }

        text_parts = []
        for seg in last_ai_msg.get("segments") or []:
            content = str(seg.get("content", "") or "")
            if not content.strip():
                continue
            if seg.get("type") == "code":
                lang = seg.get("language", "") or ""
                text_parts.append(f"```{lang}\n{content}\n```")
            else:
                text_parts.append(content)
        raw_text = "\n\n".join(text_parts).strip()
        if request_id and require_request_id and request_id not in raw_text:
            return False, {
                "stage": "extracting",
                "error_code": "request_id_mismatch",
                "request_id": request_id,
                "message_id": last_ai_msg.get("id", ""),
                "raw_text_preview": raw_text[:500],
            }
        return True, {
            "stage": "extracting",
            "message_id": last_ai_msg.get("id", ""),
            "message": last_ai_msg,
            "raw_text": raw_text,
            "dom_nodes": len(last_ai_msg.get("segments") or []),
            "raw_len": last_ai_msg.get("raw_len", 0),
        }

    def click_ai_message_action(self, action, message_id=None, confirm_delete=False, timeout=5):
        if not self.interact or not self.driver or not self._ensure_live_window():
            return False, "browser_not_connected"
        return self.interact.click_ai_message_action(
            action,
            message_id=message_id,
            confirm_delete=confirm_delete,
            timeout=timeout,
        )

    def paste_to_input(self, selector="textarea", auto_send=False):
        return self.interact.paste_to_input(auto_send) if self.interact else (False, "未连接")

    def navigate(self, url):
        if not self.driver or not self._ensure_live_window():
            return False
        try:
            self.driver.get(url)
            return True
        except Exception:
            return False

    def new_chat(self):
        if not self.driver or not self._ensure_live_window():
            return False, "未连接"
        return False, "功能迁移中"

    def force_scroll(self, interrupt_callback=None):
        if self.interact:
            self.interact.scroll_traverse(interrupt_callback)

    def manual_toggle_block(self, offset, block_idx, total_blocks, fingerprint=None):
        if self.interact:
            self.interact.manual_toggle_block(offset, block_idx, total_blocks, fingerprint)

    def get_session_list(self):
        if not self.driver or not self._ensure_live_window():
            return []
        try:
            selector = SELECTORS["session_item"]

            try:
                WebDriverWait(self.driver, 5).until(
                    lambda d: d.execute_script("return document.readyState") == "complete"
                )
            except Exception as e:
                logger.warning(f"等待页面加载超时: {e}")

            sessions = self.driver.find_elements("css selector", selector)

            if len(sessions) == 0:
                alt_selectors = [
                    "div[class*='sidebar-list-item']",
                    "div[class*='session']",
                    "div[class*='chat-item']",
                ]
                for alt_sel in alt_selectors:
                    try:
                        sessions = self.driver.find_elements("css selector", alt_sel)
                        if len(sessions) > 0:
                            break
                    except Exception as e:
                        logger.debug(f"备选选择器 {alt_sel} 未找到: {e}")

            data = []
            for i, s in enumerate(sessions):
                try:
                    raw_text = s.text.strip()
                    lines_list = [line.strip() for line in raw_text.split('\n') if line.strip()]
                    title = "New Chat"
                    date_str = ""
                    icon_char = ""
                    if len(lines_list) >= 1:
                        if len(lines_list[0]) <= 2:
                            icon_char = lines_list[0]
                            if len(lines_list) > 1:
                                title = lines_list[1]
                            if len(lines_list) > 2:
                                date_str = lines_list[2]
                        else:
                            title = lines_list[0]
                            if len(lines_list) > 1:
                                date_str = lines_list[1]
                    is_active = "active" in (s.get_attribute("class") or "")
                    data.append({
                        "index": i,
                        "title": title,
                        "date": date_str,
                        "icon": icon_char,
                        "active": is_active,
                    })
                except Exception:
                    pass
            return data
        except Exception as e:
            logger.warning(f"[Driver] get_session_list 异常: {e}")
            return []

    def get_chat_title_id(self):
        if not self.driver or not self._ensure_live_window():
            return "default"
        try:
            active_item = self.driver.find_element("css selector", SELECTORS["session_active"])
            raw_text = active_item.text.strip()
            lines = [line.strip() for line in raw_text.split('\n') if line.strip()]
            title = "Unknown"
            if len(lines) >= 1:
                title = lines[1] if len(lines[0]) <= 2 and len(lines) > 1 else lines[0]
            return hashlib.md5(title.encode("utf-8")).hexdigest()
        except Exception:
            return "default"

    def get_active_session_text(self):
        if not self.driver or not self._ensure_live_window():
            return None
        try:
            el = self.driver.find_element("css selector", SELECTORS["session_active"])
            return el.text.replace("\n", " ").strip()
        except Exception:
            return None

    def switch_session(self, index):
        if not self.driver or not self._ensure_live_window():
            return False
        try:
            sessions = self.driver.find_elements("css selector", SELECTORS["session_item"])
            if 0 <= index < len(sessions):
                sessions[index].click()
                return True
            return False
        except Exception:
            return False

    def get_last_ai_message_id(self):
        """轻量查询：只取最后一条 AI 消息的 data-message-id，不解析 DOM 内容。"""
        if not self.driver or not self._ensure_live_window():
            return ''
        try:
            msg_id = self.driver.execute_script("""
                var items = document.querySelectorAll('.chat-item[data-message-ai="true"]');
                if (items.length > 0) {
                    return items[items.length - 1].getAttribute('data-message-id') || '';
                }
                return '';
            """)
            return str(msg_id or '').strip()
        except Exception:
            return ''

    # [Refactor] 逻辑统一：直接调用 Parser，不再手写 JS 提取
    def check_last_ai_message_for_tool(self):
        """
        检查最后一条 AI 消息是否包含工具调用
        """
        if not self.driver or not self._ensure_live_window():
            return None

        try:
            structured_msgs, _ = self.get_chat_content(auto_wake=False)
            if not structured_msgs:
                return None

            last_ai_msg = None
            for msg in reversed(structured_msgs):
                if str(msg.get("role", "")).lower() == "ai":
                    last_ai_msg = msg
                    break
            if not last_ai_msg:
                return None

            final_text_parts = []
            for seg in (last_ai_msg.get("segments") or []):
                content = str(seg.get("content", "") or "")
                if not content.strip():
                    continue
                if seg.get("type") == "code":
                    lang = seg.get("language", "python")
                    if not content.strip().startswith("```"):
                        final_text_parts.append(f"```{lang}\n{content}\n```")
                    else:
                        final_text_parts.append(content)
                else:
                    final_text_parts.append(content)

            return "\n\n".join(final_text_parts) if final_text_parts else None
        except Exception as e:
            logger.warning(f"[Driver] Check Tool Error: {e}")
            return None

    def get_chat_content(self, target_class="chat-text", auto_wake=True, transient_last_ai=False):
        if not self.interact or not self.driver or not self._ensure_live_window():
            return [], False
        self.interact.switch_to_chat_tab()
        try:
            elements = self.interact.find_elements(SELECTORS["chat_items"])
            is_at_bottom = self.driver.execute_script(SCRIPTS["scroll_check"])
            structured_msgs = []
            fallback_count = 0
            for idx, el in enumerate(elements):
                if el.size["height"] == 0:
                    continue
                html = el.get_attribute("outerHTML") or ""
                raw_text = (el.text or "").replace("\n", " ").strip()
                text_preview = raw_text
                soup = BeautifulSoup(html, "html.parser")

                message_ai_attr = str(el.get_attribute("data-message-ai") or "").strip().lower()
                if message_ai_attr == "true":
                    role = "AI"
                elif message_ai_attr == "false":
                    role = "User"
                else:
                    class_str = " ".join(soup.find("div").get("class", []) if soup.find("div") else [])
                    role = "User" if ("user" in class_str or "human" in class_str) else "AI"

                primary_nodes = soup.select(".chat-text")
                all_segments = []
                transient_placeholders = []
                use_transient_parse = bool(transient_last_ai and role == "AI" and idx == len(elements) - 1)
                if primary_nodes:
                    for node in primary_nodes:
                        if use_transient_parse:
                            transient_segments, placeholders = self.parser.parse_browser_transient_message(node)
                            all_segments.extend(transient_segments)
                            transient_placeholders.extend(placeholders)
                        else:
                            all_segments.extend(self.parser.parse_node(node))
                else:
                    from .browser_incremental import _filter_top_level_nodes
                    valid_nodes = soup.find_all(class_=lambda x: x and any(b in x for b in SELECTORS["content_blocks"]))
                    valid_nodes = _filter_top_level_nodes(valid_nodes)
                    if not valid_nodes:
                        if use_transient_parse:
                            transient_segments, placeholders = self.parser.parse_browser_transient_message(soup)
                            all_segments = list(transient_segments)
                            transient_placeholders.extend(placeholders)
                        else:
                            all_segments = self.parser.parse_node(soup)
                    else:
                        for node in valid_nodes:
                            if use_transient_parse:
                                transient_segments, placeholders = self.parser.parse_browser_transient_message(node)
                                all_segments.extend(transient_segments)
                                transient_placeholders.extend(placeholders)
                            else:
                                all_segments.extend(self.parser.parse_node(node))

                final = self.parser.clean_code_headers(all_segments)
                if use_transient_parse and transient_placeholders:
                    final.extend(transient_placeholders)
                if not final:
                    continue

                message_id = (
                    el.get_attribute("data-message-id")
                    or el.get_attribute("data-id")
                    or el.get_attribute("id")
                    or ""
                )
                if not message_id:
                    ts_match = re.search(r"\b\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}\b", raw_text)
                    ts_text = ts_match.group(0) if ts_match else ""
                    fallback_preview = text_preview[:120]
                    fallback_source = f"{role}|{ts_text}|{fallback_preview}" if (ts_text or fallback_preview) else f"{role}|chat-item-{idx}"
                    fallback_hash = hashlib.md5(fallback_source.encode("utf-8")).hexdigest()[:8]
                    message_id = f"msg_fallback_{fallback_hash}"
                    fallback_count += 1
                    class_name = (el.get_attribute("class") or "").strip()
                    logger.debug(
                        f"[Driver] 消息缺少 data-message-id，已生成兜底 ID | "
                        f"index={idx} | role={role} | fallback_id={message_id} | class={class_name[:120]} | ts={ts_text or '-'}"
                    )

                code_index = 0
                for seg in final:
                    if seg.get("type") != "code":
                        continue
                    code_content = str(seg.get("content", "") or "")
                    code_fingerprint = hashlib.md5(code_content.encode("utf-8")).hexdigest()[:8]
                    seg["message_id"] = message_id
                    seg["block_index"] = code_index
                    seg["code_fingerprint"] = code_fingerprint
                    seg["block_key"] = f"{message_id}:{code_index}"
                    seg["segment_id"] = f"seg_{message_id}_code_{code_index}"
                    seg["content_hash"] = hashlib.md5(f"code:{code_content}".encode("utf-8")).hexdigest()[:12]
                    code_index += 1

                text_index = 0
                for seg in final:
                    if seg.get("type") != "text":
                        continue
                    content = str(seg.get("content", "") or "")
                    seg["segment_id"] = f"seg_{message_id}_text_{text_index}"
                    seg["content_hash"] = hashlib.md5(f"text:{content}".encode("utf-8")).hexdigest()[:12]
                    text_index += 1

                structured_msgs.append({"id": message_id, "role": role, "segments": final, "raw_len": len(html)})
            if fallback_count > 0:
                logger.debug(
                    f"[Driver] 本轮共 {fallback_count} 条消息缺少 data-message-id，DOM 标识可能已变化"
                )
            return structured_msgs, is_at_bottom
        except Exception as e:
            logger.warning(f"[Driver] get_chat_content 异常: {e}")
            return [], False

    def get_chat_content_incremental(self, transient_last_ai=False):
        """增量提取消息。优先用缓存，只对变化的消息做 BS4 解析。
        返回 (structured_msgs, is_at_bottom, has_structural_change)。"""
        if not self.interact or not self.driver or not self._ensure_live_window():
            return [], False, False
        self.interact.switch_to_chat_tab()
        return self._incremental.extract(
            self.driver, self.interact, transient_last_ai=transient_last_ai
        )

    def clear_message_cache(self):
        """会话切换时清空消息缓存，下次提取走全量。"""
        self._incremental.clear_cache()
