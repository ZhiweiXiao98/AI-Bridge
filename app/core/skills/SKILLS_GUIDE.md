# Skills 开发指南

## 📖 什么是 Skill？

Skill 是一个知识包，用于教 AI 在特定场景下按照你的方式做事。

**核心理念**：
- Skill = 知识（SKILL.md）+ 可选工具（skill.py）
- AI 读取 Skill 后，学会"如何做某事"
- 可复用、可共享、可扩展

## 📁 Skill 结构

每个 Skill 是一个文件夹，包含：

skill_name/
├── SKILL.md          # 必需：知识和指引
├── skill.py          # 可选：可执行代码
├── examples/         # 可选：示例文件
├── references/       # 可选：参考文档
└── templates/        # 可选：模板文件

## 📝 SKILL.md 格式

### 元数据区（YAML Front Matter）

必须在文件开头使用 YAML Front Matter 定义元数据：

---
name: skill_name              # 唯一标识（小写字母+下划线）
display_name: Skill 显示名称   # 用户看到的名称
category: debugging           # 分类：file/code/network/system/debugging
description: 简短描述功能      # 一句话描述
scenario: 适用场景描述         # 什么时候使用这个 Skill
version: 1.0.0               # 版本号
author: Your Name            # 作者
dangerous: false             # 是否危险操作
enabled: true                # 是否启用
---

### 内容区

元数据后面是 Markdown 格式的知识内容：

1. 技能描述
2. 工作流程
3. 常见模式
4. 示例
5. 注意事项

## 🔧 skill.py 格式（可选）

如果 Skill 需要执行代码，创建 skill.py：

from app.core.skills.base import BaseSkill, SkillMetadata, SkillParameter

class MySkill(BaseSkill):
    @property
    def metadata(self):
        return SkillMetadata(
            name="my_skill",
            display_name="我的技能",
            category="system",
            description="做某事",
            scenario="需要做某事时",
            version="1.0.0",
            author="Me",
            parameters=[
                SkillParameter(
                    name="param1",
                    type="str",
                    required=True,
                    description="参数说明"
                )
            ],
            examples=["my_skill(param1='value')"]
        )
    
    def execute(self, param1: str):
        # 实际实现
        return f"执行结果: {param1}"

# 必须导出
__skill__ = MySkill

## 📋 完整示例

### 示例 1：纯知识 Skill（无代码）

文件：extended/code_review/SKILL.md

---
name: code_review
display_name: 代码审查专家
category: code
description: 系统化审查代码质量
scenario: 需要审查代码时
version: 1.0.0
author: System
dangerous: false
---

# 代码审查专家

## 审查清单

### 1. 代码风格
- 命名是否清晰
- 缩进是否一致
- 注释是否充分

### 2. 逻辑正确性
- 边界条件处理
- 错误处理
- 性能考虑

### 3. 安全性
- 输入验证
- SQL 注入防护
- XSS 防护

## 审查流程

1. 通读代码，理解意图
2. 逐项检查清单
3. 标记问题点
4. 提出改进建议

## 示例

见 examples/good_vs_bad.md

### 示例 2：带代码的 Skill

文件：core/file_operations/SKILL.md

---
name: file_operations
display_name: 文件操作
category: file
description: 读取、写入、列出文件
scenario: 需要操作文件系统时
version: 1.0.0
author: System
dangerous: false
---

# 文件操作

## 可用操作

### read_file
读取文件内容

参数：
- path: 文件路径
- max_lines: 最大行数（默认 1000）

### list_files
列出目录文件

参数：
- directory: 目录路径（默认当前目录）

## 使用原则

1. 读取前检查文件是否存在
2. 大文件注意截断
3. 处理编码错误

文件：core/file_operations/skill.py

from app.core.skills.base import BaseSkill, SkillMetadata, SkillParameter
import os

class FileOperationsSkill(BaseSkill):
    @property
    def metadata(self):
        return SkillMetadata(
            name="file_operations",
            display_name="文件操作",
            category="file",
            description="读取、写入、列出文件",
            scenario="需要操作文件系统时",
            version="1.0.0",
            author="System",
            parameters=[
                SkillParameter(
                    name="operation",
                    type="str",
                    required=True,
                    description="操作类型：read/list"
                ),
                SkillParameter(
                    name="path",
                    type="str",
                    required=True,
                    description="文件或目录路径"
                )
            ]
        )
    
    def execute(self, operation: str, path: str, **kwargs):
        if operation == "read":
            return self._read_file(path, kwargs.get('max_lines', 1000))
        elif operation == "list":
            return self._list_files(path)
        else:
            raise ValueError(f"未知操作: {operation}")
    
    def _read_file(self, path, max_lines):
        # 实现读取逻辑
        pass
    
    def _list_files(self, path):
        # 实现列出逻辑
        pass

__skill__ = FileOperationsSkill

## 🎯 最佳实践

### 1. SKILL.md 编写
- 清晰的结构
- 具体的步骤
- 丰富的示例
- 明确的注意事项

### 2. skill.py 编写
- 继承 BaseSkill
- 实现 metadata 属性
- 实现 execute 方法
- 导出 __skill__

### 3. 测试
- 验证 SKILL.md 格式
- 测试 skill.py 执行
- 检查参数验证

### 4. 文档
- 提供使用示例
- 说明适用场景
- 标注危险操作

## 🚀 快速开始

1. 复制模板文件夹
2. 修改 SKILL.md
3. 如需代码，创建 skill.py
4. 测试验证
5. 导入到系统

## 📌 注意事项

- name 必须唯一
- 元数据必须完整
- 危险操作标记 dangerous: true
- skill.py 必须导出 __skill__
- 遵循最小权限原则


---

## 🔗 项目依赖说明

### 可用的依赖注入

当你创建 skill.py 时，可以在 __init__ 中接收以下依赖：

#### 1. file_service
文件服务，提供安全的文件访问。

**可用方法**：
- `is_safe_path(path)` - 检查路径是否安全
- 其他文件相关服务

**使用示例**：
def __init__(self, file_service=None):
    self.file_service = file_service

def execute(self, path):
    if self.file_service and not self.file_service.is_safe_path(path):
        return "Access denied"

#### 2. docker
Docker 管理器，提供沙盒执行环境。

**可用方法**：
- `execute_code(code, timeout)` - 执行 Python 代码
- `available` - 检查 Docker 是否可用

**使用示例**：
def __init__(self, docker=None):
    self.docker = docker

def execute(self, code):
    if not self.docker or not self.docker.available:
        return "Docker 不可用"
    exit_code, output = self.docker.execute_code(code)
    return output

#### 3. knowledge_engine
知识引擎，提供代码库搜索。

**可用方法**：
- `search_context(query, top_k)` - 语义搜索

**使用示例**：
def __init__(self, knowledge_engine=None):
    self.knowledge_engine = knowledge_engine

def execute(self, query):
    return self.knowledge_engine.search_context(query)

### 依赖注入流程

依赖在 AgentManager.__init__ 中注入：

# 在 AgentManager.__init__ 中
file_skill = self.skills_manager.get_skill_instance('file_operations')
if file_skill:
    file_skill.file_service = self.file_service

如果你创建新 Skill 需要其他依赖，需要在 AgentManager 中添加注入代码。

### 当前内置依赖注入说明（2026-03-31）

- `file_operations`：会注入 `file_service`，并已支持注入 `knowledge_engine`，用于文件变更后的知识库同步等能力。
- `code_execution`：会注入 `docker_manager` / `docker`。
- `knowledge_search`：会注入 `knowledge_engine`。

### Skill 热重载说明

当前 `SkillsManager` 已支持单 Skill 热重载：
- `SkillsManager.reload_skill(name)`
- `AgentManager.reload_skill(name)`
- `WorkerThread.reload_skill(...)`
- `RemoteWorker.skills_reload(...)`

适用场景：
- 只修改了某个 `skill.py`
- 希望不重启整条服务链路就刷新该 Skill 的运行时实例

重要注意：
- **修改磁盘上的 `skill.py` 后，已有 Skill 实例不会自动刷新。**
- 开发时应在“写盘验证 + 编译验证”后，再做一次：
  1. `reload_skill()` 单 Skill 重载，或
  2. 直接重启服务端
- 最终必须再做一次真实调用验证，不要只看源码和编译结果。

### file_operations 的开发工作流补充

`file_operations` 已新增 `read_lines(path, start_line, end_line)`，并返回带行号的局部内容。

建议工作流：
1. 先用 `read_lines` 精确查看大文件局部上下文
2. 再使用 `replace_lines` / `insert_at_line` 等行级编辑
3. 避免直接拿 `read_file` 的 preview/truncated 内容做精确锚点替换

---

## 🧪 如何测试 Skill

### 1. 单元测试

创建测试文件 `tests/test_my_skill.py`：

import pytest
from app.core.skills.core.my_skill.skill import MySkill

def test_my_skill_metadata():
    skill = MySkill()
    meta = skill.metadata
    assert meta.name == "my_skill"
    assert meta.category in ["file", "code", "network", "system"]

def test_my_skill_execute():
    skill = MySkill()
    result = skill.execute(param1="test")
    assert result is not None

def test_my_skill_validation():
    skill = MySkill()
    is_valid, error = skill.validate(param1="test")
    assert is_valid is True

### 2. 集成测试

重启应用，观察启动日志：

📚 [Skills] 已加载: X 核心 + Y 扩展 + Z 外部

如果看到你的 Skill，说明加载成功。

### 3. 功能测试

在 AI 对话中测试：
- 触发 Skill 的使用场景
- 观察 AI 是否正确调用
- 检查执行结果

### 4. 手动测试

创建测试脚本：

# EXEC
from app.core.skills import SkillsManager

manager = SkillsManager()
manager.scan_all_skills()

skill = manager.get_skill_instance('my_skill')
if skill:
    result = skill.execute(param1="test")
    print(result)

---

## 🔌 如何集成到系统

### 步骤 1: 创建 Skill 文件夹

在 `app/core/skills/core/` 或 `app/core/skills/extended/` 创建文件夹。

### 步骤 2: 编写 SKILL.md

按照格式编写元数据和知识内容。

### 步骤 3: 编写 skill.py（可选）

如果需要执行代码，创建 skill.py 并导出 __skill__。

### 步骤 4: 注入依赖（如果需要）

在 `app/core/agent_manager.py` 的 __init__ 中添加：

my_skill = self.skills_manager.get_skill_instance('my_skill')
if my_skill:
    my_skill.some_dependency = self.some_service

### 步骤 5: 重启测试

重启应用，观察 Skill 是否正确加载。

---

## ❓ 常见问题

### Q1: Skill 没有被加载？
**检查**：
- SKILL.md 是否在正确的位置
- YAML Front Matter 格式是否正确
- 必需字段是否完整

### Q2: skill.py 执行失败？
**检查**：
- 是否正确导出 __skill__
- 是否继承 BaseSkill
- 依赖是否正确注入

### Q3: 系统提示词太长？
**解决**：
- 将 Skill 移到 extended/（未来按需加载）
- 精简 SKILL.md 内容
- 使用引用而非完整内容

### Q4: 如何禁用某个 Skill？
**方法**：
- 在 SKILL.md 中设置 `enabled: false`
- 或者将文件夹移出 skills/ 目录

### Q5: 如何更新 Skill？
**步骤**：
1. 修改 SKILL.md 或 skill.py
2. 更新 version 版本号
3. 重启应用
4. 系统会自动重新加载

---

## 🛠️ 维护指南

### 日常维护

#### 添加新 Skill
1. 确定 Skill 的分类（core/extended）
2. 创建文件夹和 SKILL.md
3. 如需代码，创建 skill.py
4. 测试验证
5. 提交代码

#### 更新现有 Skill
1. 修改 SKILL.md 或 skill.py
2. 更新版本号
3. 记录变更（在 SKILL.md 底部）
4. 测试验证
5. 提交代码

#### 删除 Skill
1. 移除文件夹
2. 检查是否有其他代码依赖
3. 更新文档
4. 重启测试

### 版本管理

在 SKILL.md 底部添加变更记录：

## 变更历史

### v1.1.0 (2024-01-XX)
- 添加了新参数 xxx
- 优化了性能
- 修复了 bug

### v1.0.0 (2024-01-XX)
- 初始版本

### 代码审查

新增或修改 Skill 时检查：
- [ ] SKILL.md 格式正确
- [ ] 元数据完整
- [ ] 知识内容清晰
- [ ] 示例充分
- [ ] skill.py 正确实现（如果有）
- [ ] 测试通过
- [ ] 文档更新

### 性能监控

定期检查：
- 系统提示词长度（建议 < 5000 tokens）
- Skills 加载时间
- Skills 执行性能

---

## 🎓 给新 AI 的说明

如果你是接手维护 Skills 系统的新 AI，请：

1. **先阅读这些文档**：
   - `docs/SKILLS_SYSTEM_DESIGN.md` - 了解整体设计
   - `docs/SKILLS_SYSTEM_IMPLEMENTATION.md` - 了解实施状态
   - `app/core/skills/SKILLS_GUIDE.md` - 本文档

2. **理解项目上下文**：
   - 这是一个 AI 代理系统
   - 使用 Docker 沙盒执行代码
   - 有文件服务和知识引擎
   - 主要语言是 Python

3. **熟悉现有 Skills**：
   - 查看 `app/core/skills/core/` 下的 3 个核心 Skills
   - 理解它们的实现方式
   - 作为创建新 Skill 的参考

4. **测试环境**：
   - 使用 # EXEC 标记执行测试代码
   - 验证 Skills 是否正确加载
   - 测试 Skills 的执行结果

5. **遵循规范**：
   - 严格按照 SKILL.md 格式
   - skill.py 必须导出 __skill__
   - 测试后再提交

6. **寻求帮助**：
   - 如果不确定，先问用户
   - 参考现有 Skills 的实现
   - 查看错误日志定位问题

---

## 📚 参考资源

### 项目文档
- `docs/SKILLS_SYSTEM_DESIGN.md` - 系统设计
- `docs/SKILLS_SYSTEM_IMPLEMENTATION.md` - 实施总结
- `docs/AGENT_TOOL_MASTERY.md` - AI 工具使用教科书

### 代码文件
- `app/core/skills/base.py` - 基类定义
- `app/core/skills/loader.py` - 加载器
- `app/core/skills/manager.py` - 管理器
- `app/core/agent_manager.py` - 集成点

### 示例 Skills
- `app/core/skills/core/file_operations/` - 文件操作示例
- `app/core/skills/core/code_execution/` - 代码执行示例
- `app/core/skills/core/knowledge_search/` - 知识检索示例

---

## 🎯 维护目标

作为 Skills 系统的维护者，你的目标是：

1. **保持系统稳定**：不破坏现有功能
2. **持续改进**：根据反馈优化 Skills
3. **扩展能力**：添加新的有用 Skills
4. **保持文档**：及时更新文档
5. **响应问题**：快速修复 bug

记住：Skills 系统是 AI 的"知识库"，维护好它就是提升 AI 的能力！
