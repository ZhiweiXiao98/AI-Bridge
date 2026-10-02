# UI 架构分析报告

> 历史阶段记录（2026-09-05 整理）：以下原文用于追溯当时的设计、实现与验证；当前能力见[项目状态](当前项目状态.md)，当前测试命令见[测试说明](../tests/README.md)。

**分析时间**：Wed Mar  4 06:29:20 UTC 2026

## 📁 UI 文件结构

共找到 30 个 UI 文件：

- app/ui/__init__.py
- app/ui/components/base.py
- app/ui/components/chat.py
- app/ui/components/code_pseudo_viewer.py
- app/ui/components/collapsible_sidebar.py
- app/ui/components/editor.py
- app/ui/components/forensic_editor.py
- app/ui/components/input.py
- app/ui/components/logic_viewer.py
- app/ui/components/ops_panel.py
- app/ui/components/overlay.py
- app/ui/components/preview_dialog.py
- app/ui/components/session_item.py
- app/ui/components/task_panel.py
- app/ui/components/theme_editor.py
- app/ui/login_window.py
- app/ui/main_window.py
- app/ui/modeling_page.py
- app/ui/pages/chat/__init__.py
- app/ui/pages/chat/header.py
- app/ui/pages/chat/input_area.py
- app/ui/pages/chat/message_area.py
- app/ui/pages/chat/page.py
- app/ui/pages/chat/session_list.py
- app/ui/pages/code_review_page.py
- app/ui/pages/console_page.py
- app/ui/pages/context_page.py
- app/ui/settings_page.py
- app/ui/theme.py
- app/ui/widgets.py

## 🔍 关键文件分析

### 主窗口 (main_window.py)

- **路径**：/workspace/app/ui/main_window.py
- **行数**：434
- **使用 QDockWidget**：否
- **使用 QSplitter**：是
- **集成主题系统**：是

### 主题系统 (theme.py)

- **路径**：/workspace/app/ui/theme.py
- **行数**：433
- **使用 QDockWidget**：否
- **使用 QSplitter**：是
- **集成主题系统**：是


## 💡 集成建议

### 1. 主窗口集成
- 在 MainWindow 中添加 PanelManager
- 使用 QDockWidget 替代现有的右侧栏
- 保持现有布局结构

### 2. 主题集成
- 所有面板继承现有主题系统
- 使用 theme_manager 统一管理
- 监听主题切换信号

### 3. 文件浏览器改造
- 将现有组件包装为 DockablePanel
- 保持功能不变
- 添加浮动和停靠支持

---

**下一步**：开始原型验证
