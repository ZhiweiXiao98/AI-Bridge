"""登录页 — 输入服务器 IP / 端口 / 账号密码"""

import logging
import flet as ft

from state.app_state import AppState
from services.api import BridgeAPI

logger = logging.getLogger("mobile.login")


def build_login_page(page: ft.Page, state: AppState, on_login_success) -> ft.View:
    """构建登录页面"""

    # 默认登录信息
    import os
    saved_host = os.environ.get("BRIDGE_SERVER_HOST", "127.0.0.1")
    saved_port = os.environ.get("BRIDGE_SERVER_PORT", "8765")
    saved_user = os.environ.get("BRIDGE_SERVER_USER", "admin")
    _default_port = int(saved_port)

    host_input = ft.TextField(
        label="服务器 IP",
        value=saved_host,
        hint_text="192.168.1.x",
        prefix_icon=ft.Icons.COMPUTER,
        keyboard_type=ft.KeyboardType.TEXT,
        border_radius=12,
        expand=True,
    )
    port_input = ft.TextField(
        label="端口",
        value=str(saved_port),
        prefix_icon=ft.Icons.SETTINGS_ETHERNET,
        keyboard_type=ft.KeyboardType.NUMBER,
        width=100,
        border_radius=12,
    )
    user_input = ft.TextField(
        label="用户名",
        value=saved_user,
        prefix_icon=ft.Icons.PERSON_OUTLINE,
        border_radius=12,
    )
    pass_input = ft.TextField(
        label="密码",
        password=True,
        can_reveal_password=True,
        prefix_icon=ft.Icons.LOCK_OUTLINE,
        border_radius=12,
    )
    status_text = ft.Text("", size=13, color="#7f848e")

    async def handle_login(e):
        host = host_input.value.strip()
        port_str = port_input.value.strip()
        username = user_input.value.strip()
        password = pass_input.value

        if not host:
            status_text.value = "请输入服务器 IP"
            status_text.color = "#e06c75"
            page.update()
            return

        port = int(port_str) if port_str.isdigit() else _default_port

        status_text.value = "正在连接..."
        status_text.color = "#7f848e"
        page.update()

        try:
            api = BridgeAPI(host, port)
            result = await api.login(username, password)

            if result.get("status") == "ok":
                state.host = host
                state.port = port
                state.token = result["token"]
                state.role = result.get("role", "user")
                state.username = username
                state.display_name = result.get("display_name", username)
                state.device_id = api.device_id

                status_text.value = "连接成功"
                status_text.color = "#98c379"
                page.update()

                await on_login_success(api)
            else:
                status_text.value = f"登录失败: {result.get('message', '未知错误')}"
                status_text.color = "#e06c75"
                page.update()

        except Exception as ex:
            status_text.value = f"连接失败: {ex}"
            status_text.color = "#e06c75"
            logger.error("登录失败: %s", ex)
            page.update()

    login_button = ft.FilledButton(
        content="连 接",
        icon=ft.Icons.LOGIN,
        style=ft.ButtonStyle(
            shape=ft.RoundedRectangleBorder(radius=12),
            padding=ft.Padding.symmetric(horizontal=40, vertical=14),
        ),
        on_click=handle_login,
        width=280,
    )

    # 回车提交
    pass_input.on_submit = handle_login

    return ft.View(
        route="/",
        controls=[
            ft.SafeArea(
                expand=True,
                content=ft.Column(
                    expand=True,
                    alignment=ft.MainAxisAlignment.CENTER,
                    horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                    controls=[
                        ft.Container(
                            padding=ft.Padding.symmetric(horizontal=24, vertical=16),
                            content=ft.Column(
                                controls=[
                                    ft.Icon(ft.Icons.PHONE_ANDROID, size=64, color="#61afef"),
                                    ft.Text(
                                        "AI Bridge Mobile",
                                        size=28,
                                        weight=ft.FontWeight.BOLD,
                                        color="white",
                                        text_align=ft.TextAlign.CENTER,
                                    ),
                                    ft.Text(
                                        "局域网远程连接",
                                        size=14,
                                        color="#7f848e",
                                        text_align=ft.TextAlign.CENTER,
                                    ),
                                    ft.Container(height=24),
                                    ft.Row(
                                        controls=[host_input, port_input],
                                        spacing=8,
                                    ),
                                    user_input,
                                    pass_input,
                                    ft.Container(height=16),
                                    login_button,
                                    ft.Container(height=8),
                                    status_text,
                                ],
                                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                                spacing=4,
                            ),
                        ),
                    ],
                ),
            ),
        ],
        bgcolor="#1a1a1a",
        padding=0,
    )
