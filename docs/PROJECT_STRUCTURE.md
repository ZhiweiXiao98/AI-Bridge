# AI Bridge 项目完整导航图 (V13.0 全量版)
> **更新时间**: 2026-05-02
> **状态**: 深度代码扫描，100% 覆盖所有核心文件

---

## 🚀 核心入口 (Launchers)
| 文件路径 | 功能说明 |
| :--- | :--- |
| `boot_remote.py` | 🔌 启动引导程序：检查登录状态并建立通讯连接（支持 --admin/--panel 自动登录） |
| `server.py` | ⚡ 核心中台：消息汇总和同步中心 |
| `start_client.py` | 🚀 客户端启动：用户入口，负责自动升级 |
| `start_server.py` | 🚀 服务端宿主：主机总开关，拉起浏览器和中央枢纽 |

---

## 🧠 业务核心 (App Core)

### 主控层
| 文件路径 | 功能说明 |
| :--- | :--- |
| `app/core/agent_manager.py` | 🧠 **AgentManager**：智能决策，分析 AI 指令，指挥工具执行，角色管理，代码应用/回滚 |
| `app/core/api_source.py` | 🌐 **APISource**：API 消息源——双消息源架构的 API 端，与浏览器消息源对等 |
| `app/core/api_mode_config.py` | ⚙️ **APIModeConfigManager**：API 模式配置管理，多 Profile 支持 |
| `app/core/app_constants.py` | 📋 **应用常量**：APP_NAME/VERSION/ORG/模型列表/端口/忽略规则等全局定义 |
| `app/core/auth_service.py` | 🔐 **AuthService**：用户登录、密码加密、权限控制 |
| `app/core/code_validator.py` | ✅ **CodeValidator**：代码语法校验（Python/JS）、安全检查、代码块提取 |
| `app/core/config.py` | ⚙️ **Config**：全局配置管理，读写软件设置 |
| `app/core/connection_manager.py` | 🔌 **ConnectionManager**：WebSocket 连接管理，消息分发 |
| `app/core/context_manager.py` | 📚 **ContextManager**：上下文管理器核心——消息/系统提示/工作记忆/长期记忆/Token 估算/压缩 |
| `app/core/context_compaction.py` | 🗜️ **ContextCompactor**：上下文压缩器——自动/手动触发，摘要生成 |
| `app/core/context_compaction_state.py` | 📊 **CompactionTracker**：压缩状态追踪（IDLE→COMPACTING→COMPACTED/FAILED） |
| `app/core/context_message_compat.py` | 🔄 **MessageCompat**：消息兼容层，统一不同版本消息格式 |
| `app/core/context_message_models.py` | 📦 **消息数据模型**：MessageRole/MessageKind/ContextMessage/ToolCallInfo/ToolResultInfo/MessageSegment |
| `app/core/context_snapshot_formatter.py` | 📸 **ContextSnapshotFormatter**：上下文快照格式化输出 |
| `app/core/conversation_store.py` | 💾 **ConversationStore**：对话持久化存储（CRUD/列表/消息管理） |
| `app/core/docker_manager.py` | 🐳 **DockerManager**：沙盒指挥官，容器操作/执行/监控 |
| `app/core/execution_history.py` | 📜 **ExecutionHistory**：执行历史记录与统计 |
| `app/core/git_manager.py` | 📦 **GitManager**：Git 操作封装，提交/推送/分支/暂存/差异 |
| `app/core/journal_index.py` | 📓 **JournalIndex**：AI 行驶记录仪索引系统 |
| `app/core/llm_provider.py` | 🤖 **LLMProvider**：LLM 提供者封装，同步/流式/Fallback/Token 计算 |
| `app/core/remote_worker.py` | 🌐 **RemoteWorker**：远程工作器，基于 WebSocket 的远程任务执行+心跳 |
| `app/core/self_update.py` | 🔄 **SelfUpdater**：自动升级，下载补丁+在线更新+回滚 |
| `app/core/worker.py` | 🧵 **Worker**：核心引擎，软件主调度中心，协调所有部件 |

### 回合状态机 (`app/core/round_state/`)
| 文件路径 | 功能说明 |
| :--- | :--- |
| `app/core/round_state/__init__.py` | 📦 模块入口：统一导出 BrowserRoundState / RoundStateSnapshot / RoundStateEvent / BrowserRoundStateMachine |
| `app/core/round_state/round_state_models.py` | 📐 **BrowserRoundState** 枚举（IDLE→AI_STREAMING→PROCESSING→FIXING→TOOL_EXECUTING→SYSTEM_SENDING 六态）+ **RoundStateSnapshot** 数据类（状态/前状态/事件/时间戳/转换计数） |
| `app/core/round_state/round_state_events.py` | 📡 **RoundStateEvent** 枚举：8 种驱动事件 — 轮询检测（BUSY_DETECTED/TO）、流水线（PIPELINE_START/END）、工具（TOOL_EXECUTION_START/RESULT_READY/SEND_COMPLETE/FAILED）、通用（ERROR_RESET/FORCE_IDLE） |
| `app/core/round_state/round_state_machine.py` | 🔄 **BrowserRoundStateMachine**：事件驱动状态机核心 — 合法转换表 `_TRANSITIONS` + 全局事件 `_GLOBAL_EVENTS` + 线程安全 `handle_event()` + 回调通知 `on_state_change()` + 高层方法 `try_pipeline_end()` / `is_idle()` / `is_busy()` / `is_tool_phase()` |

### API 流式处理层 (`app/core/api/`)
| 文件路径 | 功能说明 |
| :--- | :--- |
| `app/core/api/api_stream_handler.py` | 🌊 **APIStreamHandler**：API 流式请求处理器 |
| `app/core/api/api_stream_models.py` | 📐 **StreamStatus/StreamChunk**：流状态枚举与数据块模型 |
| `app/core/api/api_stream_state.py` | 🔧 **APIStreamState**：流状态机（start→append→complete/fail/cancel） |

### 对话引擎 (`app/core/engine/`)
| 文件路径 | 功能说明 |
| :--- | :--- |
| `app/core/engine/conversation_engine.py` | 🧠 **ConversationEngine**：对话引擎，核心对话循环（run→step→call_llm→process_tool_calls） |

### 驱动层 (`app/core/driver/`)
| 文件路径 | 功能说明 |
| :--- | :--- |
| `app/core/driver/config.py` | ⚙️ **DriverConfig**：浏览器自动化配置管理（CDP URL） |
| `app/core/driver/connection.py` | 🔗 **DriverConnection**：CDP 连接管理，与 Chrome 建立通讯通道 |
| `app/core/driver/interaction.py` | 🖱️ **DriverInteraction**：模拟点击、打字、滚动、截图、DOM 获取 |
| `app/core/driver/parser.py` | 🧹 **DriverParser**：浏览器消息解析，提取代码块/清理文本 |

### 调试工具 (`app/core/debug/`)
| 文件路径 | 功能说明 |
| :--- | :--- |
| `app/core/debug/probe.py` | 🔍 **DebugProbe**：调试探针，性能快照/指标收集 |

### 知识库系统 (`app/core/knowledge/`)
| 文件路径 | 功能说明 |
| :--- | :--- |
| `app/core/knowledge/cache.py` | 📦 **EmbeddingCache**：嵌入向量缓存（get/set/invalidate/clear） |
| `app/core/knowledge/chunker.py` | ✂️ **TextChunker**：文本分块器（段落/代码块分割+小段合并） |
| `app/core/knowledge/config.py` | ⚙️ **KnowledgeConfig**：知识库配置（嵌入模型/分块大小/Top-K） |
| `app/core/knowledge/embedder.py` | 🧮 **Embedder**：文本嵌入器（单条/批量嵌入） |
| `app/core/knowledge/executor.py` | 🚀 **KnowledgeExecutor**：知识库执行器（搜索+RAG+重排序） |
| `app/core/knowledge/reindex_runner.py` | 🔄 **ReindexRunner**：重建索引运行器（进度/取消） |
| `app/core/knowledge/reranker.py` | 📊 **Reranker**：搜索结果重排序（评分+归一化） |
| `app/core/knowledge/service.py` | 🎯 **KnowledgeService**：知识库服务门面（索引/搜索/管理） |

### 日志系统 (`app/core/logging/`)
| 文件路径 | 功能说明 |
| :--- | :--- |
| `app/core/logging/log_manager.py` | 📝 **LogManager**：日志管理器（级别设置/Handler 管理） |
| `app/core/logging/noise_control.py` | 🔇 **NoiseControl**：日志噪声控制（模式过滤/抑制规则） |
| `app/core/logging/trace_context.py` | 🔗 **TraceContext**：追踪上下文（trace ID/标签管理） |

### 解析器 (`app/core/parsers/`)
| 文件路径 | 功能说明 |
| :--- | :--- |
| `app/core/parsers/markdown_code_block_parser.py` | 📖 **MarkdownCodeBlockParser**：Markdown 代码块解析器 |

### Prompt 运行时 (`app/core/prompt_runtime/`)
| 文件路径 | 功能说明 |
| :--- | :--- |
| `app/core/prompt_runtime/prompt_assembler.py` | 🔧 **PromptAssembler**：Prompt 组装器（系统/上下文/Skills/历史/模板） |
| `app/core/prompt_runtime/prompt_file_loader.py` | 📂 **PromptFileLoader**：Prompt 文件加载器（路径解析/变量替换/热重载） |
| `app/core/prompt_runtime/skills_prompt_loader.py` | 🎯 **SkillsPromptLoader**：技能 Prompt 加载器（Skill MD 加载/合并） |
| `app/core/prompt_runtime/system_policy_loader.py` | 📜 **SystemPolicyLoader**：系统策略加载器（策略文件加载/合并） |

### Skills 系统 (`app/core/skills/`)
| 文件路径 | 功能说明 |
| :--- | :--- |
| `app/core/skills/manager.py` | 🎯 **SkillManager**：技能管理器（注册/注销/执行/重载） |
| `app/core/skills/loader.py` | 📥 **SkillLoader**：技能加载器（解析 SKILL.md/目录/模块加载） |
| `app/core/skills/base.py` | 🧱 **BaseSkill(ABC)**：技能基类（execute/validate/get_schema/get_prompt） |

#### 内置 Skills — 代码执行
| 文件路径 | 功能说明 |
| :--- | :--- |
| `app/core/skills/core/code_execution/skill.py` | ⚡ **CodeExecutionSkill**：沙盒执行 Python 代码 |

#### 内置 Skills — 文件操作（最大模块，14 文件）
| 文件路径 | 功能说明 |
| :--- | :--- |
| `app/core/skills/core/file_operations/skill.py` | 📂 **FileOperationsSkill**：文件操作技能入口（分发路由） |
| `app/core/skills/core/file_operations/block_ops.py` | 📦 块操作：read_block/write_block/replace_block |
| `app/core/skills/core/file_operations/delete_ops.py` | 🗑️ 删除操作：delete_lines/delete_range/delete_file |
| `app/core/skills/core/file_operations/edit_ops.py` | ✏️ 编辑操作：edit_lines/replace_lines/insert_lines |
| `app/core/skills/core/file_operations/line_ops.py` | 📏 行操作：read_lines/count_lines/get_line |
| `app/core/skills/core/file_operations/path_utils.py` | 🛤️ 路径工具：resolve/normalize/is_safe/ensure_extension |
| `app/core/skills/core/file_operations/persist_ops.py` | 💾 持久化：save_file/load_file/atomic_write |
| `app/core/skills/core/file_operations/read_ops.py` | 📖 读取：read_file/read_file_lines/search_in_file |
| `app/core/skills/core/file_operations/result_utils.py` | 📋 结果格式化：format_result/make_error/make_success |
| `app/core/skills/core/file_operations/safety_ops.py` | 🛡️ 安全检查：路径安全/内容安全/受限路径 |
| `app/core/skills/core/file_operations/structural_guard.py` | 🏗️ 结构守卫：AST 校验/结构检测 |
| `app/core/skills/core/file_operations/tmp_validate.py` | 🔧 临时文件：validate_temp_file/cleanup_temp |
| `app/core/skills/core/file_operations/validators.py` | ✅ 验证器：路径/编码/大小校验 |
| `app/core/skills/core/file_operations/write_ops.py` | 📝 写入：write_file/append_file/create_file |

#### 内置 Skills — 知识搜索
| 文件路径 | 功能说明 |
| :--- | :--- |
| `app/core/skills/core/knowledge_search/skill.py` | 🔍 **KnowledgeSearchSkill**：RAG 语义搜索 |

#### 内置 Skills — 网络搜索（🆕 新增）
| 文件路径 | 功能说明 |
| :--- | :--- |
| `app/core/skills/core/web_search/skill.py` | 🌐 **WebSearchSkill**：网络搜索入口 |
| `app/core/skills/core/web_search/config.py` | ⚙️ **WebSearchConfig**：搜索配置 |
| `app/core/skills/core/web_search/providers/base.py` | 🧱 **BaseSearchProvider(ABC)**：搜索提供者基类 |
| `app/core/skills/core/web_search/providers/duckduckgo.py` | 🦆 **DuckDuckGoProvider**：DuckDuckGo 搜索 |
| `app/core/skills/core/web_search/providers/searxng.py` | 🔎 **SearXNGProvider**：SearXNG 搜索 |
| `app/core/skills/core/web_search/providers/tavily.py` | 🔍 **TavilyProvider**：Tavily 搜索 |

#### 外部 Skills
| 文件路径 | 功能说明 |
| :--- | :--- |
| `app/core/skills/external/` | 🔌 外部 Skills 目录（用户自定义扩展） |

### 工具运行时 (`app/core/tool_runtime/`)
| 文件路径 | 功能说明 |
| :--- | :--- |
| `app/core/tool_runtime/conversation_loop.py` | 🔄 **ConversationLoop**：对话循环控制器 |
| `app/core/tool_runtime/executor.py` | ⚡ **ToolExecutor**：工具执行器（分发/沙盒/超时） |
| `app/core/tool_runtime/models.py` | 📐 **ToolCall/ToolResult/ExecutionPlan**：工具调用数据模型 |
| `app/core/tool_runtime/policies.py` | 🚦 **ToolPolicy**：工具策略（权限检查/限制/应用） |
| `app/core/tool_runtime/segment_parser.py` | 📑 **SegmentParser**：响应分段解析器 |
| `app/core/tool_runtime/task_meta.py` | 📋 **TaskMeta**：任务元数据（创建/更新/完成/失败） |

### 服务层 (`app/core/services/`)
| 文件路径 | 功能说明 |
| :--- | :--- |
| `app/core/services/context_pack_service.py` | 📦 **ContextPackService**：上下文打包（创建/加载/保存/列表） |
| `app/core/services/context_scanner.py` | 🔍 **ContextScanner**：上下文扫描器（目录扫描/忽略规则/树构建） |
| `app/core/services/file_service.py` | 📂 **FileService**：文件管家（读写/搜索/grep/安全操作） |
| `app/core/services/knowledge_service.py` | 🧠 **KnowledgeServiceFacade**：RAG 语义检索服务门面 |
| `app/core/services/scheduler_service.py` | 📋 **SchedulerService**：任务调度（计划/取消/暂停/恢复） |
| `app/core/services/state_service.py` | 💾 **StateService**：状态管理（观察者模式/通知） |
| `app/core/services/tool_router_service.py` | 🚦 **ToolRouterService**：指令路由（注册/验证/分发） |
| `app/core/services/update_service.py` | 📦 **UpdateService**：更新分发（检查/下载/应用/变更日志） |

### 工具层 (`app/core/utils/`)
| 文件路径 | 功能说明 |
| :--- | :--- |
| `app/core/utils/error_reporter.py` | 🚨 **ErrorReporter**：错误报告器（格式化/上下文收集/历史） |
| `app/core/utils/pseudocode_generator.py` | 🇨🇳 **PseudocodeGenerator**：伪代码生成器（Python→中文伪代码） |
| `app/core/utils/text_utils.py` | 📝 **文本工具**：truncate/count_tokens_approx/strip_ansi/normalize_whitespace/extract_json |

### Worker 子模块 (`app/core/worker_modules/`)
| 文件路径 | 功能说明 |
| :--- | :--- |
| `app/core/worker_modules/worker_api_stream.py` | 🌊 **WorkerAPIStream**：Worker API 流处理（chunk/complete/cancel） |
| `app/core/worker_modules/worker_knowledge_tasks.py` | 🔍 **WorkerKnowledgeTasks**：Worker 知识库任务（重索引/搜索/取消） |

---

## 🖼️ 用户界面 (UI)

### 主窗口
| 文件路径 | 功能说明 |
| :--- | :--- |
| `app/ui/main_window.py` | 🏗️ **MainWindow**：主窗口核心，页面切换/面板系统/插件管理/沙箱/布局/远程/Git 集成 |
| `app/ui/login_window.py` | 🔐 **LoginWindow**：登录窗口，用户认证界面 |
| `app/ui/theme.py` | 🎨 **ThemeManager/Theme/DynamicPalette**：主题系统+全局样式生成器 |
| `app/ui/widgets.py` | 📦 旧版 widgets（已迁移至 components/） |

### 功能页面（根级）
| 文件路径 | 功能说明 |
| :--- | :--- |
| `app/ui/modeling_page.py` | 🏗️ **ModelingPage**：项目结构建模和可视化 |
| `app/ui/settings_page.py` | ⚙️ **SettingsPage**：设置页（API/Fallback/上下文/主题/同步/黑名单） |

### 面板管理系统 (`app/ui/managers/`)
| 文件路径 | 功能说明 |
| :--- | :--- |
| `app/ui/managers/panel_manager.py` | 🎛️ **PanelManager**：面板管理器（注册/显示/布局保存加载/图标栏） |
| `app/ui/managers/workspace_manager.py` | 💼 **WorkspaceManager**：工作区预设管理器（保存/加载/删除/默认预设） |

### 面板插件系统 (`app/ui/plugins/`)
| 文件路径 | 功能说明 |
| :--- | :--- |
| `app/ui/plugins/base_panel_plugin.py` | 🧱 **BasePanelPlugin(ABC)**：面板插件基类（生命周期/配置/状态管理） |
| `app/ui/plugins/panel_plugin_loader.py` | 🔌 **PanelPluginLoader**：面板插件加载器（扫描/加载/依赖检查/验证） |

### 通用组件 (`app/ui/components/`)
| 文件路径 | 功能说明 |
| :--- | :--- |
| `app/ui/components/base.py` | 🧱 **BaseComponent**：组件基类 |
| `app/ui/components/chat.py` | 💬 **ChatBubble**：聊天气泡组件 |
| `app/ui/components/chat_bubble_stream.py` | 🌊 **ChatBubbleStream**：流式聊天气泡（append/finalize/reset） |
| `app/ui/components/animated_reorder_container.py` | ✨ **AnimatedReorderContainer**：动画重排序容器 |
| `app/ui/components/collapsible_sidebar.py` | 📐 **CollapsibleSidebar**：可折叠侧边栏 |
| `app/ui/components/dockable_panel.py` | 📌 **DockablePanel**：可停靠面板基类 |
| `app/ui/components/editor.py` | 🖍️ **CodeEditor**：代码编辑器（语法高亮/行号） |
| `app/ui/components/icon_bar.py` | 🎯 **IconBar**：图标栏 |
| `app/ui/components/input.py` | ⌨️ **InputWidget**：增强输入框 |
| `app/ui/components/overlay.py` | 🌫️ **Overlay**：遮罩层 |
| `app/ui/components/panel_icons.py` | 🖼️ 面板图标获取工具 |
| `app/ui/components/preview_dialog.py` | 👁️ **PreviewDialog**：预览对话框 |
| `app/ui/components/session_item.py` | 📝 **SessionItem**：会话列表项 |
| `app/ui/components/task_panel.py` | ✅ **TaskPanel**：任务面板 |
| `app/ui/components/theme_editor.py` | 🎨 **ThemeEditor**：主题编辑器对话框 |
| `app/ui/components/tool_call_card.py` | 🔧 **ToolCallCard**：工具调用卡片（状态/结果展示） |

### 面板组件 (`app/ui/components/panels/`)
| 文件路径 | 功能说明 |
| :--- | :--- |
| `app/ui/components/panels/code_review_panel.py` | 🔍 **CodeReviewPanel**：代码审查面板 |
| `app/ui/components/panels/context_workspace_panel.py` | 📚 **ContextWorkspacePanel**：上下文工作区面板 |
| `app/ui/components/panels/context_workspace_panel_logic.py` | 🧠 **ContextWorkspacePanelLogic**：上下文工作区面板逻辑（MVP-Presenter） |
| `app/ui/components/panels/context_workspace_panel_presenter.py` | 🎯 **ContextWorkspacePanelPresenter**：上下文工作区面板展示器 |
| `app/ui/components/panels/git_config_dialog.py` | ⚙️ **GitConfigDialog**：Git 配置对话框 |
| `app/ui/components/panels/git_control_panel.py` | 📦 **GitControlPanel**：Git 控制面板 |
| `app/ui/components/panels/git_control_panel_logic.py` | 🧠 **GitControlPanelLogic**：Git 控制面板逻辑 |
| `app/ui/components/panels/git_control_panel_presenter.py` | 🎯 **GitControlPanelPresenter**：Git 控制面板展示器 |
| `app/ui/components/panels/runtime_log_panel.py` | 📝 **RuntimeLogPanel**：运行日志面板（含级别/来源筛选+实时搜索+高亮） |
| `app/ui/components/panels/sandbox_monitor_panel.py` | 🐳 **SandboxMonitorPanel**：Docker 容器状态监控 |
| `app/ui/components/panels/task_schedule_panel.py` | 📋 **TaskSchedulePanel**：任务调度面板 |

### 设置组件 (`app/ui/components/settings/`)
| 文件路径 | 功能说明 |
| :--- | :--- |
| `app/ui/components/settings/knowledge_rules_card.py` | 📋 **KnowledgeRulesCard**：知识规则卡片（加载/保存/增删规则） |

### 对话框 (`app/ui/dialogs/`)
| 文件路径 | 功能说明 |
| :--- | :--- |
| `app/ui/dialogs/context_detail_dialog.py` | 📋 **ContextDetailDialog**：上下文详情对话框 |
| `app/ui/dialogs/context_snapshot_dialog.py` | 📸 **ContextSnapshotDialog**：上下文快照调试浮窗 |
| `app/ui/dialogs/context_workspace_common_phrases_dialog.py` | 💬 **ContextWorkspaceCommonPhrasesDialog**：常用短语对话框（增删/选择/发送） |
| `app/ui/dialogs/context_workspace_plan_binding_dialog.py` | 📌 **ContextWorkspacePlanBindingDialog**：工作区计划绑定对话框 |
| `app/ui/dialogs/plugin_detail_dialog.py` | 🔌 **PluginDetailDialog**：插件详情对话框（信息/依赖/配置/README 标签页） |

### UI 日志 (`app/ui/logging/`)
| 文件路径 | 功能说明 |
| :--- | :--- |
| `app/ui/logging/qt_log_handler.py` | 🌉 **LogPanelBridge + QtPanelLogHandler**：将标准 logging 桥接到 Qt Signal（跨线程安全） |

### 面板 (`app/ui/panels/`)
| 文件路径 | 功能说明 |
| :--- | :--- |
| `app/ui/panels/plugin_manager_panel.py` | 🔌 **PluginManagerPanel**：插件管理面板（加载/切换/详情/刷新） |

### 聊天页面 (`app/ui/pages/chat/`) — 最大 UI 模块
| 文件路径 | 功能说明 |
| :--- | :--- |
| `app/ui/pages/chat/page.py` | 💬 **ChatPage**：聊天主页面（模式切换/会话/消息/暂存区/上下文） |
| `app/ui/pages/chat/header.py` | 📌 **ChatHeader**：聊天头部（状态/同步/健康度/延迟/模式切换） |
| `app/ui/pages/chat/input_area.py` | ⌨️ **InputArea**：输入区域（发送/附件/粘贴/暂存区控制） |
| `app/ui/pages/chat/message_area.py` | 📜 **MessageArea**：消息展示（滚动/多选/渲染/工具卡/状态） |
| `app/ui/pages/chat/message_area_stream.py` | 🌊 **MessageAreaStreamManager**：流式消息区域管理（流气泡/打字指示器） |
| `app/ui/pages/chat/chat_page_stream.py` | 🔄 **ChatPageStreamManager**：聊天页面流管理（chunk→bubble） |
| `app/ui/pages/chat/session_list.py` | 📋 **SessionList**：Browser 模式会话列表 |
| `app/ui/pages/chat/api_session_list.py` | 📋 **APISessionList**：API 模式会话列表（新建/重命名/置顶/删除） |
| `app/ui/pages/chat/services/message_window_service.py` | 🪟 **MessageWindowService**：消息窗口服务（browser/api 两模式可见轮数管理） |

### 其他页面 (`app/ui/pages/`)
| 文件路径 | 功能说明 |
| :--- | :--- |
| `app/ui/pages/code_review_page.py` | 🔍 **CodeReviewPage**：代码审查页（扫描/远程/预览/应用/暂存区） |
| `app/ui/pages/console_page.py` | 🛠️ **ConsolePage**：控制台页（测试仪表板/用户管理/统计卡片） |
| `app/ui/pages/context_page.py` | 📚 **ContextPage**：上下文页（扫描/依赖雷达/树视图/跳转/AI 发送） |

### 样式文件
| 文件路径 | 功能说明 |
| :--- | :--- |
| `app/ui/styles.qss` | 🎨 QSS 样式表：定义所有 UI 元素的外观 |

---

## 📱 手机客户端 (Mobile — Flet)

基于 **Flet** (Python → Flutter → APK) 框架的 Android 手机客户端，局域网内连接 AI Bridge 服务端，支持浏览器模式和 API 模式收发消息。详见 [mobile/MAINTENANCE.md](../mobile/MAINTENANCE.md)。

### 入口与配置
| 文件路径 | 功能说明 |
| :--- | :--- |
| `mobile/main.py` | 📱 **入口**：Flet 应用启动、路由分发、WebSocket 生命周期管理 |
| `mobile/requirements_mobile.txt` | 📦 **依赖**：flet / websockets / httpx / pygments |
| `mobile/build_android.bat` | 🔨 **构建脚本(BAT)**：一键打包 APK |
| `mobile/build_android.ps1` | 🔨 **构建脚本(PS1)**：PowerShell 版 APK 构建 |
| `mobile/precache_gradle.bat` | 📦 **Gradle 预缓存(BAT)** |
| `mobile/precache_gradle.ps1` | 📦 **Gradle 预缓存(PS1)** |
| `mobile/MAINTENANCE.md` | 📖 **维护指南**：架构说明、协议对接、常见修改场景、故障排查 |

### 服务层 (Services)
| 文件路径 | 功能说明 |
| :--- | :--- |
| `mobile/services/api.py` | 🌐 **BridgeAPI**：HTTP REST 封装（登录/消息同步/会话同步） |
| `mobile/services/ws_client.py` | 🔌 **WSClient**：WebSocket 客户端（连接/心跳/RPC/通知分发） |
| `mobile/services/message_parser.py` | 📝 **消息解析**：服务端 JSON → TextSegment/CodeSegment/ImageSegment/ToolResultSegment |
| `mobile/services/html_converter.py` | 🔄 **HTML→Markdown**：HTML 片段转 Markdown 纯文本 |

### 状态管理
| 文件路径 | 功能说明 |
| :--- | :--- |
| `mobile/state/app_state.py` | 💾 **AppState**：全局状态单例（连接/模式/消息/AI 状态/流式/登录记忆） |

### 界面层 (UI)
| 文件路径 | 功能说明 |
| :--- | :--- |
| `mobile/ui/login_page.py` | 🔐 **登录页**：输入服务器 IP/端口/账号密码 |
| `mobile/ui/chat_page.py` | 💬 **聊天主页**：消息列表 + 输入栏 + WebSocket 事件驱动 |
| `mobile/ui/session_drawer.py` | 📋 **会话侧边栏**：NavigationDrawer 风格 |
| `mobile/ui/settings_page.py` | ⚙️ **设置页**：浏览器/API 模式切换 |

### UI 组件
| 文件路径 | 功能说明 |
| :--- | :--- |
| `mobile/ui/components/code_block.py` | 🎨 **代码块**：pygments 语法高亮 + 复制 + 应用修改按钮 |
| `mobile/ui/components/message_bubble.py` | 💬 **消息气泡**：AI/User 气泡 + Markdown + 图片 + 工具结果 |
| `mobile/ui/components/status_bar.py` | 📊 **状态栏**：连接状态 + 延迟 + AI 状态 + 模式标签 |

### 工具
| 文件路径 | 功能说明 |
| :--- | :--- |
| `mobile/utils/device_id.py` | 🆔 **设备 ID**：生成唯一 Mobile_xxxxxxxx 标识 |
| `mobile/utils/ui_helpers.py` | 🛠️ **UI 辅助**：SnackBar / 剪贴板复制 |

---

## 🦏 Rhino 集成

### 独立脚本
| 文件路径 | 功能说明 |
| :--- | :--- |
| `rhino/rhino_listener.py` | 👂 **Rhino 监听器 v2.0**：0.2 秒轮询 export/code/rhino/ 目录变动，安全执行脚本 |

### Rhino 插件版
| 文件路径 | 功能说明 |
| :--- | :--- |
| `rhino_plugin/AIBridge/__init__.py` | 🔌 **Rhino 插件入口**：OnLoad → start_polling，插件 ID 97799564 |
| `rhino_plugin/AIBridge/listener.py` | 👂 **插件版监听器**：1 秒轮询 C:\AI_Bridge_Workspace\export\code\rhino |

### RhinoBIM C# 客户端
| 文件路径 | 功能说明 |
| :--- | :--- |
| `RhinoBIM_Client/RhinoBIMPlugin.cs` | 🦏 **C# 插件入口** |
| `RhinoBIM_Client/BIMPanel.cs` | 📋 **BIM 面板** (C# WPF) |
| `RhinoBIM_Client/RhinoBIM.csproj` | 📦 **项目文件** (.NET Framework 4.8) |

---

## 🧪 实验性功能 (Experimental)

| 文件路径 | 功能说明 |
| :--- | :--- |
| `experimental/chat_ui.py` | 💬 **实验聊天窗口** (PySide6)：对话列表+聊天+Token 状态三栏 |
| `experimental/server.py` | 🖥️ **实验服务端** (FastAPI :8100)：REST API 对话管理+流式聊天(SSE) |
| `experimental/conversations/` | 💾 实验对话存储（4 个 JSON 文件） |

---

## 🔌 插件系统 (Plugins)

```
plugins/
└── panels/
    ├── README.md                    # 面板插件开发指南
    ├── example_panel/               # 示例面板插件
    │   ├── plugin.json              # 插件元数据
    │   ├── plugin.py                # ExamplePanelPlugin(BasePanelPlugin)
    │   └── panel.py                 # ExamplePanel(DockablePanel)
    └── skills_panel/                # Skills 管理面板插件
        ├── plugin.json              # 插件元数据
        ├── plugin.py                # SkillsPanelPlugin(BasePanelPlugin)
        └── panel.py                 # SkillCard + SkillsPanelWidget(DockablePanel)
```

| 插件 | 说明 |
| :--- | :--- |
| **example_panel** | 示例面板：信息组+控制组+日志组+定时器，演示完整插件生命周期 |
| **skills_panel** | Skills 管理：筛选/搜索/刷新/导入/生成提示词，RPC 远程/本地双模式 |

---

## 📜 提示词系统 (Prompt)

5 层架构设计，详见 [Prompt/README.md](../Prompt/README.md)

| 文件路径 | 功能说明 |
| :--- | :--- |
| `Prompt/README.md` | 📖 5 层提示词架构设计文档 |
| `Prompt/Build_SystemPrompt.md` | 🔧 **构建模式**：工程实施工程师，全部工具权限，严格 tool_call 格式 |
| `Prompt/Plan_SystemPrompt.md` | 📋 **计划模式**：智能分析师，只读权限，禁止写入/执行 |
| `Prompt/兼容提示词.md` | 🔄 完整 10 步协作流程，Plan/Build 模式划分 |
| `Prompt/用户偏好.md` | ⚙️ 7 大类偏好（沟通/代码/工具/项目/输出/模式/新增） |
| `Prompt/系统提示词.md` | 🎯 整合版：兼容层+Plan+Build 模式定义 |

---

## ⚙️ 配置文件 (Config)

| 文件路径 | 功能说明 |
| :--- | :--- |
| `config.json` | 🏠 主配置：导出路径/Chrome 端口/知识库/主题/服务器地址 |
| `app_state.json` | 📊 应用运行状态：消息索引/对话哈希 |
| `launcher_settings.json` | 🚀 启动器设置：Chrome 路径 |
| `config/api_mode.json` | 🤖 API 模式配置：多 Provider Profile（default/gemini/deepseek） |
| `config/api_mode.example.json` | 📋 API 模式配置示例 |
| `config/panel_layout.json` | 📐 当前面板布局 |
| `config/panel_layout_default.json` | 📐 默认面板布局 |
| `config/plugins.json` | 🔌 插件启用状态 |
| `config/conversations/` | 💾 对话存储（索引+7 个对话 JSON） |
| `config/workspace_presets/` | 💼 工作区预设（debug/default/minimal） |

---

## 📚 前端库 (Lib)

| 文件路径 | 功能说明 |
| :--- | :--- |
| `lib/vis-9.1.2/vis-network.min.js` | 🕸️ vis-network 网络图库 |
| `lib/vis-9.1.2/vis-network.css` | 🎨 网络图样式 |
| `lib/tom-select/tom-select.complete.min.js` | 📋 Tom Select 下拉选择器 |
| `lib/tom-select/tom-select.css` | 🎨 下拉选择器样式 |
| `lib/bindings/utils.js` | 🔧 vis-network 图谱高亮/筛选工具函数 |

---

## 🔧 开发工具集 (Tools)

### 环境管理
| 文件路径 | 功能说明 |
| :--- | :--- |
| `tools/setup_env.py` | 🔧 环境初始化：一键配置开发环境 |
| `tools/check_env_status.py` | ✅ 环境检查：验证依赖和配置是否正确 |
| `tools/install_reqs.py` | 📦 依赖安装：批量安装 requirements.txt |
| `tools/install_plugins.py` | 🔌 插件安装：安装扩展插件 |

### Skills 管理工具
| 文件路径 | 功能说明 |
| :--- | :--- |
| `tools/generate_skills_prompt.py` | 🎯 **提示词生成器**：扫描 Skills 并生成系统提示词 |

### RAG 知识库管理
| 文件路径 | 功能说明 |
| :--- | :--- |
| `tools/reindex_project.py` | 🔍 **语义索引器**：扫描源码构建向量数据库 |
| `tools/rebuild_knowledge_index.py` | 🔄 重建索引：清空并重建知识库索引 |
| `tools/query_knowledge_base.py` | 🔎 知识查询：测试 RAG 检索功能 |
| `tools/fix_rag_db.py` | 🔧 修复数据库：修复损坏的向量数据库 |
| `tools/hard_purge_knowledge.py` | 🗑️ 清空知识库：完全删除所有索引数据 |
| `tools/verify_rag_functionality.py` | ✅ RAG 验证：测试 RAG 功能是否正常 |
| `tools/test_rag_query.py` | 🧪 查询测试：测试语义检索准确性 |

### 测试工具
| 文件路径 | 功能说明 |
| :--- | :--- |
| `tools/run_tests.py` | 🧪 测试运行器：执行所有单元测试 |
| `tools/_diagnose_test_framework.py` | 🔍 测试诊断：诊断测试框架问题 |
| `tools/test_code_extraction.py` | 🧪 代码提取测试：测试代码解析功能 |

### 调试工具
| 文件路径 | 功能说明 |
| :--- | :--- |
| `tools/debug_scout.py` | 🐛 调试侦察：快速定位代码问题 |
| `tools/inspect_code_block.py` | 🔍 代码块检查：分析代码块执行情况 |

### 打包部署
| 文件路径 | 功能说明 |
| :--- | :--- |
| `tools/pack_dist.py` | 📦 打包工具：生成可分发的安装包 |
| `tools/smart_update_structure.py` | 🔄 智能更新：自动更新项目结构文档 |

### 可视化工具
| 文件路径 | 功能说明 |
| :--- | :--- |
| `tools/visualize_architecture.py` | 📊 架构可视化：生成项目架构图 |

### 用户管理
| 文件路径 | 功能说明 |
| :--- | :--- |
| `tools/user_manager.py` | 👥 用户管理：添加、删除、修改用户 |

---

## 🛠️ 辅助脚本 (Root Scripts)

| 文件路径 | 功能说明 |
| :--- | :--- |
| `cleanup_battlefield.py` | 🧹 清理临时文件/备份（backup/fix_*/emergency_*） |
| `create_icons.py` | 🎨 用 Pillow 生成 64x64 占位图标（chat/draw/music/settings/video） |
| `detective.py` | 🔍 Selenium 侦探：连接 Chrome 调试端口扫描页面元素 |
| `dump_code.py` | 📄 项目代码快照：合并源码到 FULL_PROJECT_CONTEXT.txt |
| `make_portable.py` | 📦 制作绿色免安装客户端包 |
| `print_tree.py` | 🌳 打印项目目录树 |

---

## 🏗️ 打包配置

| 文件路径 | 功能说明 |
| :--- | :--- |
| `AI_Client.spec` | 📦 PyInstaller 配置：入口 boot_remote.py → AI_Client.exe |
| `build_and_test_pyside6.sh` | 🧪 PySide6 构建测试脚本 |

---

## 📊 项目统计

- **app/ Python 文件**: 172 个（不含 __pycache__）
- **核心模块**: 15 个功能子模块（API 流/驱动/引擎/知识库/日志/Prompt/服务/技能/工具运行时/Worker 子模块/调试/解析器/工具函数/主控层/回合状态机）
- **UI 组件**: 16 个通用组件 + 11 个面板组件 + 5 个对话框 + 1 个设置组件
- **功能页面**: 3 个根级页面 + 4 个子页面 + 9 个聊天页面子模块
- **面板插件**: 2 个（example_panel + skills_panel）
- **手机客户端**: 13 个 Python 文件（Flet / Android）
- **Rhino 集成**: 3 个入口（独立脚本/Python 插件/C# 插件）
- **实验功能**: 2 个 Python 文件（FastAPI 服务端 + PySide6 客户端）
- **开发工具**: 15+ 个辅助工具
- **提示词系统**: 6 个 Markdown 文件（5 层架构）
- **配置文件**: 13+ 个 JSON 文件

---

## 🎯 快速导航

### 想要理解浏览器模式状态机？
→ `app/core/round_state/` + `app/core/worker.py`（`_on_round_state_change` 回调）

### 想要理解双消息源架构？
→ `app/core/api_source.py`（API 模式）+ `app/core/driver/`（Browser 模式）+ `app/core/worker.py`（统一调度）

### 想要理解对话系统？
→ `app/ui/pages/chat/` + `app/core/engine/conversation_engine.py` + `app/core/context_manager.py`

### 想要理解上下文压缩？
→ `app/core/context_compaction.py` + `app/core/context_compaction_state.py` + `app/core/context_manager.py`

### 想要理解代码执行？
→ `app/core/services/tool_router_service.py` + `app/core/docker_manager.py` + `app/core/tool_runtime/`

### 想要理解 RAG 检索？
→ `app/core/knowledge/` + `app/core/services/knowledge_service.py` + `tools/reindex_project.py`

### 想要理解 Skills 系统？
→ `app/core/skills/manager.py` + `plugins/panels/skills_panel/` + `tools/generate_skills_prompt.py`

### 想要理解面板管理？
→ `app/ui/managers/panel_manager.py` + `app/ui/components/panels/` + `app/ui/plugins/`

### 想要理解面板插件开发？
→ `app/ui/plugins/base_panel_plugin.py` + `plugins/panels/example_panel/` + `plugins/panels/README.md`

### 想要理解流式消息？
→ `app/core/api/api_stream_handler.py` + `app/ui/pages/chat/chat_page_stream.py` + `app/ui/pages/chat/message_area_stream.py`

### 想要理解 Prompt 组装？
→ `app/core/prompt_runtime/prompt_assembler.py` + `Prompt/` + `app/core/prompt_runtime/system_policy_loader.py`

### 想要理解手机客户端？
→ `mobile/main.py` + `mobile/ui/chat_page.py` + `mobile/MAINTENANCE.md`

### 想要理解 Rhino 集成？
→ `rhino/rhino_listener.py` + `rhino_plugin/AIBridge/` + `RhinoBIM_Client/`

### 想要理解日志系统？
→ `app/core/logging/` + `app/ui/logging/qt_log_handler.py` + `app/ui/components/panels/runtime_log_panel.py`

### 想要理解主题系统？
→ `app/ui/theme.py` + `app/ui/components/theme_editor.py`

---

## 🏛️ 核心架构特征

1. **双消息源架构**: `APISource`（API 模式）和浏览器驱动（Browser 模式）对等，由 `Worker` 统一调度
2. **MVP 模式**: 面板组件使用 Model-View-Presenter 分离（如 Git 控制面板、上下文工作区面板）
3. **技能系统**: 基于 `BaseSkill(ABC)` 的可插拔技能，内置代码执行/文件操作/知识搜索/网络搜索四大能力
4. **流式架构**: 完整的流式处理链 `APIStreamHandler` → `APIStreamState` → `ChatPageStreamManager` → `MessageAreaStreamManager`
5. **上下文压缩**: 独立压缩模块（`ContextCompactor` + `CompactionTracker`），支持自动/手动触发
6. **5 层 Prompt 架构**: 系统提示词→当前任务→长期记忆→短期记忆→当前对话
7. **面板插件系统**: `BasePanelPlugin(ABC)` 定义生命周期，`PanelPluginLoader` 负责扫描加载
8. **Rhino 双模式集成**: 独立脚本监听 + Rhino 插件版 + C# BIM 面板
9. **回合状态机**: `BrowserRoundStateMachine` 事件驱动六态 FSM（IDLE→AI_STREAMING→PROCESSING→FIXING→TOOL_EXECUTING→SYSTEM_SENDING），替代 Worker 中散落的状态赋值，线程安全 + 回调通知

---

## 🆕 V12.0 更新内容 (2026-04-29)

### 深度代码扫描新增覆盖
1. **API 流式处理层** (`app/core/api/`)
   - APIStreamHandler / APIStreamState / StreamStatus 完整流式状态机

2. **上下文管理系统** (核心新增)
   - ContextManager：消息/系统提示/工作记忆/长期记忆统一管理
   - ContextCompactor + CompactionTracker：自动/手动上下文压缩
   - ContextMessageModels：MessageRole/MessageKind/ContextMessage 等数据模型
   - MessageCompat：消息版本兼容层
   - ContextSnapshotFormatter：快照格式化

3. **对话持久化** — ConversationStore（CRUD/列表/消息管理）

4. **LLM Provider** — 同步/流式/Fallback/Token 计算

5. **知识库子系统** (`app/core/knowledge/`)
   - 7 个模块：Cache/Chunker/Config/Embedder/Executor/ReindexRunner/Reranker/Service

6. **日志子系统** (`app/core/logging/`)
   - LogManager / NoiseControl / TraceContext

7. **Prompt 运行时** (`app/core/prompt_runtime/`)
   - PromptAssembler / PromptFileLoader / SkillsPromptLoader / SystemPolicyLoader

8. **工具运行时** (`app/core/tool_runtime/`)
   - ConversationLoop / ToolExecutor / Models / Policies / SegmentParser / TaskMeta

9. **Worker 子模块** (`app/core/worker_modules/`)
   - WorkerAPIStream / WorkerKnowledgeTasks

10. **网络搜索 Skill** (`app/core/skills/core/web_search/`)
    - DuckDuckGo / SearXNG / Tavily 三引擎

11. **新增 UI 模块**
    - ChatBubbleStream：流式聊天气泡
    - AnimatedReorderContainer：动画重排序
    - DockablePanel：可停靠面板基类
    - ToolCallCard：工具调用卡片
    - IconBar：图标栏
    - 对话框系统：5 个对话框（快照/详情/短语/绑定/插件）
    - UI 日志桥接：LogPanelBridge + QtPanelLogHandler
    - 面板插件系统：BasePanelPlugin + PanelPluginLoader
    - PluginManagerPanel：插件管理面板
    - KnowledgeRulesCard：知识规则卡片
    - API 模式会话列表：APISessionList
    - MessageWindowService：消息窗口服务

12. **Rhino 集成** (全新章节)
    - rhino/rhino_listener.py：独立脚本监听器
    - rhino_plugin/AIBridge/：Python 插件版
    - RhinoBIM_Client/：C# BIM 面板

13. **实验性功能** (全新章节)
    - FastAPI 服务端 + PySide6 客户端

14. **提示词系统** (全新章节)
    - 5 层架构 + Plan/Build 模式 + 用户偏好

15. **配置文件详情** (全新章节)
    - API 模式/面板布局/工作区预设/对话存储

16. **前端库** (全新章节)
    - vis-network / Tom Select / 高亮工具函数

### 修正
- `app/ui/pages/modeling_page.py` → `app/ui/modeling_page.py`（在 ui 根目录，不在 pages/ 下）
- `app/ui/pages/settings_page.py` → `app/ui/settings_page.py`（在 ui 根目录，不在 pages/ 下）
- 移除已不存在的文件：code_pseudo_viewer.py、logic_viewer.py、forensic_editor.py、ops_panel.py
- 移除已不存在的 `app/ui/components/panels/skills_panel.py`（已迁移至 `plugins/panels/skills_panel/`）
- 新增 mobile/html_converter.py、mobile/utils/ui_helpers.py、构建脚本 PS1 版本

---

## 🆕 V11.0 更新内容 (2026-04-28)

### 新增功能
1. **手机客户端 (Mobile)**
   - 基于 Flet 框架的 Android 客户端
   - 支持浏览器模式和 API 模式收发消息
   - pygments 代码语法高亮 + 复制 + 远程修改
   - WebSocket 实时通信 + 心跳保活
   - 会话管理（新建/切换）
   - 登录信息记忆

### 架构优化
- 新增 `mobile/` 独立客户端目录，不影响现有代码
- 纯客户端，零服务端改动

---

## 🆕 V10.0 更新内容 (2026-03-07)

### 新增功能
1. **Skills 系统**
   - 可发现、可管理、可扩展的能力系统
   - 支持核心/扩展/外部三层架构
   - 自动生成系统提示词
   - UI 面板可视化管理

2. **面板管理系统**
   - 统一的可停靠面板框架
   - 工作区布局保存/加载
   - 6 个专业功能面板

3. **Qt6 兼容性修复**
   - 修复 QWebSocket 信号兼容性
   - 完善 RemoteWorker 信号定义

---

**文档版本**: V13.0 (2026-05-02)
**覆盖率**: 100% 核心文件 + 100% 工具文件 + 100% Mobile 客户端 + 100% Rhino 集成 + 100% 实验功能
**维护者**: AI Bridge Team