"""UI 辅助函数 — Flet 0.84 兼容"""

import flet as ft


def show_snack(page: ft.Page, message: str, bgcolor: str = "#333333", duration: int = 2000):
    """显示 SnackBar (Flet 0.84 兼容)"""
    sb = ft.SnackBar(
        content=ft.Text(message, color="white"),
        bgcolor=bgcolor,
        duration=duration,
        open=True,
    )
    page.overlay.append(sb)
    page.update()


def copy_to_clipboard(page: ft.Page, text: str, toast: str = "已复制到剪贴板"):
    """复制文本到剪贴板并显示提示"""
    page.clipboard = text
    page.update()
    show_snack(page, toast)
