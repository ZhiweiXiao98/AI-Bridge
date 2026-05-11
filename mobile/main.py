"""AI Bridge Mobile — Flet 入口 + 页面路由"""

import asyncio
import logging
import flet as ft

from state.app_state import AppState
from services.api import BridgeAPI
from services.ws_client import WSClient
from ui.login_page import build_login_page
from ui.chat_page import build_chat_page
from utils.ui_helpers import show_snack

# ─── 日志配置 ───
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger("mobile.main")

# ─── 全局状态 ───
state = AppState()
api: BridgeAPI | None = None
ws: WSClient | None = None


def main(page: ft.Page):
    global api, ws

    page.title = "AI Bridge Mobile"
    page.theme_mode = ft.ThemeMode.DARK
    page.bgcolor = "#1a1a1a"
    page.padding = 0

    page.theme = ft.Theme(
        color_scheme_seed="#61afef",
        visual_density=ft.VisualDensity.COMPACT,
    )

    def navigate_to(route: str):
        """导航到指定路由"""
        page.views.clear()
        if route == "/chat" and api and ws:
            page.views.append(build_chat_page(page, state, api, ws))
        else:
            page.views.append(build_login_page(page, state, on_login_success))
        page.update()

    async def on_login_success(bridge_api: BridgeAPI):
        """登录成功后：连接 WebSocket → 跳转聊天页"""
        global api, ws
        api = bridge_api

        try:
            ws = WSClient(api.ws_url)
            await ws.connect()
            state.connected = True
            navigate_to("/chat")
        except Exception as e:
            logger.error("WebSocket 连接失败: %s", e)
            show_snack(page, f"WebSocket 连接失败: {e}", bgcolor="#e06c75")

    def route_change(e):
        navigate_to(page.route)

    def view_pop(e):
        if len(page.views) > 1:
            page.views.pop()
            page.update()

    page.on_route_change = route_change
    page.on_view_pop = view_pop

    navigate_to("/")


if __name__ == "__main__":
    ft.run(main)
