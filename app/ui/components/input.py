# filename: app/ui/components/input.py
import os, time, tempfile
from PySide6.QtWidgets import QTextEdit
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QImage

class ChatInput(QTextEdit):
    image_pasted_signal = Signal(str)
    enter_pressed_signal = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(45) 
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setAcceptRichText(False)
        self.setAcceptDrops(True)
        self.setStyleSheet("padding: 5px; font-family: Segoe UI Emoji, Apple Color Emoji, Noto Color Emoji, Segoe UI Symbol, Segoe UI, sans-serif; font-size: 14px;")
        self.setCursorWidth(2)

    def canInsertFromMimeData(self, source): return source.hasImage() or super().canInsertFromMimeData(source)
    
    def insertFromMimeData(self, source):
        if source.hasImage():
            image = QImage(source.imageData())
            if not image.isNull():
                t = int(time.time() * 1000)
                path = os.path.join(tempfile.gettempdir(), f"paste_{t}.png")
                image.save(path, "PNG")
                self.image_pasted_signal.emit(path)
                return 
        super().insertFromMimeData(source)

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and not (event.modifiers() & Qt.KeyboardModifier.ShiftModifier):
            self.enter_pressed_signal.emit()
            event.accept()
        else: super().keyPressEvent(event)

    def dragEnterEvent(self, event):
        if event.mimeData().hasText():
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dropEvent(self, event):
        if event.mimeData().hasText():
            cursor = self.textCursor()
            cursor.insertText(event.mimeData().text())
            self.setTextCursor(cursor)
            event.acceptProposedAction()
        else:
            super().dropEvent(event)