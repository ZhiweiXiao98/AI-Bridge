# Skills Panel Plugin

显示和管理所有可用的 Skills。

## 功能

- 📋 显示所有可用的 Skills
- 🔍 搜索和过滤 Skills
- ✨ 现代化卡片设计
- 🎨 主题适配
- 左键卡片快速启用 / 禁用 Skill
- 右键卡片查看 Skill 详情
- 在详情弹窗中可直接执行“🔄 重载”单个 Skill

## 安装

此插件已内置，无需额外安装。

## 使用

### 基本使用

1. 打开应用
2. 在菜单栏选择 "插件" > "Skills 管理面板"
3. 查看所有可用的 Skills

### 搜索 Skills

在搜索框中输入关键词，实时过滤 Skills 列表。

### 卡片交互

- **左键单击卡片**：快速启用 / 禁用对应 Skill
- **右键单击卡片**：打开 Skill 详情
- **详情弹窗中的“🔄 重载”按钮**：重新加载该 Skill 的运行时实例，适合在修改 `skill.py` 后快速让新代码生效

### 关于重载

- 单 Skill 重载适合开发调试阶段的快速刷新
- 如果遇到全局状态异常，仍可通过重启服务端做彻底刷新
- 修改 Skill 后，建议顺序为：写盘验证 → 编译验证 → 重载 Skill / 重启服务端 → 真实调用验证

## 配置

### 配置选项

```json
{
  "show_disabled": false,  // 是否显示禁用的 Skills
  "sort_by": "name"       // 默认排序方式
}
```

## 开发

### 文件结构

```
skills_panel/
├── plugin.json      # 插件元数据
├── plugin.py        # 插件入口
├── panel.py         # 面板实现
└── README.md        # 本文件
```

### 扩展功能

要添加新功能，修改 `panel.py` 中的 `SkillsPanelWidget` 类。

## 信号

- `skill_toggled(skill_id)` - Skill 被切换时发出
- `skill_detail_requested(skill_data)` - 请求显示 Skill 详情时发出

## 许可证

MIT
