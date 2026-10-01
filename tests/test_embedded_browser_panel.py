import builtins
import importlib.util
import sys
import types
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "app" / "ui" / "components" / "panels" / "browser_panel.py"


class DummySignal:
    def __init__(self, *args, **kwargs):
        self._slots = []

    def connect(self, slot):
        self._slots.append(slot)

    def emit(self, *args, **kwargs):
        for slot in self._slots:
            slot(*args, **kwargs)


class DummyQUrl:
    def __init__(self, value=""):
        self._value = str(value or "")
        self._local_path = ""

    @classmethod
    def fromLocalFile(cls, path):
        url = cls("file:///" + str(path).replace("\\", "/"))
        url._local_path = str(path)
        return url

    def toString(self):
        return self._value

    def isLocalFile(self):
        return bool(self._local_path) or self._value.startswith("file:")

    def toLocalFile(self):
        if self._local_path:
            return self._local_path
        return self._value.replace("file:///", "")


class DummyObject:
    def __init__(self, *args, **kwargs):
        self._text = ""
        self._html = ""
        self.clicked = DummySignal()
        self.returnPressed = DummySignal()
        self.sourceChanged = DummySignal()

    def __getattr__(self, name):
        def method(*args, **kwargs):
            return None
        return method

    def setText(self, text):
        self._text = text

    def text(self):
        return self._text

    def setHtml(self, html):
        self._html = html

    def toHtml(self):
        return self._html


class DummyComboBox(DummyObject):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.currentIndexChanged = DummySignal()
        self._items = []
        self._current_index = -1

    def addItem(self, label, data=None):
        self._items.append((label, data))
        if self._current_index < 0:
            self._current_index = 0

    def findData(self, data):
        for index, (_, item_data) in enumerate(self._items):
            if item_data == data:
                return index
        return -1

    def itemData(self, index):
        if 0 <= index < len(self._items):
            return self._items[index][1]
        return None

    def currentIndex(self):
        return self._current_index

    def setCurrentIndex(self, index):
        self._current_index = index

    def blockSignals(self, blocked):
        return False


class DummyTabWidget(DummyObject):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.currentChanged = DummySignal()
        self.tabCloseRequested = DummySignal()
        self._tabs = []
        self._current_index = -1

    def addTab(self, widget, title):
        self._tabs.append((widget, title))
        self._current_index = len(self._tabs) - 1
        return self._current_index

    def setCurrentIndex(self, index):
        self._current_index = index

    def currentIndex(self):
        return self._current_index

    def removeTab(self, index):
        if 0 <= index < len(self._tabs):
            self._tabs.pop(index)
            self._current_index = min(index, len(self._tabs) - 1)

    def setTabText(self, index, title):
        if 0 <= index < len(self._tabs):
            widget, _ = self._tabs[index]
            self._tabs[index] = (widget, title)

    def setTabsClosable(self, closable):
        self._tabs_closable = closable


class DummyLayout(DummyObject):
    def addWidget(self, *args, **kwargs):
        return None

    def addStretch(self, *args, **kwargs):
        return None


class DummyDockablePanel(DummyObject):
    minimize_requested = DummySignal()
    docked = DummySignal()
    closed = DummySignal()

    def __init__(self, panel_id, title, icon_name="", parent=None):
        super().__init__()
        self.panel_id = panel_id
        self.panel_title = title
        self.icon_name = icon_name
        self._widget = None

    def init_content(self):
        self._widget = self.create_content()

    def setWidget(self, widget):
        self._widget = widget

    def widget(self):
        return self._widget

    def apply_theme(self):
        return None


def import_browser_panel(monkeypatch, tmp_path):
    qt_core = types.ModuleType("PySide6.QtCore")
    qt_core.QUrl = DummyQUrl
    qt_core.Signal = DummySignal
    qt_core.Qt = types.SimpleNamespace(
        CursorShape=types.SimpleNamespace(PointingHandCursor=1),
    )

    qt_widgets = types.ModuleType("PySide6.QtWidgets")
    for name in (
        "QFileDialog",
        "QFrame",
        "QLabel",
        "QLineEdit",
        "QPushButton",
        "QTextBrowser",
        "QWidget",
    ):
        setattr(qt_widgets, name, DummyObject)
    qt_widgets.QComboBox = DummyComboBox
    qt_widgets.QTabWidget = DummyTabWidget
    qt_widgets.QHBoxLayout = DummyLayout
    qt_widgets.QVBoxLayout = DummyLayout
    qt_widgets.QSizePolicy = types.SimpleNamespace(
        Policy=types.SimpleNamespace(Expanding=1)
    )

    app_constants = types.ModuleType("app.core.app_constants")
    app_constants.APP_ROOT = str(tmp_path)

    dockable_panel = types.ModuleType("app.ui.components.dockable_panel")
    dockable_panel.DockablePanel = DummyDockablePanel

    palette = types.SimpleNamespace(
        BG_PRIMARY="#101114",
        BG_SECONDARY="#181a20",
        BG_TERTIARY="#27272a",
        BORDER="#3f3f46",
        TEXT_PRIMARY="#e5e7eb",
        TEXT_SECONDARY="#a1a1aa",
        ACCENT_PRIMARY="#38bdf8",
    )
    theme = types.ModuleType("app.ui.theme")
    theme.theme_manager = types.SimpleNamespace(get_palette=lambda: palette)

    monkeypatch.setitem(sys.modules, "PySide6.QtCore", qt_core)
    monkeypatch.setitem(sys.modules, "PySide6.QtWidgets", qt_widgets)
    monkeypatch.setitem(sys.modules, "app.core.app_constants", app_constants)
    monkeypatch.setitem(sys.modules, "app.ui.components.dockable_panel", dockable_panel)
    monkeypatch.setitem(sys.modules, "app.ui.theme", theme)

    module_name = "test_browser_panel_module"
    sys.modules.pop(module_name, None)
    spec = importlib.util.spec_from_file_location(module_name, MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def test_normalize_browser_url_adds_https_for_plain_domain(monkeypatch, tmp_path):
    module = import_browser_panel(monkeypatch, tmp_path)

    url = module.normalize_browser_url("example.com")

    assert url.toString() == "https://example.com"


def test_normalize_browser_url_accepts_existing_scheme(monkeypatch, tmp_path):
    module = import_browser_panel(monkeypatch, tmp_path)

    url = module.normalize_browser_url("http://localhost:3000/view.html")

    assert url.toString() == "http://localhost:3000/view.html"


def test_normalize_browser_url_converts_local_file(monkeypatch, tmp_path):
    module = import_browser_panel(monkeypatch, tmp_path)
    html_path = tmp_path / "scene.html"
    html_path.write_text("<html><body>scene</body></html>", encoding="utf-8")

    url = module.normalize_browser_url(str(html_path))

    assert url.isLocalFile()
    assert Path(url.toLocalFile()) == html_path


def test_webengine_runtime_loader_is_safe_when_import_fails(monkeypatch, tmp_path):
    module = import_browser_panel(monkeypatch, tmp_path)
    real_import = builtins.__import__

    def guarded_import(name, *args, **kwargs):
        if name.startswith("PySide6.QtWebEngine"):
            raise ImportError("simulated missing QtWebEngine")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guarded_import)

    runtime = module.load_webengine_runtime()

    assert runtime.available is False
    assert "simulated missing QtWebEngine" in runtime.error


def test_browser_panel_fallback_renders_html_and_blocks_javascript(monkeypatch, tmp_path):
    module = import_browser_panel(monkeypatch, tmp_path)
    runtime = module.WebEngineRuntime(available=False, error="missing for test")

    panel = module.BrowserPanel(runtime=runtime)
    panel.render_html("<html><body><h1>Digital Twin Preview</h1></body></html>")

    assert panel.render_mode == "fallback"
    assert panel.run_javascript("document.title") is False
    assert panel._fallback_browser is not None
    assert "Digital Twin Preview" in panel._fallback_browser.toHtml()


def test_compute_device_zoom_factor_fits_desktop_into_narrow_panel(monkeypatch, tmp_path):
    module = import_browser_panel(monkeypatch, tmp_path)

    zoom = module.compute_device_zoom_factor(640, 1280)

    assert zoom == 0.5


def test_foreground_visibility_script_keeps_page_visible(monkeypatch, tmp_path):
    module = import_browser_panel(monkeypatch, tmp_path)

    script = module.FOREGROUND_VISIBILITY_SCRIPT

    assert "visibilityState" in script
    assert "visible" in script
    assert "hidden" in script
    assert "hasFocus" in script


def test_browser_panel_fallback_supports_multiple_tabs_and_device_modes(monkeypatch, tmp_path):
    module = import_browser_panel(monkeypatch, tmp_path)
    runtime = module.WebEngineRuntime(available=False, error="missing for test")
    panel = module.BrowserPanel(runtime=runtime)

    first_tab = panel._current_tab()
    second_tab = panel.new_tab(html="<h1>Second</h1>", title="Second", device_mode="mobile")

    assert len(panel._tabs) == 2
    assert first_tab is not second_tab
    assert second_tab.device_mode == "mobile"
    assert panel._fallback_browser is second_tab.fallback
    assert "Second" in second_tab.fallback.toHtml()
