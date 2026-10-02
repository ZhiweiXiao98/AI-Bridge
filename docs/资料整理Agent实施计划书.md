# 资料整理与 HTML 导出

> 复核日期：2026-09-26。CLI 和桌面面板均提供文档生成入口；输出保存在本地 `docs/导出HTML/`。

## 使用方法

在仓库根目录运行：

```powershell
# 单文件转换
.\.venv\Scripts\python.exe -X utf8 tools/generate_docs_html.py docs/当前项目状态.md

# 批量转换 docs 顶层 Markdown，并生成索引
.\.venv\Scripts\python.exe -X utf8 tools/generate_docs_html.py docs/ --batch --index
```

`--output` 指定输出目录，`--open` 在完成后打开输出文件。批量入口扫描输入目录顶层的 `*.md`。输出与源 Markdown 独立，导出目录由 Git 忽略。

桌面的“资料整理”面板提供刷新、单篇生成、批量生成和内置浏览器预览。生成状态区分缺失、过期和已更新。

## 生成路径

| 入口 | 处理方式 |
| --- | --- |
| CLI / `DocOrganizerService.convert_file()` | 解析 Markdown 并通过 HTML 模板渲染；处理导出目录中的相对链接，跨盘时使用文件 URI |
| 后台 Subagent 整理 | `OrganizeTask` 支持显式转换和 polling；轮询按哈希扫描变更并调用转换服务 |
| 桌面面板 | 调用 `DocAnalyzerService`；存在可用 LLM router 时尝试生成结构化分析，分析不可用时使用 Markdown 解析器；后台线程负责生成和状态更新 |

面板通过 MainWindow 注入可用的 Subagent LLM router 和内置浏览器打开回调。面板生成路径直接写入渲染结果；CLI 的链接重定位处理尚需与面板路径统一。

## 模块职责

| 文件 | 职责 |
| --- | --- |
| `app/core/services/doc_organizer_service.py` | 单文件/批量转换、哈希扫描与 HTML 索引 |
| `app/core/services/doc_analyzer_service.py` | 可选 LLM 分析和结构化响应解析 |
| `app/core/services/doc_status_tracker.py` | 源文档与生成文件状态，持久化 `.doc_status.json` |
| `app/core/renderers/doc_html_renderer.py` | Markdown 结构解析、章节导航和展示模板 |
| `app/ui/components/panels/doc_organizer_panel.py` | 文档卡片与操作入口 |
| `app/ui/components/panels/doc_organizer_panel_logic.py` | 面板事件、后台生成和预览请求 |
| `tools/generate_docs_html.py` | CLI 参数与服务调用 |

## 编写适合导出的文档

第一行使用一级标题，随后给出简短说明；正文使用二级至四级标题组织。计划、状态和验收要求使用明确的段落、表格或清单。标题后的状态说明会出现在展示页中。

维护当前事实时先改源 Markdown，再生成 HTML。索引只收录其它 HTML 页面。生成状态可刷新检查，删除源文档后的状态条目会在扫描时清理。

## 待完善与验收

- [ ] 统一面板与 CLI 的相对链接和跨盘导出行为。
- [ ] 验证后台 polling 的生命周期、触发间隔和失败重试；按需扩展文件事件监听。
- [ ] 完整验证后台生成时的 UI 线程更新、取消和异常提示。
- [ ] 在可用 LLM router 与纯解析两种条件下核对内容完整性。
- [ ] 验证多种 Markdown 格式、图示及不同窗口尺寸的展示效果。

已有聚焦用例：`tests/test_doc_export_links.py`、`tests/test_doc_organizer_preview.py`。实际生成与验证记录见 [AI_JOURNAL.md](../AI_JOURNAL.md)。
