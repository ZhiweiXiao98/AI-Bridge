# Skills 系统设计与实施计划

## 📅 创建日期
2026-03-06

## 🎯 目标
建立一个可发现、可管理、可扩展的 Skills 系统，让 AI 能够：
1. 清楚知道自己有哪些能力
2. 根据任务自动调用相关知识
3. 支持导入外部 Skills 扩展能力

## 🏗️ 采用方案：分层架构 + 混合模式

### 核心设计理念
- Skill = 知识包（Markdown）+ 可选工具（Python）
- 分层管理：核心/扩展/外部
- 核心始终加载，扩展按需加载
- 外部 Skills 独立管理

### 目录结构
skills/
├── core/                      # 核心 Skills（始终加载）
│   ├── file_operations/
│   │   ├── SKILL.md          # 知识：如何操作文件
│   │   └── skill.py          # 工具：read_file, write_file
│   ├── code_execution/
│   │   ├── SKILL.md
│   │   └── skill.py
│   └── knowledge_search/
│       ├── SKILL.md
│       └── skill.py
│
├── extended/                  # 扩展 Skills（按需加载）
│   ├── debug_python/
│   │   ├── SKILL.md          # 纯知识，无代码
│   │   ├── examples/
│   │   └── references/
│   ├── code_review/
│   │   ├── SKILL.md
│   │   └── checklist.md
│   └── write_tests/
│       ├── SKILL.md
│       └── templates/
│
└── external/                  # 外部导入（用户自定义）
    ├── .gitignore
    └── README.md

## 📝 SKILL.md 标准格式

每个 SKILL.md 必须包含以下部分：

### 元数据区（YAML Front Matter）
---
name: debug_python
category: debugging
version: 1.0.0
author: System
scenario: Python 代码报错、性能问题、逻辑错误
dangerous: false
---

### 内容区
1. 技能描述
2. 工作流程
3. 常见模式
4. 示例
5. 注意事项

## 🔧 核心组件

### 1. SkillsManager
负责：
- 扫描 skills/ 目录
- 解析 SKILL.md 文件
- 管理 Skills 生命周期
- 生成系统提示词

### 2. SkillLoader
负责：
- 解析 YAML 元数据
- 验证 Skill 格式
- 加载 skill.py（如果存在）
- 安全检查

### 3. SkillExecutor
负责：
- 执行 skill.py 中的代码
- 权限验证
- 日志记录
- 错误处理

### 4. SkillsPanel (UI)
负责：
- 展示所有 Skills
- 查看详细信息
- 启用/禁用控制
- 导入外部 Skills

## 📊 实施计划

### 阶段 1：基础框架（第1天）
- [ ] 创建目录结构
- [ ] 实现 SkillsManager 基础类
- [ ] 实现 SKILL.md 解析器
- [ ] 编写 Skills 开发指南

### 阶段 2：迁移现有能力（第2天）
- [ ] 创建 core/file_operations/
  - [ ] 迁移 tool_read_file
  - [ ] 迁移 tool_list_files
  - [ ] 编写 SKILL.md
- [ ] 创建 core/code_execution/
  - [ ] 迁移 docker.execute_code
  - [ ] 编写 SKILL.md
- [ ] 创建 core/knowledge_search/
  - [ ] 迁移 tool_search_knowledge
  - [ ] 编写 SKILL.md

### 阶段 3：系统提示词集成（第3天）
- [ ] 实现系统提示词生成
- [ ] 在 README.md 中引用
- [ ] 测试 AI 能否正确使用 Skills

### 阶段 4：UI 面板（第4天）
- [ ] 创建 SkillsPanel 页面
- [ ] 实现 Skills 列表展示
- [ ] 实现详情查看
- [ ] 实现启用/禁用功能

### 阶段 5：外部导入（第5天）
- [ ] 实现文件选择对话框
- [ ] 实现安全验证
- [ ] 实现导入流程
- [ ] 编写外部 Skill 示例

### 阶段 6：测试与文档（第6天）
- [ ] 编写单元测试
- [ ] 编写集成测试
- [ ] 完善开发文档
- [ ] 创建示例 Skills

## 🔒 安全机制

### 外部 Skills 验证
1. 格式验证：检查 SKILL.md 是否符合标准
2. 代码扫描：如果有 skill.py，扫描危险操作
3. 沙盒测试：在隔离环境中测试执行
4. 用户确认：显示 Skill 详情，用户确认导入

### 危险操作标记
- dangerous: true 的 Skills 需要用户确认
- 执行前显示警告
- 记录执行日志

## 📈 预期效果

### 对 AI
- 清楚知道自己有哪些能力
- 能够准确选择合适的 Skill
- 按照 Skill 指引高质量完成任务

### 对用户
- UI 面板清晰展示所有 Skills
- 可以管理 Skills 的启用状态
- 可以导入社区 Skills
- 可以自己编写 Skills

### 对项目
- 能力模块化，易于维护
- 标准化格式，易于扩展
- 社区友好，易于分享

## 🎯 成功标准

1. AI 能够自动识别并使用 Skills
2. 用户能够在 UI 中看到所有 Skills
3. 可以成功导入外部 Skill 文件
4. 系统提示词自动更新
5. 所有测试通过

## 📌 技术要点

### 1. YAML 解析
使用 PyYAML 解析元数据

### 2. 动态导入
使用 importlib 动态加载 skill.py

### 3. 安全验证
使用 AST 扫描危险操作

### 4. 系统提示词生成
自动拼接所有 Skills 的内容

### 5. UI 实时更新
使用 Signal 通知 UI 刷新

## 🚀 立即开始

从阶段 1 开始实施。
