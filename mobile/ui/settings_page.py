"""设置页 — 模式切换 / 关于"""

import flet as ft
from state.app_state import AppState


def build_settings_page(page: ft.Page, state: AppState, on_back=None) -> ft.View:
    """构建设置页面"""

    mode_radio = ft.RadioGroup(
        value=state.mode,
        content=ft.Column(
            controls=[
                ft.Radio(value="browser", label="浏览器模式（通过 Chrome 中转）"),
                ft.Radio(value="api", label="API 模式（直接调用 LLM）"),
            ],
            spacing=4,
        ),
        on_change=lambda e: setattr(state, "mode", e.control.value),
    )

    def go_back(e):
        if on_back:
            on_back()
        else:
            if len(page.views) > 1:
                page.views.pop()
                page.update()

    return ft.View(
        route="/settings",
        controls=[
            ft.AppBar(
                leading=ft.IconButton(
                    icon=ft.Icons.ARROW_BACK,
                    on_click=go_back,
                    icon_color="#abb2bf",
                ),
                title=ft.Text("设置", color="white"),
                bgcolor="#1e1e1e",
            ),
            ft.Container(
                padding=20,
                content=ft.Column(
                    controls=[
                        ft.Text("交互模式", size=16, weight=ft.FontWeight.W_600, color="white"),
                        mode_radio,
                        ft.Divider(color="#333333"),
                        ft.Text("关于", size=16, weight=ft.FontWeight.W_600, color="white"),
                        ft.Text("AI Bridge Mobile v1.0", color="#7f848e"),
                        ft.Text(
                            f"服务器: {state.host}:{state.port}",
                            color="#7f848e",
                            size=13,
                        ),
                        ft.Text(
                            f"用户: {state.display_name or state.username} ({state.role})",
                            color="#7f848e",
                            size=13,
                        ),
                    ],
                    spacing=12,
                ),
            ),
        ],
        bgcolor="#1a1a1a",
    )
