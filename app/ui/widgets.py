# filename: app/ui/widgets.py
# 兼容层：重新导出新模块中的组件
from .components.base import ImageBox, ImageLoader
from .components.editor import CodeEditor, PythonHighlighter
from .components.chat import ChatBubble, CodeBox
from .components.input import ChatInput
from .components.session_item import SessionItemWidget # [New]