# Skills UI 管理面板集成指南

> 历史阶段记录（2026-09-05 整理）：以下原文用于追溯当时的设计、实现与验证；当前能力见[项目状态](当前项目状态.md)，当前测试命令见[测试说明](../tests/README.md)。

## 已完成的工作

✅ 创建了以下 UI 组件:
1. app/ui/widgets/skill_card.py - Skill 卡片组件
2. app/ui/dialogs/skill_detail_dialog.py - 详情对话框
3. app/ui/dialogs/import_skill_dialog.py - 导入对话框
4. app/ui/panels/skills_panel.py - 主面板

✅ 在 WorkerThread 中添加了:
1. RPC 方法: get_skills_list(), toggle_skill(), get_system_prompt()
2. 信号: skills_data_signal, system_prompt_signal

## 集成步骤

### 1. 在主窗口中导入 SkillsPanel

在主窗口文件顶部添加导入:
from app.ui.panels.skills_panel import SkillsPanel

### 2. 在主窗口的 UI 初始化中添加 Skills 面板

在 setup_ui() 或类似方法中:
self.skills_panel = SkillsPanel()
self.skills_panel.rpc_request.connect(self.handle_skills_rpc)

# 添加到标签页或侧边栏
# 例如，如果有 QTabWidget:
self.tabs.addTab(self.skills_panel, "🎯 Skills")

### 3. 实现 RPC 处理方法

def handle_skills_rpc(self, method, kwargs):
    if hasattr(self.worker, method):
        getattr(self.worker, method)(**kwargs)

### 4. 连接 WorkerThread 的信号到面板

在连接 worker 信号的地方添加:
self.worker.skills_data_signal.connect(self.handle_skills_data)
self.worker.system_prompt_signal.connect(self.handle_system_prompt)

### 5. 实现信号处理方法

def handle_skills_data(self, data):
    if data.get('target_client_id') == 'Host':
        self.skills_panel.update_skills_data(data['skills'])

def handle_system_prompt(self, data):
    if data.get('target_client_id') == 'Host':
        self.skills_panel.display_system_prompt(data['prompt'])

## 完整示例代码

见下方完整的集成示例，展示如何在主窗口中集成 Skills 面板。

## 测试

1. 启动应用
2. 打开 Skills 面板
3. 应该能看到所有已加载的 Skills
4. 测试功能:
   - 查看 Skill 详情
   - 启用/禁用 Skills
   - 查看系统提示词
   - 导入外部 Skills

## 注意事项

1. 启用/禁用功能: 目前 toggle_skill() 只是占位实现，需要在 SkillsManager 中添加实际的启用/禁用逻辑

2. 权限控制: 如果有多用户，需要根据 client_id 判断权限

3. 实时更新: 当 Skills 变化时，可以调用 skills_panel.refresh_skills() 刷新界面

4. 错误处理: 建议在 RPC 方法中添加更完善的错误处理和用户提示
