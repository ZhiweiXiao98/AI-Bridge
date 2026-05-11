"""会话侧边栏 — 会话列表 + 新建对话"""

import flet as ft


def build_session_drawer(sessions: list, on_select, on_new_chat) -> ft.NavigationDrawer:
    """构建会话侧边栏

    Args:
        sessions: 会话列表
        on_select: 选择会话回调 (index)
        on_new_chat: 新建对话回调
    """
    items = []

    # 标题
    items.append(ft.Container(
        content=ft.Text("会话列表", size=18, weight=ft.FontWeight.BOLD, color="white"),
        padding=ft.Padding.only(left=16, top=16, bottom=8),
    ))

    # 会话项
    if sessions:
        for i, session in enumerate(sessions):
            name = session.get("name", session.get("title", f"会话 {i + 1}"))
            is_active = session.get("active", False)
            items.append(ft.ListTile(
                leading=ft.Icon(
                    ft.Icons.CHAT_BUBBLE_OUTLINE,
                    color="#61afef" if is_active else "#7f848e",
                ),
                title=ft.Text(
                    name,
                    color="white" if is_active else "#abb2bf",
                    weight=ft.FontWeight.W_600 if is_active else ft.FontWeight.NORMAL,
                ),
                selected=is_active,
                selected_color="#61afef",
                on_click=lambda e, idx=i: on_select(idx),
            ))
    else:
        items.append(ft.Container(
            content=ft.Text("暂无会话", color="#7f848e", italic=True),
            padding=20,
        ))

    items.append(ft.Divider(color="#333333"))

    # 新建对话按钮
    items.append(ft.ListTile(
        leading=ft.Icon(ft.Icons.ADD_CIRCLE_OUTLINE, color="#98c379"),
        title=ft.Text("新建对话", color="#98c379", weight=ft.FontWeight.W_600),
        on_click=lambda e: on_new_chat(),
    ))

    return ft.NavigationDrawer(
        controls=items,
        bgcolor="#1e1e1e",
        elevation=16,
    )
