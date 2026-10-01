# filename: app/ui/pages/chat/status_bar.py
import os
import sys
import shutil
import subprocess
from PySide6.QtWidgets import QCheckBox, QComboBox, QFrame, QHBoxLayout, QLabel, QSizePolicy, QPushButton, QMenu, QFileDialog, QMessageBox, QWidget
from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen

from app.core.api_mode_config import APIModeConfigManager
from app.core.app_constants import APP_ROOT
from app.core.model_capabilities import (
    REASONING_MODE_EFFORT,
    REASONING_MODE_NONE,
    REASONING_MODE_SWITCH,
    normalize_reasoning_for_capability,
    reasoning_summary_text,
    reasoning_tooltip,
    resolve_model_capability,
)
from app.core.project_context import ProjectContext
from app.core.logging import get_logger
from app.ui.theme import Theme, theme_manager

logger = get_logger("app.ui.chat_status_bar", side="ui")


class ContextUsageRing(QWidget):
    """聊天页底部的紧凑上下文容量指示器。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._percent = 0
        self._color = "#48c774"
        self.setFixedSize(22, 22)
        self.setToolTip("暂无上下文容量数据")

    def set_usage(self, percent: int, tooltip: str = ""):
        self._percent = max(0, min(100, int(percent or 0)))
        p = theme_manager.get_palette()
        if self._percent >= 85:
            self._color = p.TEXT_DANGER
        elif self._percent >= 60:
            self._color = p.BTN_WARNING
        else:
            self._color = p.TEXT_SUCCESS
        self.setToolTip(tooltip or "暂无上下文容量数据")
        self.update()

    def paintEvent(self, event):
        p = theme_manager.get_palette()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = QRectF(3, 3, self.width() - 6, self.height() - 6)

        track = QPen(QColor(p.BORDER), 3)
        track.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(track)
        painter.drawArc(rect, 0, 360 * 16)

        progress = QPen(QColor(self._color), 3)
        progress.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(progress)
        painter.drawArc(rect, 90 * 16, -int(360 * 16 * (self._percent / 100)))


class _SandboxMixin:
    """沙盒环境切换逻辑 mixin，供 BrowserProjectBar 和 ApiModelUsageBar 共用。

    使用方需在 _build_ui 末尾调用 _build_sandbox_btn(layout)，
    并在 apply_theme 末尾调用 _apply_sandbox_theme()。
    信号 log_message(str) 和 env_changed(str, str) 需由子类声明。
    """

    def _show_project_menu(self):
        if not hasattr(self, "project_value_label"):
            return

        ctx = getattr(self, "_project_ctx", ProjectContext.get())
        menu = QMenu(self)
        p = theme_manager.get_palette()
        menu.setStyleSheet(f"""
            QMenu {{
                background-color: {p.BG_SECONDARY};
                color: {p.TEXT_PRIMARY};
                border: 1px solid {p.BORDER};
            }}
            QMenu::item:selected {{ background-color: {p.ACCENT_PRIMARY}; }}
            QMenu::item:disabled {{ color: {p.TEXT_SECONDARY}; }}
        """)

        current_action = menu.addAction(f"当前: {ctx.project_name or '未命名项目'}")
        current_action.setEnabled(False)
        current_action.setToolTip(ctx.get_project_root())
        menu.addSeparator()

        open_action = menu.addAction("打开项目...")
        recent_items = ctx.get_recent_projects()
        recent_actions = []
        if recent_items:
            menu.addSeparator()
            recent_title = menu.addAction("最近项目")
            recent_title.setEnabled(False)
            current_root = os.path.normcase(os.path.abspath(ctx.get_project_root()))
            for item in recent_items:
                path = str(item.get("path") or "")
                if not path:
                    continue
                name = str(item.get("name") or os.path.basename(path) or path)
                prefix = "✓ " if os.path.normcase(os.path.abspath(path)) == current_root else "  "
                action = menu.addAction(f"{prefix}{name}")
                action.setToolTip(path)
                action.setData(path)
                recent_actions.append(action)

        menu.addSeparator()
        home_action = menu.addAction("返回软件目录")

        action = menu.exec(self.project_value_label.mapToGlobal(
            self.project_value_label.rect().bottomLeft()
        ))
        if not action:
            return
        if action == open_action:
            current = ctx.get_project_root()
            path = QFileDialog.getExistingDirectory(self, "选择项目目录", current)
            if path:
                self._switch_project_path(path)
            return
        if action == home_action:
            self._switch_project_path(APP_ROOT)
            return
        path = action.data()
        if path:
            self._switch_project_path(str(path))

    def _switch_project_path(self, path: str):
        if not path:
            return
        if not os.path.isdir(path):
            QMessageBox.warning(self, "路径无效", f"目录不存在:\n{path}")
            return
        ctx = getattr(self, "_project_ctx", ProjectContext.get())
        logger.info("[底部项目切换] 请求切换到: %s", path)
        ok = ctx.switch_to(path)
        if not ok:
            self.log_message.emit(f"⚠️ 项目切换失败: {path}")
            return
        self.refresh_project()
        self.log_message.emit(f"📁 项目已切换: {ctx.project_name}")
        if hasattr(self, "project_changed"):
            self.project_changed.emit(path)

    def _build_sandbox_btn(self, layout):
        """在传入的 QHBoxLayout 末尾追加环境切换按钮。"""
        self._docker_manager = None
        self.env_btn = QPushButton("执行环境 ▾")
        self.env_btn.setFixedHeight(20)
        self.env_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.env_btn.setToolTip("当前代码执行环境，点击切换")
        self.env_btn.clicked.connect(self._show_sandbox_menu)
        layout.addWidget(self.env_btn)

    def set_docker_manager(self, docker_manager):
        """绑定 DockerManager 实例（直连本地模式，兼容保留）。"""
        self._docker_manager = docker_manager
        self._refresh_sandbox_label()

    def sync_exec_state(self, mode: str, python: str = ""):
        """从外部（config 或服务端状态）同步当前执行环境，刷新按钮显示。"""
        self._current_exec_mode = mode
        self._current_exec_python = python
        self._refresh_sandbox_label()
        if hasattr(self, 'env_btn'):
            self.env_btn.setEnabled(True)

    def _refresh_sandbox_label(self):
        if not hasattr(self, 'env_btn'):
            return
        # 优先用本地缓存（remote 模式下无法访问服务端 docker_manager）
        mode = getattr(self, '_current_exec_mode', None)
        python = getattr(self, '_current_exec_python', '')
        # 若本地无缓存，尝试从 docker_manager 读（本地直连模式）
        if mode is None and self._docker_manager:
            mode = getattr(self._docker_manager, 'exec_mode', 'docker')
            python = getattr(self._docker_manager, 'local_python', '')
        if mode is None:
            self.env_btn.setText("执行环境 ▾")
            return
        if mode == 'local':
            name = os.path.basename(python) if python else '系统 Python'
            self.env_btn.setText(f"💻 本地: {name} ▾")
            self.env_btn.setToolTip(f"当前使用本地 Python\n路径: {python or '系统默认'}\n点击切换")
        else:
            self.env_btn.setText("🐳 Docker 沙盒 ▾")
            self.env_btn.setToolTip("当前使用 Docker 隔离沙盒\n点击切换")

    def _show_sandbox_menu(self):
        from app.core.docker_manager import EXEC_MODE_DOCKER, EXEC_MODE_LOCAL

        menu = QMenu(self)

        # Docker 选项（可用性由服务端判断，客户端直接允许选择）
        docker_action = menu.addAction("🐳 Docker 沙盒")

        menu.addSeparator()

        # 自动探测本地环境
        detected = self._detect_local_pythons()
        for label, path in detected:
            act = menu.addAction(label)
            act.setData((EXEC_MODE_LOCAL, path))

        menu.addSeparator()
        custom_action = menu.addAction("🔧 自定义解释器路径...")

        action = menu.exec(self.env_btn.mapToGlobal(
            self.env_btn.rect().bottomLeft()
        ))

        if not action:
            return
        if action == docker_action:
            self._apply_sandbox_mode(EXEC_MODE_DOCKER, "")
        elif action == custom_action:
            self._pick_sandbox_custom_path()
        elif action.data():
            mode, path = action.data()
            self._apply_sandbox_mode(mode, path)

    def _detect_local_pythons(self) -> list:
        """探测本地可用 Python 解释器，返回 [(显示名, 路径), ...]。"""
        candidates = []
        seen_paths = set()  # 按路径字符串去重，venv 和系统 python 即使 realpath 相同也分开显示
        current_path = getattr(self, '_current_exec_python', '') or sys.executable

        def get_version(path):
            """跑一次 python --version 拿版本号，失败返回空串。"""
            try:
                out = subprocess.check_output(
                    [path, '--version'], stderr=subprocess.STDOUT, timeout=3
                ).decode().strip()
                return out.split()[-1] if out else ''
            except Exception:
                return ''

        def add(name, path):
            if not path or path in seen_paths:
                return
            seen_paths.add(path)
            ver = get_version(path)
            ver_str = f"  Python {ver}" if ver else ''
            prefix = '✓ ' if path == current_path else '  '
            candidates.append((f"{prefix}{name}{ver_str}", path))

        # 项目根目录常见虚拟环境（优先）
        try:
            root = ProjectContext.get().get_project_root()
        except Exception:
            root = os.getcwd()

        for venv_dir in (".venv", "venv", "env", ".env"):
            base = os.path.join(root, venv_dir)
            for rel in ("bin/python3", "bin/python", "Scripts/python.exe"):
                p = os.path.join(base, rel)
                if os.path.isfile(p):
                    add(venv_dir, p)
                    break

        # PATH 中的 python3 / python
        for name in ("python3", "python"):
            p = shutil.which(name)
            if p:
                add(f"系统 {name}", p)

        return candidates

    def _pick_sandbox_custom_path(self):
        from app.core.docker_manager import EXEC_MODE_LOCAL
        current = getattr(self, '_current_exec_python', '') or ""
        path, ok = QFileDialog.getOpenFileName(
            self, "选择 Python 解释器", os.path.dirname(current) or "",
            "Python 解释器 (python python3 python.exe);;所有文件 (*)"
        )
        if ok and path:
            self._apply_sandbox_mode(EXEC_MODE_LOCAL, path)

    def _apply_sandbox_mode(self, mode: str, python_path: str):
        # 本地缓存当前选择，用于刷新按钮文字（不依赖服务端回传）
        self._current_exec_mode = mode
        self._current_exec_python = python_path
        self._refresh_sandbox_label()
        # 通知上层走 RPC 切换（page.py 里接到后调 worker.set_exec_mode）
        self.env_changed.emit(mode, python_path)
        # 日志提醒
        if mode == 'local':
            label = os.path.basename(python_path) if python_path else '系统默认'
            self.log_message.emit(f"💻 执行环境已切换为本地 Python: {label}")
        else:
            self.log_message.emit("🐳 执行环境已切换为 Docker 沙盒")

    def _apply_sandbox_theme(self):
        if not hasattr(self, 'env_btn'):
            return
        p = theme_manager.get_palette()
        self.env_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {p.BG_TERTIARY};
                color: {p.TEXT_SECONDARY};
                border: 1px solid {p.BORDER};
                border-radius: 3px;
                padding: 0px 6px;
                font-size: 11px;
            }}
            QPushButton:hover {{
                background-color: {p.BORDER};
                color: {p.TEXT_PRIMARY};
            }}
        """)


class ApiModelUsageBar(_SandboxMixin, QFrame):
    usage_changed = Signal(object)
    env_changed = Signal(str, str)   # (mode, local_python)
    project_changed = Signal(str)
    log_message = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("ApiModelUsageBar")
        self._loading = False
        self._conversation_id = ""
        self._current_usage = None
        self._api_mode_config = {}
        self._context_status = {}
        self._current_reasoning_capability = {}
        self._project_ctx = ProjectContext.get()
        self._build_ui()
        theme_manager.theme_changed.connect(self.apply_theme)
        try:
            self._project_ctx.project_switched.connect(lambda *_: self.refresh_project())
        except Exception as e:
            logger.warning(e)
        self.reload_options()
        self.refresh_project()
        self.apply_theme()

    def _build_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 4, 12, 0)
        layout.setSpacing(8)

        # 项目名
        self.project_value_label = QPushButton("📁 当前项目 ▾")
        self.project_value_label.setMinimumWidth(36)
        self.project_value_label.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
        self.project_value_label.setToolTip("")
        self.project_value_label.setCursor(Qt.CursorShape.PointingHandCursor)
        self.project_value_label.clicked.connect(self._show_project_menu)

        # Profile / Chain 选择
        self.combo = QComboBox()
        self.combo.setMinimumWidth(60)
        self.combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.combo.setMinimumContentsLength(8)
        self.combo.setCursor(Qt.CursorShape.PointingHandCursor)
        self.combo.currentIndexChanged.connect(self._on_selection_changed)

        # 会话级模型覆盖
        self.model_combo = QComboBox()
        self.model_combo.setMinimumWidth(110)
        self.model_combo.setMaximumWidth(190)
        self.model_combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.model_combo.setMinimumContentsLength(10)
        self.model_combo.setCursor(Qt.CursorShape.PointingHandCursor)
        self.model_combo.setToolTip("本对话使用的模型；留空则跟随 Profile")
        self.model_combo.currentIndexChanged.connect(self._on_detail_controls_changed)

        # 会话级思考参数
        self.reasoning_check = QCheckBox("思考")
        self.reasoning_check.setCursor(Qt.CursorShape.PointingHandCursor)
        self.reasoning_check.setToolTip("仅影响当前 API 对话；Provider 不支持时会由后端按兼容策略处理")
        self.reasoning_check.stateChanged.connect(self._on_detail_controls_changed)

        self.effort_combo = QComboBox()
        self.effort_combo.setMinimumWidth(54)
        self.effort_combo.setMaximumWidth(72)
        self.effort_combo.setCursor(Qt.CursorShape.PointingHandCursor)
        self.effort_combo.addItem("低", "low")
        self.effort_combo.addItem("中", "medium")
        self.effort_combo.addItem("高", "high")
        self.effort_combo.currentIndexChanged.connect(self._on_detail_controls_changed)

        # 摘要
        self.summary_label = QLabel("使用全局默认")
        self.summary_label.setMinimumWidth(36)
        self.summary_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.summary_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

        # 上下文容量
        self.context_ring = ContextUsageRing()
        self.capacity_value_label = QLabel("--%")
        self.capacity_value_label.setMinimumWidth(34)
        self.capacity_value_label.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
        self.capacity_value_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

        layout.addWidget(self.project_value_label)
        layout.addWidget(self.combo)
        layout.addWidget(self.model_combo)
        layout.addWidget(self.reasoning_check)
        layout.addWidget(self.effort_combo)
        layout.addWidget(self.summary_label, 1)
        layout.addWidget(self.context_ring)
        layout.addWidget(self.capacity_value_label)
        # 环境切换按钮（同行末尾）
        self._build_sandbox_btn(layout)

    def reload_options(self):
        self._api_mode_config = APIModeConfigManager.load()
        self._populate_options()
        self.set_conversation(self._conversation_id, self._current_usage)

    def set_conversation(self, conv_id, usage):
        self._conversation_id = str(conv_id or "")
        self._current_usage = usage if isinstance(usage, dict) else None
        self._select_usage(self._current_usage)
        self.combo.setEnabled(bool(self._conversation_id))
        self.model_combo.setEnabled(bool(self._conversation_id))
        self._refresh_reasoning_enabled_state()
        if not self._conversation_id:
            self.summary_label.setText("请先选择 API 对话")

    def refresh_project(self):
        try:
            root = self._project_ctx.get_project_root()
            name = self._project_ctx.project_name or "未命名项目"
            self.project_value_label.setText(f"📁 {name} ▾")
            self.project_value_label.setToolTip(f"当前项目:\n{root}\n点击切换项目")
        except Exception:
            self.project_value_label.setText("📁 未知项目 ▾")
            self.project_value_label.setToolTip("")

    def set_context_status(self, payload):
        self._context_status = payload if isinstance(payload, dict) else {}
        self._update_capacity()

    def _populate_options(self):
        self._loading = True
        self.combo.clear()
        self.combo.addItem("使用全局默认", "")

        profiles = self._api_mode_config.get("profiles", {}) or {}
        if profiles:
            self.combo.insertSeparator(self.combo.count())
        for key, profile in profiles.items():
            name = profile.get("name") or key
            kind = profile.get("kind") or "api"
            provider = profile.get("provider") or profile.get("vendor") or "api"
            self.combo.addItem(f"Profile · {name}", f"profile:{key}")
            self.combo.setItemData(
                self.combo.count() - 1,
                f"{key} · {provider} · {kind}",
                Qt.ItemDataRole.ToolTipRole,
            )

        chains = self._api_mode_config.get("fallback_chains", {}) or {}
        if chains:
            self.combo.insertSeparator(self.combo.count())
        for key in chains.keys():
            self.combo.addItem(f"Chain · {key}", f"chain:{key}")

        self._loading = False

    def _select_usage(self, usage):
        self._loading = True
        target = ""
        if isinstance(usage, dict):
            usage_type = str(usage.get("type") or "").strip()
            ref = str(usage.get("ref") or "").strip()
            if usage_type in ("profile", "chain") and ref:
                target = f"{usage_type}:{ref}"
        idx = self.combo.findData(target)
        self.combo.setCurrentIndex(idx if idx >= 0 else 0)
        self._loading = False
        self._sync_detail_controls(usage)
        self._update_summary()

    def _current_combo_usage(self):
        data = str(self.combo.currentData() or "")
        if not data:
            return None
        usage_type, _, ref = data.partition(":")
        if usage_type not in ("profile", "chain") or not ref:
            return None
        return {"type": usage_type, "ref": ref}

    def _resolved_profile_key(self, usage=None):
        try:
            return APIModeConfigManager.get_active_profile_key(
                self._api_mode_config,
                usage_override=usage if isinstance(usage, dict) else None,
            )
        except Exception:
            return ""

    def _profile_for_usage(self, usage=None):
        profile_key = self._resolved_profile_key(usage)
        profiles = self._api_mode_config.get("profiles", {}) or {}
        return profile_key, profiles.get(profile_key, {}) if profile_key else {}

    def _available_models_for_profile(self, profile):
        models = []
        current = str((profile or {}).get("model") or "").strip()
        if current:
            models.append(current)
        available = (profile or {}).get("available_models")
        if isinstance(available, dict):
            models.extend(str(m).strip() for m in (available.get("models") or []) if str(m).strip())
        elif isinstance(available, list):
            models.extend(str(m).strip() for m in available if str(m).strip())
        return list(dict.fromkeys(models))

    def _profile_reasoning(self, profile):
        reasoning = (profile or {}).get("reasoning") if isinstance(profile, dict) else {}
        reasoning = reasoning if isinstance(reasoning, dict) else {}
        effort = str(reasoning.get("effort", "medium") or "medium").strip().lower()
        if effort not in ("low", "medium", "high"):
            effort = "medium"
        return {
            "enabled": bool(reasoning.get("enabled", False)),
            "effort": effort,
        }

    def _effective_model_for_controls(self, profile):
        return str(self.model_combo.currentData() or (profile or {}).get("model") or "").strip()

    def _capability_for_profile_model(self, profile, model=None):
        return resolve_model_capability(profile, model=model or self._effective_model_for_controls(profile))

    def _set_effort_options(self, efforts, selected="medium"):
        labels = {"low": "低", "medium": "中", "high": "高"}
        options = [str(e).strip().lower() for e in (efforts or []) if str(e).strip().lower() in labels]
        if not options:
            options = ["medium"]
        selected = str(selected or "medium").strip().lower()
        if selected not in options:
            selected = "medium" if "medium" in options else options[0]

        self.effort_combo.blockSignals(True)
        self.effort_combo.clear()
        for effort in options:
            self.effort_combo.addItem(labels.get(effort, effort), effort)
        idx = self.effort_combo.findData(selected)
        self.effort_combo.setCurrentIndex(idx if idx >= 0 else 0)
        self.effort_combo.blockSignals(False)

    def _apply_reasoning_controls(self, reasoning, capability):
        self._current_reasoning_capability = capability or {}
        reasoning_cap = (capability or {}).get("reasoning", {}) if isinstance(capability, dict) else {}
        mode = str(reasoning_cap.get("mode") or REASONING_MODE_NONE)
        normalized = normalize_reasoning_for_capability(reasoning, capability)

        self._set_effort_options(reasoning_cap.get("efforts") or [], normalized.get("effort", "medium"))
        self.reasoning_check.setVisible(mode != REASONING_MODE_NONE)
        self.effort_combo.setVisible(mode == REASONING_MODE_EFFORT)
        self.reasoning_check.setToolTip(reasoning_tooltip(capability))
        self.effort_combo.setToolTip(reasoning_tooltip(capability))
        self.reasoning_check.setText("思考" if mode != REASONING_MODE_SWITCH else "思考")
        if mode != REASONING_MODE_NONE:
            self.reasoning_check.setChecked(bool(normalized.get("enabled")))
        self._refresh_reasoning_enabled_state()

    def _refresh_reasoning_enabled_state(self):
        reasoning_cap = (self._current_reasoning_capability or {}).get("reasoning", {})
        mode = str(reasoning_cap.get("mode") or REASONING_MODE_NONE)
        can_edit = bool(self._conversation_id and mode != REASONING_MODE_NONE)
        self.reasoning_check.setEnabled(can_edit)
        self.effort_combo.setEnabled(bool(can_edit and mode == REASONING_MODE_EFFORT and self.reasoning_check.isChecked()))

    def _refresh_reasoning_controls_for_current_model(self):
        base_usage = self._current_combo_usage()
        _profile_key, profile = self._profile_for_usage(base_usage)
        capability = self._capability_for_profile_model(profile)
        current = {
            "enabled": bool(self.reasoning_check.isChecked()),
            "effort": str(self.effort_combo.currentData() or "medium"),
        }
        normalized = normalize_reasoning_for_capability(current, capability)
        old_loading = self._loading
        self._loading = True
        self._apply_reasoning_controls(normalized, capability)
        self._loading = old_loading

    def _sync_detail_controls(self, usage):
        base_usage = self._current_combo_usage()
        profile_key, profile = self._profile_for_usage(base_usage)
        default_model = str((profile or {}).get("model") or "").strip()
        selected_model = ""
        if isinstance(usage, dict):
            selected_model = str(usage.get("model") or "").strip()

        self._loading = True
        self.model_combo.clear()
        follow_text = f"跟随: {default_model}" if default_model else "跟随 Profile"
        self.model_combo.addItem(follow_text, "")
        for model in self._available_models_for_profile(profile):
            self.model_combo.addItem(model, model)
        idx = self.model_combo.findData(selected_model) if selected_model else 0
        self.model_combo.setCurrentIndex(idx if idx >= 0 else 0)

        effective_model = selected_model or default_model
        capability = self._capability_for_profile_model(profile, effective_model)
        reasoning = normalize_reasoning_for_capability(self._profile_reasoning(profile), capability)
        if isinstance(usage, dict) and isinstance(usage.get("reasoning"), dict):
            override = usage.get("reasoning") or {}
            if "enabled" in override:
                reasoning["enabled"] = bool(override.get("enabled"))
            effort = str(override.get("effort") or reasoning["effort"]).strip().lower()
            if effort in ("low", "medium", "high"):
                reasoning["effort"] = effort
        reasoning = normalize_reasoning_for_capability(reasoning, capability)
        self._apply_reasoning_controls(reasoning, capability)
        self._loading = False

    def _current_usage_from_controls(self):
        base_usage = self._current_combo_usage()
        profile_key, profile = self._profile_for_usage(base_usage)
        if not profile_key:
            return base_usage

        usage = dict(base_usage or {"type": "profile", "ref": profile_key})
        explicit_override = bool(base_usage)

        model = str(self.model_combo.currentData() or "").strip()
        if model:
            usage["model"] = model
            explicit_override = True

        default_model = str((profile or {}).get("model") or "").strip()
        default_capability = self._capability_for_profile_model(profile, default_model)
        default_reasoning = normalize_reasoning_for_capability(self._profile_reasoning(profile), default_capability)
        capability = self._capability_for_profile_model(profile, model or default_model)
        reasoning = normalize_reasoning_for_capability({
            "enabled": bool(self.reasoning_check.isChecked()),
            "effort": str(self.effort_combo.currentData() or "medium"),
        }, capability)
        mode = str((capability.get("reasoning") or {}).get("mode") or REASONING_MODE_NONE)
        if mode != REASONING_MODE_NONE and (reasoning != default_reasoning or explicit_override):
            usage["reasoning"] = reasoning
            explicit_override = True

        return usage if explicit_override else None

    def _on_selection_changed(self, *_args):
        if self._loading:
            return
        self._sync_detail_controls(None)
        usage = self._current_usage_from_controls()
        self._current_usage = usage
        self._update_summary()
        self.usage_changed.emit(usage)

    def _on_detail_controls_changed(self, *_args):
        if self._loading:
            return
        self._refresh_reasoning_controls_for_current_model()
        usage = self._current_usage_from_controls()
        self._current_usage = usage
        self._update_summary()
        self.usage_changed.emit(usage)

    def _update_summary(self):
        usage = self._current_usage_from_controls()
        if not usage:
            try:
                default_key = APIModeConfigManager.get_active_profile_key(self._api_mode_config)
                profile = self._api_mode_config.get("profiles", {}).get(default_key, {})
                model = profile.get("model") or ""
                capability = self._capability_for_profile_model(profile, model)
                reason_text = reasoning_summary_text(self._profile_reasoning(profile), capability)
                self.summary_label.setText(f"默认：{profile.get('name') or default_key} · {model} · {reason_text}")
            except Exception:
                self.summary_label.setText("使用全局默认")
            return

        ref = usage.get("ref", "")
        if usage.get("type") == "profile":
            profile = self._api_mode_config.get("profiles", {}).get(ref, {})
            model = usage.get("model") or profile.get("model") or ""
            reason = usage.get("reasoning") if isinstance(usage.get("reasoning"), dict) else {}
            profile_reasoning = self._profile_reasoning(profile)
            if reason:
                profile_reasoning.update(reason)
            capability = self._capability_for_profile_model(profile, model)
            reason_text = reasoning_summary_text(profile_reasoning, capability)
            self.summary_label.setText(f"本对话：{profile.get('name') or ref} · {model} · {reason_text}")
        else:
            profile_key, profile = self._profile_for_usage(usage)
            model = usage.get("model") or profile.get("model") or ""
            reason = usage.get("reasoning") if isinstance(usage.get("reasoning"), dict) else {}
            profile_reasoning = self._profile_reasoning(profile)
            if reason:
                profile_reasoning.update(reason)
            capability = self._capability_for_profile_model(profile, model)
            reason_text = reasoning_summary_text(profile_reasoning, capability)
            self.summary_label.setText(f"本对话 Chain：{ref} · {model} · {reason_text}")

    def _update_capacity(self):
        usage = self._context_status or {}
        try:
            utilization = float(usage.get("utilization", 0) or 0)
            used = int(usage.get("total_used", usage.get("used", 0)) or 0)
            total = int(usage.get("total_budget", usage.get("total", 0)) or 0)
        except Exception:
            utilization, used, total = 0, 0, 0

        if total <= 0 and used <= 0:
            self.capacity_value_label.setText("--%")
            self.capacity_value_label.setToolTip("暂无上下文容量数据")
            self.context_ring.set_usage(0, "暂无上下文容量数据")
            self._apply_capacity_color(0)
            return

        if utilization <= 0 and total > 0:
            utilization = round((used / total) * 100, 1)
        percent = int(round(utilization))
        tooltip = self._format_context_tooltip(usage, percent, used, total)
        if total > 0:
            self.capacity_value_label.setText(f"{percent}%")
            self.capacity_value_label.setToolTip(tooltip)
        else:
            self.capacity_value_label.setText(f"{percent}%")
            self.capacity_value_label.setToolTip(tooltip)
        self.context_ring.set_usage(percent, tooltip)
        self._apply_capacity_color(percent)

    def _format_context_tooltip(self, usage, percent, used, total):
        lines = ["上下文容量"]
        if total > 0:
            lines.append(f"已使用: {used:,} / {total:,} tokens ({percent}%)")
        else:
            lines.append(f"已使用: {used:,} tokens ({percent}%)")

        layer_labels = {
            "system": "系统",
            "long_term": "长期记忆",
            "working": "工作记忆",
            "short_term": "短期历史",
        }
        for key, label in layer_labels.items():
            layer = usage.get(key)
            if not isinstance(layer, dict):
                continue
            layer_used = int(layer.get("used", 0) or 0)
            budget = int(layer.get("budget", 0) or 0)
            if budget > 0:
                lines.append(f"{label}: {layer_used:,} / {budget:,}")
            elif layer_used > 0:
                lines.append(f"{label}: {layer_used:,}")

        reserve = int(usage.get("output_reserve", 0) or 0)
        if reserve > 0:
            lines.append(f"输出预留: {reserve:,}")
        turns = usage.get("turns", usage.get("history_turns"))
        if turns is not None:
            lines.append(f"轮次: {turns}")
        profile = usage.get("runtime_profile_key") or usage.get("configured_profile_key")
        if profile:
            lines.append(f"Profile 配置: {profile}")
        return "\n".join(lines)

    def _apply_capacity_color(self, percent):
        p = theme_manager.get_palette()
        color = p.TEXT_SUCCESS
        if percent >= 85:
            color = p.TEXT_DANGER
        elif percent >= 60:
            color = p.BTN_WARNING
        self.capacity_value_label.setStyleSheet(f"color: {color}; font-size: 12px; font-weight: bold;")

    def apply_theme(self):
        p = theme_manager.get_palette()
        self.setStyleSheet(f"""
            QFrame#ApiModelUsageBar {{
                background-color: {p.BG_PRIMARY};
                border-top: 1px solid {p.BORDER};
            }}
        """)
        self.project_value_label.setStyleSheet(f"""
            QPushButton {{
                background-color: {p.BG_TERTIARY};
                color: {p.TEXT_PRIMARY};
                border: 1px solid {p.BORDER};
                border-radius: 3px;
                padding: 0px 6px;
                font-size: 12px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background-color: {p.BORDER};
            }}
        """)
        self.combo.setStyleSheet(Theme.combo_box())
        self.model_combo.setStyleSheet(Theme.combo_box())
        self.effort_combo.setStyleSheet(Theme.combo_box())
        self.reasoning_check.setStyleSheet(f"color: {p.TEXT_SECONDARY}; font-size: 12px;")
        self.summary_label.setStyleSheet(f"color: {p.TEXT_SECONDARY}; font-size: 12px;")
        self._update_capacity()
        self._apply_sandbox_theme()


class BrowserProjectBar(_SandboxMixin, QFrame):
    """浏览器模式下的轻量状态栏，显示当前项目位置 + 执行环境切换按钮。"""
    env_changed = Signal(str, str)   # (mode, local_python)
    project_changed = Signal(str)
    log_message = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("BrowserProjectBar")
        self._project_ctx = ProjectContext.get()
        self._build_ui()
        theme_manager.theme_changed.connect(self.apply_theme)
        try:
            self._project_ctx.project_switched.connect(lambda *_: self.refresh_project())
        except Exception as e:
            logger.warning(e)
        self.refresh_project()
        self.apply_theme()

    def _build_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 3, 12, 3)
        layout.setSpacing(6)

        self.project_label = QLabel("项目")
        self.project_value_label = QPushButton("当前项目 ▾")
        self.project_value_label.setMinimumWidth(36)
        self.project_value_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.project_value_label.setCursor(Qt.CursorShape.PointingHandCursor)
        self.project_value_label.clicked.connect(self._show_project_menu)

        layout.addWidget(self.project_label)
        layout.addWidget(self.project_value_label, 1)
        # 环境切换按钮（同行末尾）
        self._build_sandbox_btn(layout)

    def refresh_project(self):
        try:
            root = self._project_ctx.get_project_root()
            name = self._project_ctx.project_name or "未命名项目"
            self.project_value_label.setText(f"{name} ▾")
            self.project_value_label.setToolTip(f"当前项目:\n{root}\n点击切换项目")
        except Exception:
            self.project_value_label.setText("未知项目 ▾")
            self.project_value_label.setToolTip("")

    def apply_theme(self):
        p = theme_manager.get_palette()
        self.setStyleSheet(f"""
            QFrame#BrowserProjectBar {{
                background-color: {p.BG_PRIMARY};
                border-top: 1px solid {p.BORDER};
            }}
        """)
        self.project_label.setStyleSheet(f"color: {p.TEXT_SECONDARY}; font-size: 12px;")
        self.project_value_label.setStyleSheet(f"""
            QPushButton {{
                background-color: {p.BG_TERTIARY};
                color: {p.TEXT_PRIMARY};
                border: 1px solid {p.BORDER};
                border-radius: 3px;
                padding: 0px 6px;
                font-size: 12px;
                font-weight: bold;
                text-align: left;
            }}
            QPushButton:hover {{
                background-color: {p.BORDER};
            }}
        """)
        self._apply_sandbox_theme()


# 向后兼容：旧代码若直接实例化 SandboxEnvBar 不会报错
SandboxEnvBar = None
