"""顶部状态栏 — 连接状态 / AI 状态 / 延迟"""

import flet as ft


def build_status_bar(state, on_menu_click=None, on_settings_click=None) -> ft.AppBar:
    """构建顶部状态栏

    Args:
        state: AppState 实例
        on_menu_click: 菜单按钮回调（打开会话侧边栏）
    """
    # 连接状态指示灯
    if state.connected:
        dot_color = "#98c379"  # 绿色
        status_text = f"已连接 {state.latency_ms}ms"
    else:
        dot_color = "#e06c75"  # 红色
        status_text = "未连接"

    dot = ft.Container(
        width=8,
        height=8,
        bgcolor=dot_color,
        border_radius=4,
    )

    # AI 状态
    ai_text = ""
    if state.ai_state == "thinking":
        ai_text = " | AI 思考中..."
    elif state.ai_state == "streaming":
        ai_text = " | AI 回复中..."

    # 模式标签
    mode_label = "API" if state.mode == "api" else "浏览器"

    status_label = ft.Text(
        f"{status_text}{ai_text} [{mode_label}]",
        size=12,
        color="#7f848e",
    )

    return ft.AppBar(
        leading=ft.IconButton(
            icon=ft.Icons.MENU,
            on_click=on_menu_click,
            icon_color="#abb2bf",
        ),
        title=ft.Row(
            controls=[
                ft.Text("AI Bridge", size=16, weight=ft.FontWeight.BOLD, color="white"),
                dot,
                status_label,
            ],
            spacing=8,
            tight=True,
        ),
        bgcolor="#1e1e1e",
        actions=[
            ft.IconButton(
                icon=ft.Icons.SETTINGS_OUTLINED,
                on_click=on_settings_click,
                icon_color="#7f848e",
            ),
        ],
    )
