# filename: app/core/driver/interaction.py
import time
import json
import math
import os
import random
import logging
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from .config import SELECTORS, SCRIPTS, CODE_BLOCK_SELECTORS

logger = logging.getLogger(__name__)

# FontAwesome (旧版) — <i> 元素 class 片段
STATE_EXPANDED = "up-right-and-down-left-from-center"
STATE_COLLAPSED = "down-left-and-up-right-to-center"

# Lucide SVG (新版) — <svg> 元素 class 片段
LUCIDE_EXPANDED = "lucide-minimize-2"   # 展开状态 → 含 "退出全屏" 按钮
LUCIDE_COLLAPSED = "lucide-maximize-2"  # 收缩状态 → 含 "展开" 按钮
LUCIDE_COPY = "lucide-copy"             # 复制按钮

# WebAI message-level toolbar icons (not code-block toolbar).
MSG_COPY_PATH = "M216 40v128h-48V88H88V40Z"
MSG_REGENERATE_PATH = "M20 11A8.1 8.1 0 0 0 4.5 9M4 5v4h4"
MSG_DELETE_PATH = "M864 256H736v-80c0-35.3"

# 合并列表：用于遍历查找
ALL_COLLAPSED = [STATE_COLLAPSED, LUCIDE_COLLAPSED]
ALL_EXPANDED = [STATE_EXPANDED, LUCIDE_EXPANDED]

TARGET_ICONS = ALL_COLLAPSED + ALL_EXPANDED
TARGET_XPATH = " or ".join([f"contains(@class, '{icon}')" for icon in TARGET_ICONS])

class InteractionManager:
    def __init__(self, driver):
        self.driver = driver
        self.fixed_registry = set()
        self.target_handle = None

    def find_element(self, selector):
        return self.driver.find_element(By.CSS_SELECTOR, selector)

    def find_elements(self, selector):
        return self.driver.find_elements(By.CSS_SELECTOR, selector)

    def is_busy(self):
        if self._has_generating_spinner():
            return True
        if self._has_stop_button():
            return True
        return False

    def _has_generating_spinner(self):
        try:
            selectors = [
                '.spinner-box',
                '.pulse-container',
                '.pulse-bubble',
            ]
            for selector in selectors:
                nodes = self.driver.find_elements(By.CSS_SELECTOR, selector)
                for node in nodes:
                    if node.is_displayed():
                        return True
        except:
            pass
        return False

    def _has_stop_button(self):
        try:
            xpath = "//button[contains(@class, 'n-button--error-type') and .//span[contains(text(), '停止')]]"
            btns = self.driver.find_elements(By.XPATH, xpath)
            for btn in btns:
                if btn.is_displayed(): return True
            xpath_icon = "//button[.//i[contains(@class, 'fa-stop')]]"
            btns_icon = self.driver.find_elements(By.XPATH, xpath_icon)
            for btn in btns_icon:
                if btn.is_displayed(): return True
        except: pass
        return False

    def _is_content_growing(self):
        """跨循环对比文本长度，无需内部 sleep"""
        try:
            items = self.find_elements(SELECTORS["chat_items"])
            if not items:
                self._last_content_len = 0
                return False
            current_len = len(items[-1].text)
            prev_len = getattr(self, '_last_content_len', 0)
            self._last_content_len = current_len
            if current_len > prev_len and prev_len > 0:
                return True
        except: pass
        return False

    def send_message(self, text):
        try:
            logger.info("[Interaction] send_message start | text_len=%d current_url=%s", len(text or ""), getattr(self.driver, "current_url", ""))
            web_input = self.find_element(SELECTORS["input_area"])
            before = self._chat_submit_state()
            logger.info("[Interaction] send_message before state | %s", before)
            use_js_injection = len(text) > 10 or "\n" in text or not text.isascii()
            if use_js_injection:
                self.driver.execute_script(SCRIPTS["react_input"], web_input, text)
                time.sleep(0.1)
                clicked = False
                for xpath in SELECTORS["send_buttons_xpath"]:
                    try:
                        btns = self.driver.find_elements(By.XPATH, xpath)
                        for btn in btns:
                            if btn.is_displayed():
                                self.driver.execute_script("arguments[0].click();", btn)
                                clicked = True
                                break
                        if clicked:
                            break
                    except Exception:
                        pass
                if not clicked:
                    web_input.send_keys(Keys.ENTER)
            else:
                web_input.send_keys(text)
                time.sleep(0.05)
                web_input.send_keys(Keys.ENTER)
            if not self._wait_for_user_message_after_submit(before, timeout=8):
                after = self._chat_submit_state()
                logger.warning("[Interaction] send_message failed: send_not_committed | before=%s after=%s", before, after)
                return False, "send_not_committed"
            after = self._chat_submit_state()
            logger.info("[Interaction] send_message committed | before=%s after=%s", before, after)
            return True, "发送成功"
        except Exception as e:
            logger.exception("[Interaction] send_message exception")
            return False, f"发送失败: {e}"

    def _chat_submit_state(self):
        try:
            return self.driver.execute_script("""
                var items = Array.from(document.querySelectorAll('.chat-item[data-message-ai="false"]'));
                var last = items.length ? items[items.length - 1] : null;
                return {
                    user_count: items.length,
                    last_user_id: last ? (last.getAttribute('data-message-id') || last.getAttribute('data-id') || last.id || '') : ''
                };
            """) or {}
        except Exception:
            logger.exception("[Interaction] read chat submit state failed")
            return {}

    def _wait_for_user_message_after_submit(self, before, timeout=8):
        before_count = int((before or {}).get("user_count") or 0)
        before_last_id = str((before or {}).get("last_user_id") or "")

        def committed(driver):
            state = driver.execute_script("""
                var items = Array.from(document.querySelectorAll('.chat-item[data-message-ai="false"]'));
                var last = items.length ? items[items.length - 1] : null;
                return {
                    user_count: items.length,
                    last_user_id: last ? (last.getAttribute('data-message-id') || last.getAttribute('data-id') || last.id || '') : ''
                };
            """) or {}
            count = int(state.get("user_count") or 0)
            last_id = str(state.get("last_user_id") or "")
            return count > before_count or (last_id and last_id != before_last_id)

        try:
            WebDriverWait(self.driver, timeout).until(committed)
            return True
        except Exception:
            return False

    def _wait_for_send_button(self, timeout=5):
        def find(driver):
            button = driver.execute_script("""
                var roots = Array.from(document.querySelectorAll('.aa-chat-input, .chat-input-box'));
                var buttons = roots.flatMap(function(root) {
                    return Array.from(root.querySelectorAll('button'));
                });
                function visible(el) {
                    var rect = el.getBoundingClientRect();
                    var style = window.getComputedStyle(el);
                    return rect.width > 0 && rect.height > 0 && style.visibility !== 'hidden' && style.display !== 'none';
                }
                function disabled(el) {
                    return el.disabled || el.getAttribute('aria-disabled') === 'true' || el.classList.contains('n-button--disabled');
                }
                return buttons.find(function(btn) {
                    var text = (btn.innerText || btn.textContent || '').trim();
                    return visible(btn) && !disabled(btn) && text.indexOf('发送') >= 0;
                }) || null;
            """)
            return button or False

        try:
            return WebDriverWait(self.driver, timeout).until(find)
        except Exception:
            logger.warning("[Interaction] send button wait timeout | timeout=%s debug=%s", timeout, self._debug_send_surface())
            return None

    def _debug_send_surface(self):
        try:
            return self.driver.execute_script("""
                var roots = Array.from(document.querySelectorAll('.aa-chat-input, .chat-input-box'));
                return roots.map(function(root) {
                    var rect = root.getBoundingClientRect();
                    return {
                        className: root.className,
                        text: (root.innerText || root.textContent || '').trim().slice(0, 200),
                        rect: { width: rect.width, height: rect.height, top: rect.top, left: rect.left },
                        buttonTexts: Array.from(root.querySelectorAll('button')).map(function(btn) {
                            return {
                                text: (btn.innerText || btn.textContent || '').trim(),
                                disabled: btn.disabled || btn.getAttribute('aria-disabled') === 'true' || btn.classList.contains('n-button--disabled'),
                                className: btn.className
                            };
                        })
                    };
                });
            """)
        except Exception as e:
            return {"error": str(e)}

    def open_conversation_url(self, conversation_url, timeout=20):
        url = str(conversation_url or "").strip()
        if not url:
            return False, {
                "stage": "switching_conversation",
                "error_code": "conversation_url_empty",
            }
        try:
            current = str(getattr(self.driver, "current_url", "") or "")
        except Exception:
            current = ""
        try:
            logger.info("[Interaction] open_conversation_url start | current=%s target=%s", current, url)
            if current != url:
                self.driver.get(url)
                self.target_handle = self.driver.current_window_handle
                logger.info("[Interaction] driver.get called | target=%s handle=%s", url, self.target_handle)

            def loaded(driver):
                try:
                    has_input = bool(driver.find_elements(By.CSS_SELECTOR, SELECTORS["input_area"]))
                    has_chat = bool(driver.find_elements(By.CSS_SELECTOR, SELECTORS["chat_items"]))
                    return has_input or has_chat
                except Exception:
                    return False

            WebDriverWait(self.driver, timeout).until(loaded)
            final_url = str(getattr(self.driver, "current_url", "") or "")
            debug_surface = self._debug_send_surface()
            logger.info(
                "[Interaction] open_conversation_url loaded | target=%s final=%s debug_surface=%s",
                url,
                final_url,
                debug_surface,
            )
            return True, {
                "stage": "switching_conversation",
                "conversation_url": url,
                "current_url": final_url,
                "debug_surface": debug_surface,
            }
        except Exception as e:
            logger.exception("[Interaction] open_conversation_url failed | target=%s", url)
            return False, {
                "stage": "switching_conversation",
                "error_code": "conversation_switch_failed",
                "conversation_url": url,
                "current_url": str(getattr(self.driver, "current_url", "") or ""),
                "error": str(e),
            }

    def open_conversation_target(self, conversation_url="", conversation_name="", timeout=20):
        url = str(conversation_url or "").strip()
        name = str(conversation_name or "").strip()
        if url:
            return self.open_conversation_url(url, timeout=timeout)
        if not name:
            return False, {
                "stage": "switching_conversation",
                "error_code": "conversation_target_empty",
            }
        try:
            logger.info("[Interaction] open_conversation_target by name | name=%s current_url=%s", name, getattr(self.driver, "current_url", ""))
            switched = self._click_conversation_by_name(name)
            if not switched:
                return False, {
                    "stage": "switching_conversation",
                    "error_code": "conversation_name_not_found",
                    "conversation_name": name,
                    "sessions": self._debug_session_list(),
                }

            def loaded(driver):
                try:
                    has_input = bool(driver.find_elements(By.CSS_SELECTOR, SELECTORS["input_area"]))
                    return has_input
                except Exception:
                    return False

            WebDriverWait(self.driver, timeout).until(loaded)
            active_text = self._active_session_text()
            info = {
                "stage": "switching_conversation",
                "conversation_name": name,
                "current_url": str(getattr(self.driver, "current_url", "") or ""),
                "active_session_text": active_text,
                "debug_surface": self._debug_send_surface(),
            }
            logger.info("[Interaction] open_conversation_target by name loaded | info=%s", info)
            return True, info
        except Exception as e:
            logger.exception("[Interaction] open_conversation_target by name failed | name=%s", name)
            return False, {
                "stage": "switching_conversation",
                "error_code": "conversation_name_switch_failed",
                "conversation_name": name,
                "current_url": str(getattr(self.driver, "current_url", "") or ""),
                "error": str(e),
            }

    def _click_conversation_by_name(self, name):
        return bool(self.driver.execute_script("""
            var target = String(arguments[0] || '').trim();
            var items = Array.from(document.querySelectorAll('.aa-sidebar-list-item'));
            function visible(el) {
                var rect = el.getBoundingClientRect();
                var style = window.getComputedStyle(el);
                return rect.width > 0 && rect.height > 0 && style.visibility !== 'hidden' && style.display !== 'none';
            }
            function titleOf(el) {
                var lines = (el.innerText || el.textContent || '').split('\\n').map(function(s) {
                    return s.trim();
                }).filter(Boolean);
                if (!lines.length) return '';
                if (lines[0].length <= 2 && lines.length > 1) return lines[1];
                return lines[0];
            }
            var exact = items.find(function(el) { return visible(el) && titleOf(el) === target; });
            var fuzzy = exact || items.find(function(el) { return visible(el) && titleOf(el).indexOf(target) >= 0; });
            if (!fuzzy) return false;
            fuzzy.scrollIntoView({block: 'center', inline: 'nearest'});
            fuzzy.click();
            return true;
        """, name))

    def _active_session_text(self):
        try:
            return self.driver.execute_script("""
                var el = document.querySelector('.aa-sidebar-list-item.active');
                return el ? (el.innerText || el.textContent || '').trim() : '';
            """) or ""
        except Exception:
            return ""

    def _debug_session_list(self):
        try:
            return self.driver.execute_script("""
                return Array.from(document.querySelectorAll('.aa-sidebar-list-item')).slice(0, 30).map(function(el, index) {
                    var lines = (el.innerText || el.textContent || '').split('\\n').map(function(s) {
                        return s.trim();
                    }).filter(Boolean);
                    var title = lines.length ? (lines[0].length <= 2 && lines.length > 1 ? lines[1] : lines[0]) : '';
                    return { index: index, title: title, text: lines.join(' | '), active: el.classList.contains('active') };
                });
            """)
        except Exception as e:
            return {"error": str(e)}

    def paste_to_input(self, auto_send=False):
        try:
            web_input = self.find_element(SELECTORS["input_area"])
            web_input.click(); time.sleep(0.1)
            web_input.send_keys(Keys.CONTROL, 'v')
            if auto_send:
                time.sleep(0.3); web_input.send_keys(Keys.ENTER)
            return True, "粘贴成功"
        except Exception as e: return False, f"粘贴失败: {e}"

    def upload_file(self, file_paths):
        if isinstance(file_paths, list):
            valid_paths = [p for p in file_paths if os.path.exists(p)]
            if not valid_paths: return False, "所有文件均不存在"
            paths_str = "\n".join(valid_paths)
        else:
            if not os.path.exists(file_paths): return False, "文件不存在"
            paths_str = file_paths
        try:
            # 1. 尝试点击附件按钮 (触发上传框)
            triggers = self.driver.find_elements(By.XPATH, SELECTORS["upload_trigger"])
            clicked = False
            for btn in triggers:
                if btn.is_displayed():
                    btn.click()
                    clicked = True; break
            
            # [Fix] 如果没找到附件按钮，尝试直接找 input[type=file]
            if not clicked:
                print("⚠️ 未找到显式附件按钮，尝试隐式 Input...")
            
            # 2. 查找文件输入框 (增加 fallback)
            file_input = self._wait_for_file_input(timeout=8)
            if not file_input:
                return False, "upload_input_not_created: 未找到文件输入框"
            file_input.send_keys(paths_str)

            wait_time = 1.0 + 0.5 * paths_str.count('\n')
            time.sleep(wait_time) 
            
            # 3. 确认上传 (如果有确认按钮的话)
            confirms = self.driver.find_elements(By.XPATH, SELECTORS["upload_confirm"])
            for btn in confirms:
                if btn.is_displayed(): 
                    btn.click()
                    break
            
            return True, "批量上传指令已执行"
        except Exception as e:
            return False, f"上传异常: {e}"

    def _wait_for_file_input(self, timeout=8):
        """Wait for NaiveUI upload input; minimized/slow rendering may create it late."""
        deadline = time.time() + timeout
        selectors = [SELECTORS["file_input"], "input[type='file']"]
        while time.time() < deadline:
            for selector in selectors:
                try:
                    inputs = self.driver.find_elements(By.CSS_SELECTOR, selector)
                    for file_input in inputs:
                        if file_input:
                            return file_input
                except Exception:
                    pass
            time.sleep(0.2)
        return None

    def click_ai_message_action(self, action, message_id=None, confirm_delete=False, timeout=5):
        """
        Click a WebAI message-level toolbar action.

        action: "copy", "regenerate", or "delete".
        message_id: target data-message-id; defaults to latest AI message.
        delete is blocked unless confirm_delete=True.
        """
        action = (action or "").strip().lower()
        if action not in {"copy", "regenerate", "delete"}:
            return False, f"unsupported_action: {action}"
        if action == "delete" and not confirm_delete:
            return False, "delete_requires_confirm"

        try:
            self.switch_to_chat_tab()
            button = self._find_ai_message_action_button(action, message_id=message_id, timeout=timeout)
            if not button:
                return False, f"{action}_button_not_found"
            self.driver.execute_script("arguments[0].scrollIntoView({behavior: 'auto', block: 'center'});", button)
            time.sleep(0.1)
            self.driver.execute_script("arguments[0].click();", button)
            if action == "delete":
                self._confirm_clear_dialog_if_present()
            return True, f"{action}_clicked"
        except Exception as e:
            return False, f"{action}_failed: {e}"

    def _find_ai_message_action_button(self, action, message_id=None, timeout=5):
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                button = self.driver.execute_script("""
                    var action = arguments[0];
                    var messageId = arguments[1];
                    var pathMap = {
                        copy: %s,
                        regenerate: %s,
                        delete: %s
                    };
                    var pathNeedle = pathMap[action];
                    function visible(el) {
                        var rect = el.getBoundingClientRect();
                        var style = window.getComputedStyle(el);
                        return rect.width > 0 && rect.height > 0 && style.display !== 'none' && style.visibility !== 'hidden';
                    }
                    function pathMatches(btn) {
                        var paths = Array.from(btn.querySelectorAll('path')).map(function(p) {
                            return p.getAttribute('d') || '';
                        });
                        return paths.some(function(d) { return d.indexOf(pathNeedle) >= 0; });
                    }
                    var selector = '.chat-item[data-message-ai="true"][data-message-id]';
                    var messages = Array.from(document.querySelectorAll(selector));
                    if (messageId) {
                        messages = messages.filter(function(item) {
                            return item.getAttribute('data-message-id') === messageId;
                        });
                    } else {
                        messages = messages.slice(-1);
                    }
                    for (var i = messages.length - 1; i >= 0; i--) {
                        var msg = messages[i];
                        try { msg.scrollIntoView({behavior: 'auto', block: 'center'}); } catch (e) {}
                        var toolbar = msg.querySelector('.chat-toolbar') || msg;
                        var buttons = Array.from(toolbar.querySelectorAll('button.n-button'))
                            .filter(function(btn) {
                                return !btn.closest('.code-block-container')
                                    && !btn.closest('.node-slot[data-node-type="code_block"]')
                                    && pathMatches(btn);
                            });
                        if (buttons.length) {
                            return buttons.find(visible) || buttons[0];
                        }
                    }
                    return null;
                """ % (json.dumps(MSG_COPY_PATH), json.dumps(MSG_REGENERATE_PATH), json.dumps(MSG_DELETE_PATH)), action, message_id)
                if button:
                    return button
            except Exception:
                pass
            time.sleep(0.2)
        return None

    def fast_expand_all(self):
        try:
            js_expand = """
            var collapsedClasses = %s;
            var allBtns = document.querySelectorAll('button');
            var stats = { found: 0, clicked: 0, skipped: 0 };

            allBtns.forEach(function(btn) {
                var html = btn.innerHTML;
                var isCollapsed = collapsedClasses.some(function(cls) {
                    return html.indexOf(cls) !== -1;
                });
                if (isCollapsed) {
                    stats.found++;
                    if (btn.dataset.aiExpanded === 'true') {
                        stats.skipped++;
                    } else {
                        btn.click();
                        btn.dataset.aiExpanded = 'true';
                        stats.clicked++;
                    }
                }
            });
            return stats;
            """ % json.dumps(ALL_COLLAPSED)
            stats = self.driver.execute_script(js_expand)
            if stats and stats.get('clicked', 0) > 0:
                print(f"⚡ [Expand] 发现:{stats['found']} | 新增点击:{stats['clicked']} | 已跳过:{stats['skipped']}")
            return stats.get('clicked', 0)
        except Exception as e:
            return 0

    def scan_and_fix_last_message(self):
        try:
            js_expand_last = """
            var items = document.querySelectorAll('.chat-item');
            if (items.length > 0) {
                var last = items[items.length - 1];
                var collapsedClasses = %s;
                var clicked = 0;
                var allBtns = last.querySelectorAll('button');
                allBtns.forEach(function(btn) {
                    var html = btn.innerHTML;
                    var isCollapsed = collapsedClasses.some(function(cls) {
                        return html.indexOf(cls) !== -1;
                    });
                    if (isCollapsed) {
                        btn.click();
                        clicked++;
                    }
                });
                return clicked;
            }
            return 0;
            """ % json.dumps(ALL_COLLAPSED)
            clicked = self.driver.execute_script(js_expand_last)
            if clicked > 0:
                print(f"⚡ [AutoFix] 在最后一条消息中展开了 {clicked} 个代码块")
                time.sleep(0.2)
            else:
                logger.debug("[AutoFix] 未找到折叠代码块 | 可能已展开或 DOM 尚未渲染")

            target_xpath = SELECTORS["scroll_container_xpath"]
            js_measure = """
            var container = document.evaluate(arguments[0], document, null, XPathResult.FIRST_ORDERED_NODE_TYPE, null).singleNodeValue;
            var items = document.querySelectorAll('.chat-item');
            if (container && items.length > 0) {
                var last = items[items.length - 1];
                if (last.querySelector('.code-block-container') || last.querySelector('.monaco-editor')) {
                    return {
                        start: last.offsetTop,
                        end: last.offsetTop + last.offsetHeight,
                        need_scroll: true
                    };
                }
            }
            return { need_scroll: false };
            """
            info = self.driver.execute_script(js_measure, target_xpath)
            
            if info and info.get('need_scroll'):
                start = info['start']
                end = info['end']
                print(f"🔧 [AutoFix] 正在遍历最后一条消息 ({start} -> {end})...")
                
                self.driver.execute_script(f"""
                var c = document.evaluate(arguments[0], document, null, XPathResult.FIRST_ORDERED_NODE_TYPE, null).singleNodeValue;
                if(c) c.scrollTo({{top: {start}, behavior: 'auto'}});
                """, target_xpath)
                
                current = start
                step = 400
                
                while current < end:
                    current += step
                    self.driver.execute_script(f"""
                    var c = document.evaluate(arguments[0], document, null, XPathResult.FIRST_ORDERED_NODE_TYPE, null).singleNodeValue;
                    if(c) c.scrollTo({{top: {current}, behavior: 'auto'}});
                    """, target_xpath)
                    time.sleep(0.02)
                
                self.driver.execute_script(f"""
                var c = document.evaluate(arguments[0], document, null, XPathResult.FIRST_ORDERED_NODE_TYPE, null).singleNodeValue;
                if(c) c.scrollTo({{top: c.scrollHeight, behavior: 'auto'}});
                """, target_xpath)
                
        except Exception as e:
            print(f"⚠️ [AutoFix] Error: {e}")

    def ensure_expanded(self): pass
    def trigger_refresh(self, message_element, block_index, unique_id): pass
    
    def scroll_traverse(self, interrupt_check=None):
        try:
            target_xpath = SELECTORS["scroll_container_xpath"]
            js_reset = """
            var container = document.evaluate(arguments[0], document, null, XPathResult.FIRST_ORDERED_NODE_TYPE, null).singleNodeValue;
            if (container) { container.scrollTo({top: 0}); return container.scrollHeight; }
            return 0;
            """
            total_height = self.driver.execute_script(js_reset, target_xpath)
            time.sleep(0.2)

            current = 0
            max_steps = 4000 
            last_scroll_top = -1 
            
            FAST_STEP = 600   
            FAST_WAIT = 0.01  
            
            SLOW_STEP = 150   
            SLOW_WAIT = 0.05  
            
            step_count = 0 
            
            while current < total_height and max_steps > 0:
                if interrupt_check and interrupt_check():
                    print("🛑 [Scroll] 收到中断信号，立即停止唤醒！")
                    break

                js_check_view = """
                var container = document.evaluate(arguments[0], document, null, XPathResult.FIRST_ORDERED_NODE_TYPE, null).singleNodeValue;
                if (!container) return false;

                var scrollTop = container.scrollTop || 0;
                var viewHeight = container.clientHeight || 600;
                var midY = scrollTop + viewHeight / 2;
                var containerRect = container.getBoundingClientRect();
                var codeBlocks = container.querySelectorAll('.node-slot[data-node-type="code_block"]');
                if (!codeBlocks.length) {
                    codeBlocks = container.querySelectorAll('.code-block-container, pre');
                }

                for (var i = 0; i < codeBlocks.length; i++) {
                    var block = codeBlocks[i];
                    var rect = block.getBoundingClientRect();
                    var blockTop = scrollTop + (rect.top - containerRect.top);
                    var blockHeight = block.offsetHeight || rect.height || 0;
                    var blockBottom = blockTop + blockHeight;
                    if (midY >= blockTop && midY <= blockBottom) {
                        return true;
                    }
                }
                return false;
                """
                in_code_block = self.driver.execute_script(js_check_view, target_xpath)
                
                if in_code_block:
                    step = SLOW_STEP
                    wait = SLOW_WAIT
                else:
                    step = FAST_STEP
                    wait = FAST_WAIT
                
                current += step
                
                js_scroll = """
                var container = document.evaluate(arguments[0], document, null, XPathResult.FIRST_ORDERED_NODE_TYPE, null).singleNodeValue;
                if (container) { 
                    container.scrollTo({top: arguments[1], behavior: 'auto'});
                    return { total: container.scrollHeight, top: container.scrollTop }; 
                }
                return null;
                """
                result = self.driver.execute_script(js_scroll, target_xpath, current)
                
                if not result: break
                
                new_total = result['total']
                current_top = result['top']
                
                if current_top == last_scroll_top: break
                if current_top + 1000 >= new_total: break
                    
                last_scroll_top = current_top
                if new_total > total_height: total_height = new_total
                
                time.sleep(wait) 
                
                step_count += 1
                if in_code_block or (step_count % 10 == 0):
                    self.fast_expand_all()
                
                max_steps -= 1
            
            if not (interrupt_check and interrupt_check()):
                js_bottom = """
                var container = document.evaluate(arguments[0], document, null, XPathResult.FIRST_ORDERED_NODE_TYPE, null).singleNodeValue;
                if (container) { container.scrollTo({top: container.scrollHeight}); }
                """
                self.driver.execute_script(js_bottom, target_xpath)
        except Exception as e: pass

    def manual_toggle_block(self, offset_from_end, block_index, total_ide_blocks, fingerprint=None):
        try:
            items = self.driver.find_elements(By.CSS_SELECTOR, SELECTORS["chat_items"])
            if not items: return
            target_msg = None
            if fingerprint:
                for item in reversed(items):
                    raw_text = item.get_attribute("textContent") or ""
                    if fingerprint in raw_text.replace("\n", ""):
                        target_msg = item; break
            if not target_msg:
                target_idx = len(items) - 1 - offset_from_end
                if 0 <= target_idx < len(items):
                    target_msg = items[target_idx]
            if not target_msg: return
            self.driver.execute_script("arguments[0].scrollIntoView({behavior: 'auto', block: 'start'});", target_msg)
            time.sleep(0.2)
            valid_pairs = self._get_valid_code_blocks(target_msg)
            real_target_index = block_index
            if len(valid_pairs) > total_ide_blocks:
                real_target_index += (len(valid_pairs) - total_ide_blocks)
            if real_target_index < len(valid_pairs):
                target_pair = valid_pairs[real_target_index]
                toggle_btn = target_pair['toggle']
                btn_html = toggle_btn.get_attribute("innerHTML")
                is_expanded = STATE_EXPANDED in btn_html or LUCIDE_EXPANDED in btn_html
                if is_expanded:
                    self.driver.execute_script("arguments[0].click();", toggle_btn)
                    time.sleep(0.3)
                    self.driver.execute_script("arguments[0].click();", toggle_btn)
                else:
                    self.driver.execute_script("arguments[0].click();", toggle_btn)
                js_measure = """
                var btn = arguments[0];
                var wrapper = btn.closest('.code-block-container');
                if (wrapper) {
                    var editor = wrapper.querySelector('.monaco-editor');
                    if (editor) return editor.offsetHeight;
                }
                return 0;
                """
                block_height = 0
                for _ in range(15): 
                    h = self.driver.execute_script(js_measure, toggle_btn)
                    if h > 600:
                        block_height = h
                        break
                    time.sleep(0.2)
                if block_height == 0: 
                    block_height = self.driver.execute_script(js_measure, toggle_btn)
                js_audit = """
                var btn = arguments[0];
                var result = { scroll_parent: null };
                var p = btn.parentElement;
                while (p && p !== document.body) {
                    var style = window.getComputedStyle(p);
                    if ((style.overflowY === 'auto' || style.overflowY === 'scroll') && p.scrollHeight > p.clientHeight) {
                        result.scroll_parent = { tag: p.tagName };
                        p.setAttribute('data-ai-bridge-scroll-target', 'true');
                        break;
                    }
                    p = p.parentElement;
                }
                return result;
                """
                audit_data = self.driver.execute_script(js_audit, toggle_btn)
                if not audit_data.get('scroll_parent'): return
                target_h = block_height if block_height > 600 else 2000
                steps = math.ceil(target_h / 600)
                steps = min(steps, 50)
                js_scroll_step = """
                var target = document.querySelector('[data-ai-bridge-scroll-target="true"]');
                if (target) {
                    var before = target.scrollTop;
                    target.scrollBy(0, 600);
                    return { before: before, after: target.scrollTop };
                }
                return null;
                """
                for i in range(steps):
                    res = self.driver.execute_script(js_scroll_step)
                    if res:
                        if res['after'] - res['before'] <= 0: break
                    else: break
                    time.sleep(0.15)
                js_align_end = """
                var btn = arguments[0];
                var wrapper = btn.closest('.code-block-container');
                if (wrapper) wrapper.scrollIntoView({behavior: 'auto', block: 'end'});
                """
                self.driver.execute_script(js_align_end, toggle_btn)
        except Exception as e: pass

    def _get_valid_code_blocks(self, message_element):
        valid_blocks = []
        try:
            copy_xpath = ".//button[.//i[contains(@class, 'fa-copy')] or .//svg[contains(@class, 'lucide-copy')]]"
            all_copies = message_element.find_elements(By.XPATH, copy_xpath)
            for copy_btn in all_copies:
                if not copy_btn.is_displayed(): continue
                toggle_btn = self._find_sibling_toggle(copy_btn)
                if toggle_btn:
                    valid_blocks.append({ 'copy': copy_btn, 'toggle': toggle_btn })
        except: pass
        return valid_blocks

    def _find_sibling_toggle(self, anchor_element):
        parent = anchor_element
        for _ in range(5):
            try:
                parent = parent.find_element(By.XPATH, "..")
                # 同时匹配 FontAwesome <i> 和 Lucide <svg> 元素
                old_xpath = f".//i[{TARGET_XPATH}]"
                new_xpath = ".//svg[contains(@class, 'lucide-maximize-2') or contains(@class, 'lucide-minimize-2')]"
                xpath = f".//button[{old_xpath} or {new_xpath}]"
                toggles = parent.find_elements(By.XPATH, xpath)
                valid_toggles = [t for t in toggles if t != anchor_element and t.is_displayed()]
                if valid_toggles: return valid_toggles[0]
            except: break
        return None

    def scroll_to_bottom(self):
        """滚动聊天容器到底部"""
        try:
            target_xpath = SELECTORS["scroll_container_xpath"]
            js_scroll_bottom = """
            var container = document.evaluate(arguments[0], document, null, XPathResult.FIRST_ORDERED_NODE_TYPE, null).singleNodeValue;
            if (container) { 
                container.scrollTo({top: container.scrollHeight, behavior: 'smooth'}); 
            }
            """
            self.driver.execute_script(js_scroll_bottom, target_xpath)
        except Exception as e:
            print(f"⚠️ [Scroll] 滚动到底部失败: {e}")

    def clear_conversation(self, timeout=10):
        """Clear the current web chat and verify old chat items are gone."""
        try:
            self.switch_to_chat_tab()
            before = self.driver.execute_script("""
                var items = Array.from(document.querySelectorAll('.chat-item'));
                var last = items.length ? items[items.length - 1] : null;
                return {
                    count: items.length,
                    last_id: last ? (last.getAttribute('data-message-id') || last.getAttribute('data-id') || last.id || '') : ''
                };
            """) or {}

            self.driver.execute_script("""
                var selectors = ['.n-scrollbar-container', '.n-scrollbar-content'];
                selectors.forEach(function(sel) {
                    document.querySelectorAll(sel).forEach(function(el) {
                        try { el.scrollTop = el.scrollHeight; } catch (e) {}
                    });
                });
                try { window.scrollTo(0, document.body.scrollHeight); } catch (e) {}
            """)
            time.sleep(0.2)

            button = self._find_clear_button()
            if not button:
                if int(before.get("count") or 0) == 0:
                    return True, {
                        "stage": "resetting",
                        "reason": "already_empty",
                        "before_count": 0,
                        "after_count": 0,
                    }
                return False, {
                    "stage": "resetting",
                    "error_code": "clear_button_not_found",
                    "before_count": before.get("count", 0),
                    "before_last_id": before.get("last_id", ""),
                }

            self.driver.execute_script("arguments[0].click();", button)
            time.sleep(0.2)
            self._confirm_clear_dialog_if_present()
            before_last_id = str(before.get("last_id") or "")

            def cleared(driver):
                state = driver.execute_script("""
                    var items = Array.from(document.querySelectorAll('.chat-item'));
                    var ids = items.map(function(item) {
                        return item.getAttribute('data-message-id') || item.getAttribute('data-id') || item.id || '';
                    });
                    return { count: items.length, ids: ids };
                """) or {}
                if int(state.get("count") or 0) == 0:
                    return state
                if before_last_id and before_last_id not in (state.get("ids") or []):
                    return state
                return False

            final_state = WebDriverWait(self.driver, timeout).until(cleared)
            return True, {
                "stage": "resetting",
                "before_count": before.get("count", 0),
                "after_count": final_state.get("count", 0),
                "before_last_id": before_last_id,
            }
        except Exception as e:
            return False, {
                "stage": "resetting",
                "error_code": "reset_verify_failed",
                "error": str(e),
            }

    def _find_clear_button(self):
        try:
            return self.driver.execute_script("""
                var roots = Array.from(document.querySelectorAll('.aa-chat-input, .chat-input-box'));
                var buttons = roots.flatMap(function(root) {
                    return Array.from(root.querySelectorAll('button'));
                });
                if (!buttons.length) {
                    buttons = Array.from(document.querySelectorAll('button'));
                }
                function visible(el) {
                    var rect = el.getBoundingClientRect();
                    var style = window.getComputedStyle(el);
                    return rect.width > 0 && rect.height > 0 && style.visibility !== 'hidden' && style.display !== 'none';
                }
                var exact = buttons.find(function(btn) {
                    var text = (btn.innerText || btn.textContent || '').trim();
                    return visible(btn) && text === '清空';
                });
                if (exact) return exact;
                return buttons.find(function(btn) {
                    var text = (btn.innerText || btn.textContent || '').trim();
                    return visible(btn) && text.indexOf('清空') >= 0;
                }) || null;
            """)
        except Exception:
            return None

    def _confirm_clear_dialog_if_present(self):
        try:
            return bool(self.driver.execute_script("""
                var buttons = Array.from(document.querySelectorAll('button'));
                function visible(el) {
                    var rect = el.getBoundingClientRect();
                    var style = window.getComputedStyle(el);
                    return rect.width > 0 && rect.height > 0 && style.visibility !== 'hidden' && style.display !== 'none';
                }
                var candidates = buttons.filter(function(btn) {
                    var text = (btn.innerText || btn.textContent || '').trim();
                    return visible(btn) && /^(确认|确定|OK|Ok|ok|Yes|是)$/.test(text);
                });
                if (candidates.length) {
                    candidates[0].click();
                    return true;
                }
                return false;
            """))
        except Exception:
            return False

    def switch_to_chat_tab(self):
        try:
            def has_chat_surface():
                return (
                    len(self.find_elements(SELECTORS["chat_items"])) > 0
                    or len(self.find_elements(SELECTORS["input_area"])) > 0
                )

            if self.target_handle:
                try:
                    if self.driver.current_window_handle == self.target_handle:
                        if has_chat_surface():
                            return 
                except:
                    self.target_handle = None
            handles = self.driver.window_handles
            if len(handles) == 1: 
                self.target_handle = handles[0]
                return
            for handle in handles:
                self.driver.switch_to.window(handle)
                if "chrome://" in self.driver.current_url: continue
                if has_chat_surface(): 
                    self.target_handle = handle
                    return 
        except: pass
