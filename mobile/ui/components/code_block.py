"""代码块组件 — pygments 语法高亮 + 复制 + 应用修改"""

import flet as ft
from pygments import lexers
from utils.ui_helpers import copy_to_clipboard
from pygments.token import Token
from pygments.util import ClassNotFound

# Pygments token 颜色映射（深色主题）
TOKEN_COLORS = {
    Token.Keyword: "#c678dd",
    Token.Keyword.Type: "#e5c07b",
    Token.Name.Function: "#61afef",
    Token.Name.Class: "#e5c07b",
    Token.Name.Builtin: "#e5c07b",
    Token.Name.Decorator: "#d19a66",
    Token.Name: "#e06c75",
    Token.Literal.String: "#98c379",
    Token.Literal.String.Doc: "#98c379",
    Token.Literal.Number: "#d19a66",
    Token.Operator: "#56b6c2",
    Token.Punctuation: "#abb2bf",
    Token.Comment: "#7f848e",
    Token.Comment.Single: "#7f848e",
    Token.Comment.Multiline: "#7f848e",
    Token.Text: "#abb2bf",
}


def _get_color(token_type) -> str:
    """根据 pygments token 类型返回颜色"""
    for tok, color in TOKEN_COLORS.items():
        if token_type in tok:
            return color
    # 回退：逐级向上查找
    parent = token_type
    while parent:
        for tok, color in TOKEN_COLORS.items():
            if parent in tok:
                return color
        parent = parent.parent
    return "#abb2bf"


def _highlight_code(code: str, language: str) -> list[ft.Text]:
    """用 pygments 分词，返回 Flet Text spans 列表"""
    try:
        lexer = lexers.get_lexer_by_name(language)
    except ClassNotFound:
        lexer = lexers.get_lexer_by_name("text")

    tokens = list(lexer.get_tokens(code))
    spans = []
    for token_type, value in tokens:
        # 处理换行
        color = _get_color(token_type)
        spans.append(ft.TextSpan(
            text=value,
            style=ft.TextStyle(
                color=color,
                font_family="monospace",
                size=13,
            ),
        ))
    return spans


def build_code_block(segment, on_apply=None) -> ft.Container:
    """构建带语法高亮的代码块

    Args:
        segment: CodeSegment 对象
        on_apply: 浏览器模式下点击"应用修改"的回调，接收 code 文本
    """
    # 语言标签
    lang_label = ft.Container(
        content=ft.Text(
            segment.language.upper(),
            size=11,
            color="#7f848e",
            weight=ft.FontWeight.W_500,
        ),
        padding=ft.Padding.only(left=12, top=8, bottom=2),
    )

    # 代码内容
    code_spans = _highlight_code(segment.content, segment.language)
    code_text = ft.Text(spans=code_spans, selectable=True)

    # 操作按钮行
    buttons = [
        ft.TextButton(
            "复制",
            icon=ft.Icons.COPY_OUTLINED,
            style=ft.ButtonStyle(
                color="#7f848e",
                text_style=ft.TextStyle(size=12),
            ),
            on_click=lambda e, c=segment.content: _copy_code(e, c),
        ),
    ]
    if on_apply:
        buttons.append(
            ft.TextButton(
                "应用修改",
                icon=ft.Icons.AUTO_FIX_HIGH,
                style=ft.ButtonStyle(
                    color="#61afef",
                    text_style=ft.TextStyle(size=12),
                ),
                on_click=lambda e, c=segment.content: on_apply(c),
            ),
        )

    action_row = ft.Row(
        controls=buttons,
        spacing=4,
        alignment=ft.MainAxisAlignment.END,
    )

    return ft.Container(
        content=ft.Column(
            controls=[
                lang_label,
                ft.Container(
                    content=code_text,
                    padding=ft.Padding.symmetric(horizontal=12, vertical=8),
                ),
                action_row,
            ],
            spacing=0,
        ),
        bgcolor="#1e1e1e",
        border_radius=8,
        border=ft.Border.all(1, "#333333"),
        margin=ft.Margin.symmetric(vertical=4),
    )


def _copy_code(e, code: str):
    """复制代码到剪贴板"""
    copy_to_clipboard(e.page, code)
