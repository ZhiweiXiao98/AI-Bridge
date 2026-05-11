from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional

from PySide6.QtCore import QPoint, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QMouseEvent, QPainter, QPen
from PySide6.QtWidgets import (
    QApplication, QFrame, QSizePolicy, QVBoxLayout, QWidget,
)


@dataclass
class _ReorderItem:
    item_id: str
    widget: QWidget
    wrapper: QFrame


class ReorderableCardItem(QFrame):
    drag_requested = Signal(object, object)
    drag_moved = Signal(object, object)
    drag_finished = Signal(object)

    def __init__(self, content_widget: QWidget, item_id: str, parent=None):
        super().__init__(parent)
        self.item_id = item_id
        self.content_widget = content_widget
        self._drag_handle: Optional[QWidget] = None
        self._press_pos: Optional[QPoint] = None
        self._drag_started = False
        self._drag_threshold = 6

        self.setObjectName('AnimatedReorderItem')
        self.setFrameShape(QFrame.NoFrame)
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(content_widget)

        self.setMouseTracking(True)

    def set_drag_handle(self, handle: Optional[QWidget]):
        if self._drag_handle is not None:
            self._drag_handle.removeEventFilter(self)
        self._drag_handle = handle
        if self._drag_handle is not None:
            self._drag_handle.installEventFilter(self)
            self._drag_handle.setCursor(Qt.OpenHandCursor)

    def eventFilter(self, watched, event):
        if watched is self._drag_handle:
            et = event.type()
            if et == QMouseEvent.Type.MouseButtonPress or et == QMouseEvent.Type.NonClientAreaMouseButtonPress:
                return self._handle_mouse_press(event)
            if et == QMouseEvent.Type.MouseMove or et == QMouseEvent.Type.NonClientAreaMouseMove:
                return self._handle_mouse_move(event)
            if et == QMouseEvent.Type.MouseButtonRelease or et == QMouseEvent.Type.NonClientAreaMouseButtonRelease:
                return self._handle_mouse_release(event)
        return super().eventFilter(watched, event)

    def _mouse_allowed(self, event: QMouseEvent) -> bool:
        return bool(event.button() == Qt.LeftButton or event.buttons() & Qt.LeftButton)

    def _handle_mouse_press(self, event: QMouseEvent):
        if event.button() != Qt.LeftButton:
            return False
        self._press_pos = event.globalPosition().toPoint()
        self._drag_started = False
        if self._drag_handle is not None:
            self._drag_handle.setCursor(Qt.ClosedHandCursor)
        return False

    def _handle_mouse_move(self, event: QMouseEvent):
        if self._press_pos is None or not self._mouse_allowed(event):
            return False
        global_pos = event.globalPosition().toPoint()
        if not self._drag_started:
            if (global_pos - self._press_pos).manhattanLength() < self._drag_threshold:
                return False
            self._drag_started = True
            self.drag_requested.emit(self, global_pos)
        self.drag_moved.emit(self, global_pos)
        return True

    def _handle_mouse_release(self, event: QMouseEvent):
        if self._drag_handle is not None:
            self._drag_handle.setCursor(Qt.OpenHandCursor)
        if self._drag_started:
            self.drag_finished.emit(self)
            self._drag_started = False
            self._press_pos = None
            return True
        self._press_pos = None
        return False


class AnimatedReorderContainer(QWidget):
    order_changed = Signal(list)
    drag_started = Signal(str)
    drag_moved = Signal(str, int)
    drag_finished = Signal(str, list)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName('AnimatedReorderContainer')
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setMouseTracking(True)

        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(8)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
        self._layout.setSizeConstraint(QVBoxLayout.SetMinimumSize)
        self._layout.setAlignment(Qt.AlignTop)

        self._items: List[_ReorderItem] = []
        self._item_map: Dict[str, _ReorderItem] = {}

        self._drag_item: Optional[_ReorderItem] = None
        self._drag_proxy: Optional[QFrame] = None
        self._placeholder: Optional[QWidget] = None
        self._drag_offset = QPoint()
        self._placeholder_index: int = -1
        self._drag_original_index: int = -1

        self._auto_scroll_timer = QTimer(self)
        self._auto_scroll_timer.timeout.connect(self._tick_auto_scroll)
        self._last_global_pos: Optional[QPoint] = None
        self._scroll_host: Optional[QWidget] = None

        self._drag_lerp_timer = QTimer(self)
        self._drag_lerp_timer.setInterval(16)
        self._drag_lerp_timer.timeout.connect(self._tick_drag_lerp)
        self._drag_target_local_pos: Optional[QPoint] = None

    def set_spacing(self, value: int):
        self._layout.setSpacing(value)
        self.updateGeometry()

    def set_scroll_host(self, scroll_area):
        self._scroll_host = scroll_area

    def sizeHint(self):
        margins = self._layout.contentsMargins()
        spacing = self._layout.spacing()
        total_height = margins.top() + margins.bottom()
        count = self._layout.count()
        for i in range(count):
            item = self._layout.itemAt(i)
            if item and item.widget():
                total_height += item.widget().sizeHint().height()
        if count > 1:
            total_height += spacing * (count - 1)
        width = max(super().sizeHint().width(), 1)
        return QSize(width, max(total_height, 1))

    def minimumSizeHint(self):
        return self.sizeHint()

    def clear_items(self):
        self._cancel_drag()
        while self._items:
            item = self._items.pop()
            self._layout.removeWidget(item.wrapper)
            item.wrapper.deleteLater()
        self._item_map.clear()
        self.updateGeometry()
        self.update()

    def add_item(self, item_id: str, widget: QWidget, drag_handle: Optional[QWidget] = None):
        wrapper = ReorderableCardItem(widget, item_id, self)
        wrapper.drag_requested.connect(self._on_drag_requested)
        wrapper.drag_moved.connect(self._on_drag_moved)
        wrapper.drag_finished.connect(self._on_drag_finished)
        wrapper.set_drag_handle(drag_handle)
        self._layout.addWidget(wrapper, 0, Qt.AlignTop)
        item = _ReorderItem(item_id=item_id, widget=widget, wrapper=wrapper)
        self._items.append(item)
        self._item_map[item_id] = item
        self.updateGeometry()

    def item_order(self) -> List[str]:
        return [item.item_id for item in self._items]

    def widget_for_item(self, item_id: str) -> Optional[QWidget]:
        item = self._item_map.get(item_id)
        return item.widget if item else None

    def _on_drag_requested(self, wrapper: ReorderableCardItem, global_pos: QPoint):
        item = self._item_from_wrapper(wrapper)
        if not item:
            return
        self._layout.activate()

        self._drag_item = item
        idx = self._items.index(item)
        self._drag_original_index = idx
        self._placeholder_index = idx
        self._last_global_pos = global_pos

        self._drag_offset = global_pos - wrapper.mapToGlobal(QPoint(0, 0))

        proxy = QFrame(self)
        proxy.setObjectName('AnimatedReorderDragProxy')
        proxy.setFrameShape(QFrame.NoFrame)
        proxy.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        proxy.setGeometry(wrapper.geometry())
        proxy.setStyleSheet('background: transparent; border: none;')
        content = wrapper.content_widget.grab()
        proxy._pixmap = content
        proxy.paintEvent = lambda event, p=proxy: self._paint_proxy(p)
        proxy.show()
        proxy.raise_()
        self._drag_proxy = proxy
        self._drag_target_local_pos = None
        self._drag_lerp_timer.start()

        layout_idx = self._layout.indexOf(wrapper)
        self._layout.removeWidget(wrapper)
        wrapper.hide()

        placeholder = QFrame(self)
        placeholder.setObjectName('AnimatedReorderPlaceholder')
        placeholder.setFixedHeight(wrapper.sizeHint().height())
        placeholder.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        placeholder.setStyleSheet(
            'background: rgba(95, 145, 255, 0.10); '
            'border: 2px solid rgba(95, 145, 255, 0.85); '
            'border-radius: 8px;'
        )
        self._placeholder = placeholder
        self._layout.insertWidget(layout_idx, placeholder)

        self.drag_started.emit(item.item_id)
        self._ensure_auto_scroll(True)

    def _paint_proxy(self, proxy: QFrame):
        painter = QPainter(proxy)
        painter.setRenderHint(QPainter.Antialiasing, True)
        if hasattr(proxy, '_pixmap'):
            painter.drawPixmap(0, 0, proxy._pixmap)
        pen = QPen(QColor(95, 145, 255, 180))
        pen.setWidth(2)
        painter.setPen(pen)
        painter.drawRoundedRect(proxy.rect().adjusted(1, 1, -1, -1), 8, 8)

    def _on_drag_moved(self, wrapper: ReorderableCardItem, global_pos: QPoint):
        if not self._drag_item or wrapper is not self._drag_item.wrapper:
            return
        self._last_global_pos = global_pos
        self._move_drag_proxy(global_pos)
        new_index = self._index_for_global_pos(global_pos)
        if new_index != self._placeholder_index:
            self._placeholder_index = new_index
            self._move_placeholder(new_index)
            self.drag_moved.emit(self._drag_item.item_id, new_index)

    def _on_drag_finished(self, wrapper: ReorderableCardItem):
        if not self._drag_item or wrapper is not self._drag_item.wrapper:
            return
        item_id = self._drag_item.item_id
        self._commit_reorder()
        self.drag_finished.emit(item_id, self.item_order())
        self.order_changed.emit(self.item_order())
        self._cleanup_drag_state()

    def _item_from_wrapper(self, wrapper: ReorderableCardItem) -> Optional[_ReorderItem]:
        for item in self._items:
            if item.wrapper is wrapper:
                return item
        return None

    def _move_drag_proxy(self, global_pos: QPoint):
        if not self._drag_proxy:
            return
        self._drag_target_local_pos = self.mapFromGlobal(global_pos - self._drag_offset)
        self._drag_proxy.raise_()

    def _tick_drag_lerp(self):
        if not self._drag_proxy or self._drag_target_local_pos is None:
            return
        cur = self._drag_proxy.pos()
        tgt = self._drag_target_local_pos
        f = 0.4
        nx = int(cur.x() + (tgt.x() - cur.x()) * f)
        ny = int(cur.y() + (tgt.y() - cur.y()) * f)
        if abs(nx - tgt.x()) <= 1 and abs(ny - tgt.y()) <= 1:
            nx, ny = tgt.x(), tgt.y()
        self._drag_proxy.move(QPoint(nx, ny))

    def _index_for_global_pos(self, global_pos: QPoint) -> int:
        local = self.mapFromGlobal(global_pos)
        index = 0
        for i in range(self._layout.count()):
            w = self._layout.itemAt(i).widget()
            if w is None or w is self._placeholder:
                continue
            rect = w.geometry()
            mid_y = rect.top() + rect.height() // 2
            if local.y() <= mid_y:
                return index
            index += 1
        return index

    def _move_placeholder(self, target_index: int):
        if not self._placeholder:
            return
        self._layout.removeWidget(self._placeholder)
        self._layout.insertWidget(target_index, self._placeholder)
        self._layout.activate()

    def _commit_reorder(self):
        if not self._drag_item:
            return
        item = self._drag_item
        target = self._placeholder_index

        if self._placeholder:
            self._layout.removeWidget(self._placeholder)
            self._placeholder.deleteLater()
            self._placeholder = None

        self._layout.insertWidget(target, item.wrapper, 0, Qt.AlignTop)
        item.wrapper.show()

        current = [i for i in self._items if i is not item]
        target = max(0, min(target, len(current)))
        current.insert(target, item)
        self._items = current

        self._layout.activate()
        self.updateGeometry()

    def _cleanup_drag_state(self):
        self._drag_lerp_timer.stop()
        self._drag_target_local_pos = None
        if self._drag_proxy:
            self._drag_proxy.deleteLater()
            self._drag_proxy = None
        if self._placeholder:
            self._layout.removeWidget(self._placeholder)
            self._placeholder.deleteLater()
            self._placeholder = None
        if self._drag_item and self._drag_item.wrapper:
            self._drag_item.wrapper.setGraphicsEffect(None)
        self._drag_item = None
        self._drag_original_index = -1
        self._placeholder_index = -1
        self._ensure_auto_scroll(False)
        self.updateGeometry()
        self.update()

    def _cancel_drag(self):
        if not self._drag_item:
            return
        item = self._drag_item

        if self._placeholder:
            self._layout.removeWidget(self._placeholder)
            self._placeholder.deleteLater()
            self._placeholder = None

        idx = min(self._drag_original_index, self._layout.count())
        self._layout.insertWidget(idx, item.wrapper, 0, Qt.AlignTop)
        item.wrapper.show()

        self._cleanup_drag_state()

    def _ensure_auto_scroll(self, enabled: bool):
        if enabled:
            self._auto_scroll_timer.start(30)
        else:
            self._auto_scroll_timer.stop()

    def _tick_auto_scroll(self):
        if self._drag_item and not (QApplication.mouseButtons() & Qt.LeftButton):
            self._cancel_drag()
            return
        if not self._drag_item or not self._scroll_host or self._last_global_pos is None:
            return
        viewport = getattr(self._scroll_host, 'viewport', lambda: None)()
        if viewport is None:
            return
        local = viewport.mapFromGlobal(self._last_global_pos)
        margin = 28
        delta = 0
        if local.y() < margin:
            delta = -12
        elif local.y() > viewport.height() - margin:
            delta = 12
        if delta:
            bar = self._scroll_host.verticalScrollBar()
            bar.setValue(bar.value() + delta)
            self._move_drag_proxy(self._last_global_pos)
            new_index = self._index_for_global_pos(self._last_global_pos)
            if new_index != self._placeholder_index:
                self._placeholder_index = new_index
                self._move_placeholder(new_index)

    def hideEvent(self, event):
        self._cancel_drag()
        return super().hideEvent(event)

    def focusOutEvent(self, event):
        if self._drag_item and not (QApplication.mouseButtons() & Qt.LeftButton):
            self._cancel_drag()
        return super().focusOutEvent(event)
