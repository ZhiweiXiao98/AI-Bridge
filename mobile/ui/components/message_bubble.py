"""消息气泡组件 — AI / User 消息"""

import flet as ft
from .code_block import build_code_block
from services.html_converter import html_to_markdown


def build_message_bubble(msg, on_code_apply=None) -> ft.Container:
    """构建消息气泡

    Args:
        msg: ParsedMessage 对象
        on_code_apply: 代码"应用修改"回调
    """
    is_user = msg.role.upper() == "USER"

    # 头像 & 角色标签
    avatar = ft.CircleAvatar(
        content=ft.Text("U" if is_user else "AI", size=12, weight=ft.FontWeight.BOLD),
        bgcolor="#4a6fa5" if is_user else "#61afef",
        radius=16,
    )
    role_label = ft.Text(
        "你" if is_user else "AI",
        size=12,
        weight=ft.FontWeight.W_600,
        color="#abb2bf" if is_user else "#61afef",
    )

    # 构建内容块
    content_controls = []
    for seg in msg.segments:
        if seg.type == "text":
            raw = seg.content.strip()
            if not raw:
                continue
            # HTML → Markdown
            text = html_to_markdown(raw)
            if not text:
                continue
            content_controls.append(ft.Markdown(
                text,
                selectable=True,
                extension_set=ft.MarkdownExtensionSet.GITHUB_WEB,
                code_theme=ft.MarkdownCodeTheme.GITHUB,
                code_style_sheet=ft.MarkdownStyleSheet(
                    code_text_style=ft.TextStyle(
                        font_family="monospace",
                        size=13,
                    ),
                ),
            ))
        elif seg.type == "code":
            content_controls.append(build_code_block(seg, on_apply=on_code_apply))
        elif seg.type == "image":
            if seg.content:
                try:
                    content_controls.append(ft.Image(
                        src=seg.content,
                        fit=ft.BoxFit.CONTAIN,
                        border_radius=8,
                    ))
                except Exception:
                    content_controls.append(ft.Text(
                        f"[图片: {seg.content[:50]}]",
                        color="#7f848e",
                        italic=True,
                    ))
        elif seg.type == "tool_result":
            icon = ft.Icons.CHECK_CIRCLE if seg.success else ft.Icons.ERROR
            color = "#98c379" if seg.success else "#e06c75"
            tool_text = html_to_markdown(seg.content)[:300] if seg.content else ""
            if tool_text:
                content_controls.append(ft.Container(
                    content=ft.Column([
                        ft.Row([
                            ft.Icon(icon, size=16, color=color),
                            ft.Text(
                                f"[{seg.tool_name}]",
                                size=12,
                                weight=ft.FontWeight.W_500,
                                color=color,
                            ),
                        ], spacing=6),
                        ft.Text(tool_text, size=12, color="#abb2bf", selectable=True),
                    ], spacing=4),
                    bgcolor="#252526",
                    border_radius=6,
                    padding=8,
                    margin=ft.Margin.only(top=4),
                ))

    if not content_controls:
        content_controls.append(ft.Text("(空消息)", color="#7f848e", italic=True))

    # 气泡容器
    bubble = ft.Container(
        content=ft.Column(controls=content_controls, spacing=4),
        bgcolor="#2d2d2d" if not is_user else "#1a3a5c",
        border_radius=12,
        padding=12,
        margin=ft.Margin.only(
            left=8 if not is_user else 48,
            right=48 if not is_user else 8,
            top=4,
            bottom=4,
        ),
    )

    # 头部行（头像 + 角色）
    header = ft.Row(
        controls=[avatar, role_label],
        spacing=8,
        alignment=ft.MainAxisAlignment.START if not is_user else ft.MainAxisAlignment.END,
    )

    return ft.Container(
        content=ft.Column(
            controls=[header, bubble],
            spacing=4,
            horizontal_alignment=ft.CrossAxisAlignment.START if not is_user else ft.CrossAxisAlignment.END,
        ),
        margin=ft.Margin.only(bottom=8),
    )
