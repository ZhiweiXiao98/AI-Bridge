# filename: app/ui/components/panels/browser_panel.py
"""
Embedded browser panel.

The panel prefers Qt WebEngine for Chromium-grade HTML/WebGL rendering and
falls back to QTextBrowser when the runtime environment does not provide the
QtWebEngine binaries. The fallback keeps the application bootable and still
supports lightweight HTML previews.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from PySide6.QtCore import QUrl, Signal, Qt
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QTabWidget,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from app.core.app_constants import APP_ROOT
from app.ui.components.dockable_panel import DockablePanel
from app.ui.theme import theme_manager


DEFAULT_HOME_HTML = """
<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>AI Bridge 内置浏览器</title>
  <style>
    :root { color-scheme: dark; font-family: "Microsoft YaHei", system-ui, sans-serif; }
    body { margin: 0; min-height: 100vh; background: #101114; color: #e5e7eb; display: grid; place-items: center; }
    main { width: min(880px, calc(100vw - 48px)); }
    h1 { font-size: 28px; margin: 0 0 12px; font-weight: 700; }
    p { color: #a1a1aa; line-height: 1.75; margin: 0 0 18px; }
    .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(190px, 1fr)); gap: 10px; }
    .tile { border: 1px solid #2f343d; background: #181a20; border-radius: 8px; padding: 14px; }
    .tile strong { display: block; margin-bottom: 6px; color: #f8fafc; }
    code { color: #7dd3fc; }
  </style>
</head>
<body>
  <main>
    <h1>内置浏览器已就绪</h1>
    <p>这里用于渲染 HTML 页面、文档预览、WebGL/Three.js/Cesium 数字孪生画面，以及本地可视化产物。</p>
    <div class="grid">
      <div class="tile"><strong>网页渲染</strong><span>输入 URL 或打开本地 HTML 文件。</span></div>
      <div class="tile"><strong>数字孪生</strong><span>Qt WebEngine 可承载 WebGL 场景。</span></div>
      <div class="tile"><strong>AI 维护友好</strong><span>面板公开 <code>load_url</code> / <code>render_html</code> / <code>run_javascript</code>。</span></div>
    </div>
  </main>
</body>
</html>
"""

DESKTOP_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/143.0.0.0 Safari/537.36"
)
MOBILE_USER_AGENT = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 18_2 like Mac OS X) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/18.2 Mobile/15E148 Safari/604.1"
)

DEVICE_MODES = {
    "desktop": {
        "label": "电脑网页",
        "target_width": 1280,
        "user_agent": DESKTOP_USER_AGENT,
    },
    "mobile": {
        "label": "手机网页",
        "target_width": 390,
        "user_agent": MOBILE_USER_AGENT,
    },
}

MIN_ZOOM_FACTOR = 0.35
MAX_ZOOM_FACTOR = 1.5

FOREGROUND_VISIBILITY_SCRIPT_NAME = "ai_bridge_foreground_visibility"
FOREGROUND_VISIBILITY_SCRIPT = r"""
(function() {
  if (window.__aiBridgeForegroundVisibilityInstalled) return;
  window.__aiBridgeForegroundVisibilityInstalled = true;

  function defineGetter(target, key, getter) {
    try {
      Object.defineProperty(target, key, { configurable: true, get: getter });
    } catch (e) {}
  }

  defineGetter(Document.prototype, 'hidden', function() { return false; });
  defineGetter(Document.prototype, 'visibilityState', function() { return 'visible'; });
  defineGetter(Document.prototype, 'webkitHidden', function() { return false; });
  defineGetter(Document.prototype, 'webkitVisibilityState', function() { return 'visible'; });

  try { Document.prototype.hasFocus = function() { return true; }; } catch (e) {}
  try { window.focus = function() {}; } catch (e) {}

  function foregroundTick() {
    try { document.dispatchEvent(new Event('visibilitychange')); } catch (e) {}
    try { window.dispatchEvent(new Event('focus')); } catch (e) {}
    try { document.dispatchEvent(new Event('focusin')); } catch (e) {}
  }

  foregroundTick();
  window.setInterval(foregroundTick, 1000);
})();
"""


@dataclass(frozen=True)
class WebEngineRuntime:
    available: bool
    error: str = ""
    QWebEngineView: Optional[type] = None
    QWebEnginePage: Optional[type] = None
    QWebEngineProfile: Optional[type] = None
    QWebEngineSettings: Optional[type] = None
    QWebEngineScript: Optional[type] = None


@dataclass
class BrowserTab:
    title: str
    widget: QWidget
    device_mode: str
    profile: Any = None
    view: Any = None
    fallback: QTextBrowser | None = None


def load_webengine_runtime() -> WebEngineRuntime:
    """Load Qt WebEngine lazily so the app can boot without its binaries."""
    try:
        from PySide6.QtWebEngineCore import (  # type: ignore
            QWebEnginePage,
            QWebEngineProfile,
            QWebEngineScript,
            QWebEngineSettings,
        )
        from PySide6.QtWebEngineWidgets import QWebEngineView  # type: ignore
    except Exception as exc:
        return WebEngineRuntime(available=False, error=f"{type(exc).__name__}: {exc}")

    return WebEngineRuntime(
        available=True,
        QWebEngineView=QWebEngineView,
        QWebEnginePage=QWebEnginePage,
        QWebEngineProfile=QWebEngineProfile,
        QWebEngineSettings=QWebEngineSettings,
        QWebEngineScript=QWebEngineScript,
    )


def normalize_browser_url(raw: str, cwd: str | os.PathLike[str] | None = None) -> QUrl:
    """Convert user input into a QUrl suitable for browser navigation."""
    value = (raw or "").strip()
    if not value:
        return QUrl("about:blank")

    lower = value.lower()
    if lower.startswith(("http://", "https://", "file://", "about:", "data:")):
        return QUrl(value)

    path = Path(value)
    if not path.is_absolute() and cwd:
        path = Path(cwd) / path
    if path.exists():
        return QUrl.fromLocalFile(str(path.resolve()))

    if "://" in value:
        return QUrl(value)
    return QUrl(f"https://{value}")


def _set_webengine_attribute(settings: Any, settings_cls: Any, name: str, enabled: bool) -> None:
    attr = getattr(settings_cls.WebAttribute, name, None)
    if attr is not None:
        settings.setAttribute(attr, enabled)


def _install_foreground_visibility_script(profile: Any, script_cls: Any) -> bool:
    """Make AI pages treat hidden embedded WebEngine tabs as visible foreground pages."""
    if profile is None or script_cls is None or not hasattr(profile, "scripts"):
        return False
    try:
        scripts = profile.scripts()
        for item in scripts.toList() if hasattr(scripts, "toList") else []:
            if getattr(item, "name", lambda: "")() == FOREGROUND_VISIBILITY_SCRIPT_NAME:
                return True

        script = script_cls()
        script.setName(FOREGROUND_VISIBILITY_SCRIPT_NAME)
        script.setSourceCode(FOREGROUND_VISIBILITY_SCRIPT)
        injection_point = getattr(script_cls.InjectionPoint, "DocumentCreation", None)
        if injection_point is not None:
            script.setInjectionPoint(injection_point)
        world_id = getattr(script_cls.ScriptWorldId, "MainWorld", None)
        if world_id is not None:
            script.setWorldId(world_id)
        script.setRunsOnSubFrames(True)
        scripts.insert(script)
        return True
    except Exception:
        return False


def _keep_page_lifecycle_active(page: Any) -> bool:
    """Best-effort Qt WebEngine lifecycle override for hidden/background pages."""
    if page is None or not hasattr(page, "setLifecycleState"):
        return False
    lifecycle = getattr(type(page), "LifecycleState", None)
    active = getattr(lifecycle, "Active", None) if lifecycle is not None else None
    if active is None:
        return False
    try:
        page.setLifecycleState(active)
        return True
    except Exception:
        return False


def compute_device_zoom_factor(view_width: int, target_width: int) -> float:
    """Scale pages so the chosen device layout fits inside the dock width."""
    if view_width <= 0 or target_width <= 0:
        return 1.0
    zoom = view_width / target_width
    return max(MIN_ZOOM_FACTOR, min(MAX_ZOOM_FACTOR, zoom))


class BrowserPanel(DockablePanel):
    """Dockable built-in browser for HTML pages and digital twin scenes."""

    page_title_changed = Signal(str)
    url_changed = Signal(str)
    render_mode_changed = Signal(str)

    def __init__(self, runtime: WebEngineRuntime | None = None):
        super().__init__("embedded_browser", "内置浏览器", "Web")
        self._runtime = runtime or load_webengine_runtime()
        self._profile = None
        self._view = None
        self._fallback_browser: QTextBrowser | None = None
        self._mode = "webengine" if self._runtime.available else "fallback"
        self._tabs: list[BrowserTab] = []
        self._active_device_mode = "desktop"
        self._tab_counter = 0
        self.init_content()

    @property
    def render_mode(self) -> str:
        return self._mode

    @property
    def webengine_error(self) -> str:
        return self._runtime.error

    def create_content(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        layout.addWidget(self._create_toolbar())
        layout.addWidget(self._create_status_strip())
        self.tab_widget = QTabWidget()
        self.tab_widget.setObjectName("browserTabs")
        self.tab_widget.setTabsClosable(True)
        self.tab_widget.currentChanged.connect(self._on_current_tab_changed)
        self.tab_widget.tabCloseRequested.connect(self.close_tab)
        layout.addWidget(self.tab_widget, 1)

        self.apply_content_theme()
        self.new_tab(html=DEFAULT_HOME_HTML, title="首页", device_mode="desktop")
        return widget

    def _create_toolbar(self) -> QWidget:
        toolbar = QWidget()
        toolbar.setObjectName("browserToolbar")
        row = QHBoxLayout(toolbar)
        row.setContentsMargins(6, 5, 6, 5)
        row.setSpacing(5)

        self.btn_back = self._tool_button("‹", "后退", self.go_back)
        self.btn_forward = self._tool_button("›", "前进", self.go_forward)
        self.btn_reload = self._tool_button("↻", "刷新", self.reload)
        self.btn_stop = self._tool_button("×", "停止加载", self.stop)
        self.btn_home = self._tool_button("⌂", "首页", self.go_home)
        self.btn_new_tab = self._tool_button("+", "新建标签页", self.new_tab)
        self.btn_file = self._tool_button("HTML", "打开本地 HTML", self.open_html_file)

        row.addWidget(self.btn_back)
        row.addWidget(self.btn_forward)
        row.addWidget(self.btn_reload)
        row.addWidget(self.btn_stop)
        row.addWidget(self.btn_home)
        row.addWidget(self.btn_new_tab)

        self.address_input = QLineEdit()
        self.address_input.setObjectName("browserAddress")
        self.address_input.setPlaceholderText("输入 URL、本地 HTML 路径，或域名")
        self.address_input.returnPressed.connect(self.load_address_bar)
        row.addWidget(self.address_input, 1)

        self.device_combo = QComboBox()
        self.device_combo.setObjectName("browserDeviceCombo")
        self.device_combo.setToolTip("切换当前标签页声明给网页的设备类型")
        self.device_combo.setMinimumWidth(78)
        for mode, config in DEVICE_MODES.items():
            self.device_combo.addItem(config["label"], mode)
        self.device_combo.currentIndexChanged.connect(self._on_device_combo_changed)
        row.addWidget(self.device_combo)

        self.btn_go = self._tool_button("Go", "打开地址", self.load_address_bar)
        row.addWidget(self.btn_go)
        row.addWidget(self.btn_file)

        return toolbar

    def _create_status_strip(self) -> QWidget:
        strip = QFrame()
        strip.setObjectName("browserStatusStrip")
        row = QHBoxLayout(strip)
        row.setContentsMargins(8, 3, 8, 3)
        row.setSpacing(8)

        mode_text = "Chromium WebEngine" if self._runtime.available else "轻量 HTML 预览"
        self.mode_label = QLabel(mode_text)
        self.mode_label.setObjectName("browserModeLabel")
        row.addWidget(self.mode_label)

        self.status_label = QLabel("")
        self.status_label.setObjectName("browserStatusLabel")
        row.addWidget(self.status_label, 1)

        if not self._runtime.available:
            self.status_label.setText(f"Qt WebEngine 不可用，已自动降级：{self._runtime.error}")

        return strip

    def _tool_button(self, text: str, tooltip: str, slot) -> QPushButton:
        button = QPushButton(text)
        button.setObjectName("browserToolBtn")
        button.setToolTip(tooltip)
        button.setFixedHeight(28)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.clicked.connect(slot)
        return button

    def _create_webengine_view(self, device_mode: str = "desktop") -> tuple[QWidget, Any, Any]:
        runtime = self._runtime
        assert runtime.QWebEngineView and runtime.QWebEnginePage
        assert runtime.QWebEngineProfile and runtime.QWebEngineSettings

        profile_root = Path(APP_ROOT) / ".config" / "embedded_browser"
        profile_root.mkdir(parents=True, exist_ok=True)
        device_config = DEVICE_MODES.get(device_mode, DEVICE_MODES["desktop"])

        self._tab_counter += 1
        profile_name = f"ai_bridge_embedded_browser_{self._tab_counter}_{device_mode}"
        profile = runtime.QWebEngineProfile(profile_name, self)
        profile.setCachePath(str(profile_root / device_mode / "cache"))
        profile.setPersistentStoragePath(str(profile_root / device_mode / "storage"))
        profile.setDownloadPath(str(profile_root / "downloads"))
        if hasattr(profile, "setHttpUserAgent"):
            profile.setHttpUserAgent(device_config["user_agent"])
        if hasattr(runtime.QWebEngineProfile, "PersistentCookiesPolicy"):
            policy = getattr(
                runtime.QWebEngineProfile.PersistentCookiesPolicy,
                "AllowPersistentCookies",
                None,
            )
            if policy is not None:
                profile.setPersistentCookiesPolicy(policy)

        settings = profile.settings()
        for name in (
            "JavascriptEnabled",
            "LocalContentCanAccessFileUrls",
            "LocalContentCanAccessRemoteUrls",
            "WebGLEnabled",
            "Accelerated2dCanvasEnabled",
            "ScrollAnimatorEnabled",
        ):
            _set_webengine_attribute(settings, runtime.QWebEngineSettings, name, True)

        policy = getattr(
            runtime.QWebEngineSettings.UnknownUrlSchemePolicy,
            "DisallowUnknownUrlSchemes",
            None,
        )
        if policy is not None:
            settings.setUnknownUrlSchemePolicy(policy)

        view = runtime.QWebEngineView()
        _install_foreground_visibility_script(profile, runtime.QWebEngineScript)
        page = runtime.QWebEnginePage(profile, view)
        _keep_page_lifecycle_active(page)
        view.setPage(page)
        view.urlChanged.connect(lambda url, tab_view=view: self._on_url_changed(url.toString(), tab_view))
        view.titleChanged.connect(lambda title, tab_view=view: self._on_title_changed(title, tab_view))
        view.loadStarted.connect(lambda tab_view=view: self._on_load_started(tab_view))
        view.loadFinished.connect(lambda ok, tab_view=view: self._on_load_finished(ok, tab_view))
        view.loadProgress.connect(lambda value, tab_view=view: self._on_load_progress(value, tab_view))
        return view, profile, view

    def _create_fallback_view(self) -> QTextBrowser:
        fallback_browser = QTextBrowser()
        fallback_browser.setOpenExternalLinks(True)
        fallback_browser.sourceChanged.connect(lambda url, tab_view=fallback_browser: self._on_url_changed(url.toString(), tab_view))
        return fallback_browser

    def load_address_bar(self) -> None:
        self.load_url(self.address_input.text())

    def new_tab(self, checked=False, url: str | None = None, html: str | None = None,
                title: str = "新标签页", device_mode: str | None = None) -> BrowserTab:
        mode = device_mode or self._active_device_mode
        if mode not in DEVICE_MODES:
            mode = "desktop"

        if self._runtime.available:
            widget, profile, view = self._create_webengine_view(mode)
            tab = BrowserTab(title=title, widget=widget, device_mode=mode, profile=profile, view=view)
        else:
            fallback = self._create_fallback_view()
            tab = BrowserTab(title=title, widget=fallback, device_mode=mode, fallback=fallback)

        tab.widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._tabs.append(tab)
        index = self.tab_widget.addTab(tab.widget, title)
        self.tab_widget.setCurrentIndex(index)
        self._sync_current_tab_controls()

        if html is not None:
            self.render_html(html)
        elif url:
            self.load_url(url)
        else:
            self.render_html(DEFAULT_HOME_HTML)
        self._apply_current_device_profile()
        return tab

    def close_tab(self, index: int) -> None:
        if len(self._tabs) <= 1:
            self.go_home()
            return
        if not 0 <= index < len(self._tabs):
            return
        tab = self._tabs.pop(index)
        self.tab_widget.removeTab(index)
        tab.widget.deleteLater()
        self._sync_current_tab_controls()

    def _current_tab(self) -> BrowserTab | None:
        if not hasattr(self, "tab_widget"):
            return None
        index = self.tab_widget.currentIndex()
        if 0 <= index < len(self._tabs):
            return self._tabs[index]
        return None

    def load_url(self, raw_url: str) -> None:
        url = normalize_browser_url(raw_url, APP_ROOT)
        tab = self._current_tab()
        if tab is None:
            tab = self.new_tab()
        self._apply_device_to_tab(tab)
        if tab.view is not None:
            tab.view.load(url)
        elif tab.fallback is not None:
            if url.isLocalFile():
                tab.fallback.setSource(url)
            else:
                tab.fallback.setHtml(
                    f"<h2>轻量预览模式</h2><p>当前环境未启用 Qt WebEngine，无法打开远程页面：</p><code>{url.toString()}</code>"
                )
        self._on_url_changed(url.toString())

    def load_file(self, path: str | os.PathLike[str]) -> None:
        self.load_url(str(path))

    def render_html(self, html: str, base_url: str | QUrl | None = None) -> None:
        url = QUrl(base_url) if isinstance(base_url, str) else base_url
        if url is None:
            url = QUrl.fromLocalFile(str(Path(APP_ROOT).resolve()) + os.sep)

        tab = self._current_tab()
        if tab is None:
            tab = self.new_tab(html="")
        self._apply_device_to_tab(tab)
        if tab.view is not None:
            tab.view.setHtml(html or "", url)
        elif tab.fallback is not None:
            tab.fallback.setHtml(html or "")
        self.status_label.setText("HTML 已渲染")

    def run_javascript(self, script: str, callback=None) -> bool:
        tab = self._current_tab()
        if tab is None or tab.view is None or tab.view.page() is None:
            self.status_label.setText("当前为轻量预览模式，无法执行 JavaScript")
            return False
        page = tab.view.page()
        if callback is None:
            page.runJavaScript(script)
        else:
            page.runJavaScript(script, callback)
        return True

    def open_html_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "打开 HTML 文件",
            APP_ROOT,
            "HTML 文件 (*.html *.htm);;所有文件 (*.*)",
        )
        if path:
            self.load_file(path)

    def go_home(self) -> None:
        self.render_html(DEFAULT_HOME_HTML)
        self.address_input.clear()

    def go_back(self) -> None:
        tab = self._current_tab()
        if tab and tab.view is not None:
            tab.view.back()
        elif tab and tab.fallback is not None:
            tab.fallback.backward()

    def go_forward(self) -> None:
        tab = self._current_tab()
        if tab and tab.view is not None:
            tab.view.forward()
        elif tab and tab.fallback is not None:
            tab.fallback.forward()

    def reload(self) -> None:
        tab = self._current_tab()
        if tab and tab.view is not None:
            tab.view.reload()
        elif tab and tab.fallback is not None:
            tab.fallback.reload()

    def stop(self) -> None:
        tab = self._current_tab()
        if tab and tab.view is not None:
            tab.view.stop()
        self.status_label.setText("已停止")

    def _on_url_changed(self, url: str, source_widget=None) -> None:
        tab = self._current_tab()
        if source_widget is not None and tab and source_widget is not tab.view and source_widget is not tab.fallback:
            return
        if url and url != self.address_input.text():
            self.address_input.setText(url)
        self.url_changed.emit(url)

    def _on_title_changed(self, title: str, source_widget=None) -> None:
        tab = self._current_tab()
        if source_widget is not None and tab and source_widget is not tab.view:
            return
        if title:
            if tab:
                tab.title = title
                index = self.tab_widget.currentIndex()
                if index >= 0:
                    short_title = title if len(title) <= 18 else title[:17] + "..."
                    self.tab_widget.setTabText(index, short_title)
            self.page_title_changed.emit(title)
            self.status_label.setText(title)

    def _on_load_started(self, source_widget=None) -> None:
        tab = self._current_tab()
        if source_widget is not None and tab and source_widget is not tab.view:
            return
        self.status_label.setText("正在加载...")

    def _on_load_progress(self, value: int, source_widget=None) -> None:
        tab = self._current_tab()
        if source_widget is not None and tab and source_widget is not tab.view:
            return
        self.status_label.setText(f"加载进度 {value}%")

    def _on_load_finished(self, ok: bool, source_widget=None) -> None:
        tab = self._current_tab()
        if source_widget is not None and tab and source_widget is not tab.view:
            return
        self._apply_current_device_profile()
        self.status_label.setText("加载完成" if ok else "加载失败")

    def _on_current_tab_changed(self, index: int) -> None:
        self._sync_current_tab_controls()
        self._apply_current_device_profile()

    def _sync_current_tab_controls(self) -> None:
        tab = self._current_tab()
        if tab is None:
            return
        self._view = tab.view
        self._profile = tab.profile
        self._fallback_browser = tab.fallback
        self._active_device_mode = tab.device_mode
        if hasattr(self, "device_combo"):
            target = self.device_combo.findData(tab.device_mode)
            if isinstance(target, int) and target >= 0 and target != self.device_combo.currentIndex():
                self.device_combo.blockSignals(True)
                self.device_combo.setCurrentIndex(target)
                self.device_combo.blockSignals(False)
        if tab.view is not None and tab.view.url():
            self.address_input.setText(tab.view.url().toString())

    def _on_device_combo_changed(self, index: int) -> None:
        mode = self.device_combo.itemData(index) if index >= 0 else "desktop"
        if mode not in DEVICE_MODES:
            mode = "desktop"
        self._active_device_mode = mode
        tab = self._current_tab()
        if tab is None:
            return
        previous = tab.device_mode
        tab.device_mode = mode
        self._apply_device_to_tab(tab)
        if previous != mode and tab.view is not None:
            tab.view.reload()

    def _apply_device_to_tab(self, tab: BrowserTab | None) -> None:
        if tab is None:
            return
        config = DEVICE_MODES.get(tab.device_mode, DEVICE_MODES["desktop"])
        if tab.profile is not None and hasattr(tab.profile, "setHttpUserAgent"):
            tab.profile.setHttpUserAgent(config["user_agent"])
        if tab.view is not None:
            if hasattr(tab.view, "page"):
                _keep_page_lifecycle_active(tab.view.page())
            width = max(1, tab.view.width() if hasattr(tab.view, "width") else self.width())
            tab.view.setZoomFactor(compute_device_zoom_factor(width, config["target_width"]))
        if tab.fallback is not None:
            line_wrap_mode = getattr(getattr(QTextBrowser, "LineWrapMode", None), "WidgetWidth", None)
            if line_wrap_mode is not None and hasattr(tab.fallback, "setLineWrapMode"):
                tab.fallback.setLineWrapMode(line_wrap_mode)

    def _apply_current_device_profile(self) -> None:
        self._apply_device_to_tab(self._current_tab())

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._apply_current_device_profile()

    def apply_content_theme(self) -> None:
        p = theme_manager.get_palette()
        self.setStyleSheet(f"""
            QWidget#browserToolbar {{
                background-color: {p.BG_SECONDARY};
                border-bottom: 1px solid {p.BORDER};
            }}
            QPushButton#browserToolBtn {{
                background-color: {p.BG_TERTIARY};
                color: {p.TEXT_PRIMARY};
                border: 1px solid {p.BORDER};
                border-radius: 4px;
                padding: 2px 9px;
                font-size: 11px;
                font-family: "Microsoft YaHei", sans-serif;
            }}
            QPushButton#browserToolBtn:hover {{
                border-color: {p.ACCENT_PRIMARY};
            }}
            QLineEdit#browserAddress {{
                background-color: {p.BG_PRIMARY};
                color: {p.TEXT_PRIMARY};
                border: 1px solid {p.BORDER};
                border-radius: 4px;
                padding: 4px 8px;
                font-size: 12px;
                font-family: Consolas, "Microsoft YaHei", sans-serif;
            }}
            QComboBox#browserDeviceCombo {{
                background-color: {p.BG_TERTIARY};
                color: {p.TEXT_PRIMARY};
                border: 1px solid {p.BORDER};
                border-radius: 4px;
                padding: 3px 8px;
                min-width: 72px;
                font-size: 11px;
                font-family: "Microsoft YaHei", sans-serif;
            }}
            QComboBox#browserDeviceCombo::drop-down {{
                border: none;
                width: 16px;
            }}
            QTabWidget#browserTabs::pane {{
                border: none;
                background-color: {p.BG_PRIMARY};
            }}
            QTabBar::tab {{
                background-color: {p.BG_SECONDARY};
                color: {p.TEXT_SECONDARY};
                border: 1px solid {p.BORDER};
                border-bottom: none;
                padding: 4px 10px;
                min-width: 72px;
                max-width: 160px;
                font-size: 11px;
            }}
            QTabBar::tab:selected {{
                background-color: {p.BG_PRIMARY};
                color: {p.TEXT_PRIMARY};
            }}
            QFrame#browserStatusStrip {{
                background-color: {p.BG_PRIMARY};
                border-bottom: 1px solid {p.BORDER};
            }}
            QLabel#browserModeLabel {{
                color: {p.ACCENT_PRIMARY};
                font-size: 11px;
                font-weight: 600;
            }}
            QLabel#browserStatusLabel {{
                color: {p.TEXT_SECONDARY};
                font-size: 11px;
            }}
            QTextBrowser {{
                background-color: #101114;
                color: #e5e7eb;
                border: none;
                padding: 12px;
                font-family: "Microsoft YaHei", sans-serif;
            }}
        """)

    def apply_theme(self):
        super().apply_theme()
        if hasattr(self, "status_label"):
            self.apply_content_theme()
