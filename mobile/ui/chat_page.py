"""聊天主页面 — 消息列表 + 输入栏 + WebSocket 事件驱动"""

import asyncio
import logging
import flet as ft

from state.app_state import AppState
from services.api import BridgeAPI
from services.ws_client import WSClient
from services.message_parser import parse_messages
from ui.components.message_bubble import build_message_bubble
from ui.components.status_bar import build_status_bar
from ui.session_drawer import build_session_drawer
from utils.ui_helpers import show_snack

logger = logging.getLogger("mobile.chat")


def build_chat_page(page: ft.Page, state: AppState, api: BridgeAPI, ws: WSClient) -> ft.View:
    """构建聊天主页面"""

    # ─── 消息列表 ───
    message_list = ft.ListView(
        expand=True,
        spacing=4,
        padding=ft.Padding.only(bottom=8),
        auto_scroll=True,
    )

    # ─── 置顶按钮 ───
    scroll_top_btn = ft.FloatingActionButton(
        icon=ft.Icons.VERTICAL_ALIGN_TOP,
        bgcolor="#61afef",
        foreground_color="white",
        mini=True,
        visible=False,
    )

    def scroll_to_top(e):
        message_list.scroll_to(offset=0, duration=300)
        scroll_top_btn.visible = False
        try:
            scroll_top_btn.update()
        except Exception:
            pass

    scroll_top_btn.on_click = scroll_to_top

    # ─── 流式加载指示器 ───
    streaming_indicator = ft.Container(
        visible=False,
        content=ft.Row(
            controls=[
                ft.ProgressRing(width=16, height=2, color="#61afef"),
                ft.Text("AI 正在回复...", size=13, color="#7f848e", italic=True),
            ],
            spacing=8,
        ),
        padding=ft.Padding.only(left=16, bottom=8),
    )

    # ─── 输入栏 ───
    input_field = ft.TextField(
        hint_text="输入消息...",
        border=ft.InputBorder.OUTLINE,
        border_radius=24,
        filled=True,
        fill_color="#2d2d2d",
        hint_style=ft.TextStyle(color="#7f848e"),
        text_style=ft.TextStyle(color="white"),
        expand=True,
        multiline=True,
        max_lines=4,
        min_lines=1,
        content_padding=ft.Padding.symmetric(horizontal=16, vertical=10),
    )

    send_button = ft.IconButton(
        icon=ft.Icons.SEND_ROUNDED,
        icon_color="#61afef",
        icon_size=24,
    )

    input_row = ft.Container(
        content=ft.Row(
            controls=[input_field, send_button],
            spacing=4,
            vertical_alignment=ft.CrossAxisAlignment.END,
        ),
        padding=ft.Padding.all(8),
        bgcolor="#1e1e1e",
    )

    # ─── 内部函数 ───

    def refresh_messages():
        try:
            message_list.controls.clear()
            for msg in state.messages:
                bubble = build_message_bubble(
                    msg,
                    on_code_apply=_handle_code_apply if state.mode == "browser" else None,
                )
                message_list.controls.append(bubble)
            if state.streaming_active and state.streaming_content:
                from services.message_parser import ParsedMessage, TextSegment
                stream_msg = ParsedMessage(
                    role="AI",
                    segments=[TextSegment(content=state.streaming_content)],
                )
                message_list.controls.append(build_message_bubble(stream_msg))
            message_list.update()
            # 消息超过 3 条时显示置顶按钮
            if len(state.messages) > 3:
                scroll_top_btn.visible = True
                try:
                    scroll_top_btn.update()
                except Exception:
                    pass
        except Exception:
            pass

    async def load_messages():
        try:
            raw = await api.sync_messages()
            state.messages = parse_messages(raw)
            refresh_messages()
        except Exception as e:
            logger.warning("加载消息失败: %s", e)

    async def load_sessions():
        try:
            state.sessions = await api.sync_sessions()
        except Exception as e:
            logger.warning("加载会话失败: %s", e)

    async def handle_send(e):
        text = input_field.value.strip()
        if not text:
            return
        input_field.value = ""
        input_field.update()
        try:
            if state.mode == "api":
                await ws.send_text_api(text)
            else:
                await ws.send_text_browser(text)
        except Exception as ex:
            logger.error("发送失败: %s", ex)
            show_snack(page, f"发送失败: {ex}", bgcolor="#e06c75")

    send_button.on_click = handle_send
    input_field.on_submit = handle_send

    # ─── WebSocket 通知处理器 ───

    _last_msg_sync_ts: float = 0
    _msg_syncing: bool = False

    async def on_notify_messages(payload, p):
        nonlocal _last_msg_sync_ts, _msg_syncing
        now = asyncio.get_event_loop().time()
        # 防抖：流式期间每 1.5s 最多同步一次，避免每 0.3s 一次全量 HTTP 拉取
        # 同时跳过正在进行中的同步
        if now - _last_msg_sync_ts < 1.5 or _msg_syncing:
            return
        _last_msg_sync_ts = now
        _msg_syncing = True
        try:
            await load_messages()
        finally:
            _msg_syncing = False

    _last_sess_sync_ts: float = 0
    _sess_syncing: bool = False

    async def on_notify_sessions(payload, p):
        nonlocal _last_sess_sync_ts, _sess_syncing
        now = asyncio.get_event_loop().time()
        if now - _last_sess_sync_ts < 2.0 or _sess_syncing:
            return
        _last_sess_sync_ts = now
        _sess_syncing = True
        try:
            await load_sessions()
        finally:
            _sess_syncing = False

    async def on_status(payload, p):
        state.status_text = str(payload)
        _update_status_bar(p)

    async def on_ai_state(payload, p):
        if isinstance(payload, dict):
            state.ai_state = payload.get("state", "idle")
        else:
            state.ai_state = str(payload)
        try:
            _update_status_bar(p)
            streaming_indicator.visible = state.ai_state in ("thinking", "streaming")
            streaming_indicator.update()
        except Exception:
            pass

    async def on_stream_chunk(payload, p):
        if not isinstance(payload, dict):
            return
        status = payload.get("status", "")
        content = payload.get("content", "")
        stream_id = payload.get("stream_id", "")
        if status == "started":
            state.streaming_active = True
            state.streaming_content = ""
            state.current_stream_id = stream_id
        elif status == "streaming":
            state.streaming_content += content
        elif status in ("completed", "error", "cancelled"):
            state.streaming_active = False
            state.streaming_content = ""
            state.current_stream_id = ""
        refresh_messages()

    async def on_pong(payload, p):
        _update_status_bar(p)

    ws.on("notify_messages", on_notify_messages)
    ws.on("notify_sessions", on_notify_sessions)
    ws.on("status", on_status)
    ws.on("ai_state", on_ai_state)
    ws.on("api_stream_chunk", on_stream_chunk)
    ws.on("api_stream_status", on_stream_chunk)
    ws.on("pong", on_pong)

    # ─── 日志接收 ───
    log_buffer: list[str] = []
    MAX_LOG_LINES = 200

    async def on_server_log(payload, p):
        if isinstance(payload, dict):
            text = payload.get("text", "")
        else:
            text = str(payload)
        if text:
            log_buffer.append(text)
            if len(log_buffer) > MAX_LOG_LINES:
                log_buffer.pop(0)

    ws.on("server_log", on_server_log)

    def _open_logs(e):
        log_text = "\n".join(log_buffer) if log_buffer else "暂无日志"
        # 截断过长文本
        if len(log_text) > 5000:
            log_text = "...\n" + log_text[-5000:]
        try:
            dlg = ft.AlertDialog(
                title=ft.Text("服务端日志", color="white"),
                content=ft.Container(
                    content=ft.TextField(
                        value=log_text,
                        multiline=True,
                        read_only=True,
                        text_style=ft.TextStyle(font_family="monospace", size=11, color="#abb2bf"),
                        bgcolor="#1e1e1e",
                        border=ft.InputBorder.NONE,
                        min_lines=10,
                        max_lines=20,
                    ),
                    width=400,
                ),
                actions=[
                    ft.TextButton("关闭", on_click=lambda ev: page.close(dlg)),
                ],
                bgcolor="#252526",
            )
            page.open(dlg)
        except Exception:
            pass

    # ─── 导航回调 ───

    def _open_settings(e):
        from ui.settings_page import build_settings_page
        page.views.append(build_settings_page(page, state, _close_settings))
        page.update()

    def _close_settings():
        if len(page.views) > 1:
            page.views.pop()
            page.update()

    def _open_drawer(e):
        try:
            drawer = build_session_drawer(state.sessions, handle_session_select, handle_new_chat)
            page.drawer = drawer
            page.open(drawer)
        except Exception as ex:
            logger.warning("打开抽屉失败: %s", ex)

    # ─── 会话回调 ───

    async def handle_session_select(index: int):
        try:
            await ws.switch_session(index)
            state.current_session_index = index
            # 等服务端 notify_messages 通知触发 load_messages，无需 sleep
        except Exception as e:
            logger.warning("切换会话失败: %s", e)

    async def handle_new_chat():
        try:
            await ws.new_chat()
            # 等服务端通知触发 load_messages / load_sessions，无需 sleep
        except Exception as e:
            logger.warning("新建对话失败: %s", e)

    # ─── 状态栏 ───

    def _update_status_bar(p):
        try:
            p.appbar = build_status_bar(
                state,
                on_menu_click=_open_drawer,
                on_settings_click=_open_settings,
            )
            p.update()
        except Exception:
            pass

    def _handle_code_apply(code: str):
        prompt = f"请将当前代码替换为：\n```\n{code}\n```"
        input_field.value = prompt
        input_field.update()

    # ─── 启动加载 ───

    async def init_chat():
        state.connected = ws.connected
        await ws.start_loops(page)
        await load_messages()
        await load_sessions()
        try:
            await ws.request_sync()
        except Exception:
            pass
        _update_status_bar(page)

    page.run_task(init_chat)

    # ─── 组装 View ───

    _appbar = build_status_bar(
        state,
        on_menu_click=_open_drawer,
        on_settings_click=_open_settings,
    )
    # 在 settings 按钮前插入日志按钮
    _appbar.actions.insert(
        len(_appbar.actions) - 1 if _appbar.actions else 0,
        ft.IconButton(
            icon=ft.Icons.ARTICLE_OUTLINED,
            icon_color="#7f848e",
            icon_size=20,
            tooltip="查看日志",
            on_click=_open_logs,
        ),
    )

    return ft.View(
        route="/chat",
        appbar=_appbar,
        controls=[
            message_list,
            streaming_indicator,
            input_row,
        ],
        bgcolor="#1a1a1a",
        padding=0,
        floating_action_button=scroll_top_btn,
    )
