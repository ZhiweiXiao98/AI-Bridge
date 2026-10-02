# API 模式集成计划

> 历史阶段记录（2026-09-05 整理）：以下原文用于追溯当时的设计、实现与验证；当前能力见[项目状态](当前项目状态.md)，当前测试命令见[测试说明](../tests/README.md)。

## 架构：双消息源(Dual Source)
浏览器消息源(现有) + API消息源(新增)，worker.py 统一调度

## 进度跟踪

### Phase 4: UI 集成 + Worker 对接 —✅ 全部完成

| Step | 任务 | 状态 |
|------|------|------|
| 4.1 | 底层三件套 (ContextManager + ConversationStore + LLMProvider) | ✅ 已完成 |
| 4.2 | APISource 封装层 | ✅ 已完成 |
| 4.3 | ChatPage UI 改造 (Header模式切换/SessionList混合/InputArea分发) | ✅ 已完成 |
| 4.4 | 设置页面集成 (API Key/Base URL/模型/温度等参数) | ✅ 已完成 |
| 4.5 | 上下文可视化面板 (ContextVisualPanel 五层token分配) | ✅ 已完成 |
| 4.6 | Worker API 模式收发逻辑 (api_send/stream/信号) | ✅ 已完成 |
| 4.7 | Worker context_status_signal 定时刷新 | ✅ 已完成 |
| 4.8 | API 对话管理 (新建/切换/删除/重命名) | ✅ 已完成 |
| 4.9 | 集成测试 + 错误处理 | ✅ 已完成 |

## 集成测试结果
-ContextManager: ✅ 五层token追踪正常
- ConversationStore: ✅ 创建/切换/删除/重命名/持久化正常
- LLMProvider: ✅ 配置加载/update_config正常
- APISource: ✅ 初始化/对话管理/上下文状态正常
- 语法检查: 12/12 文件全部通过
- UI组件: 沙盒无PySide6，需桌面环境验证

## 文件清单

### 新增 (5个)
- `app/core/context_manager.py` - 五层上下文管理
- `app/core/conversation_store.py` - 对话持久化
- `app/core/llm_provider.py` - LLM 抽象层
- `app/core/api_source.py` - API 消息源封装
- `app/ui/components/panels/context_visual_panel.py` - 上下文可视化

### 修改 (7个)
- `app/core/worker.py` - 双模式调度
- `app/ui/pages/chat/page.py` - 模式切换+面板集成
- `app/ui/pages/chat/header.py` - 模式切换按钮
- `app/ui/pages/chat/session_list.py` - 混合数据源
- `app/ui/pages/chat/input_area.py` - API发送分发
- `app/ui/components/session_item.py` - source标签
- `app/ui/settings_page.py` - API配置区
