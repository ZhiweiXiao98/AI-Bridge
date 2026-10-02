# 守护进程 Profile 共享功能 - 修改总结

> 历史阶段记录（2026-09-05 整理）：以下原文用于追溯当时的设计、实现与验证；当前能力见[项目状态](当前项目状态.md)，当前测试命令见[测试说明](../tests/README.md)。

## 修改的文件

### 1. app/ui/settings_page.py
- **新增**：Profile 选择器（第 411-429 行）
- **新增**：`_on_daemon_profile_changed` 方法（第 540-594 行）
- **修改**：`_install_safe_wheel_filter` 添加守护进程控件（第 58-87 行）
- **修改**：`save_settings` 添加 `profile_ref` 字段（第 1455 行）

### 2. app/core/daemon/daemon_config.py
- **修改**：`_load` 方法支持 Profile 引用（第 124-180 行）

## 核心功能

1. **Profile 选择器**：可选择 "🔧 独立配置" 或 "📋 {Profile名称}"
2. **自动填充**：切换 Profile 时自动填充所有配置字段
3. **防误触**：所有输入控件添加滚轮保护
4. **配置加载**：daemon_config 根据 profile_ref 决定配置来源

## 配置格式

```json
{
  "daemon": {
    "profile_ref": "欧亿",  // 或 "__independent__"
    "enabled": true,
    "provider": "openai_compatible",
    "api_key": "sk-xxx",
    ...
  }
}
```

## 使用方式

1. 打开设置页面 → 守护进程配置区
2. 在 "配置来源" 下拉框选择：
   - "🔧 独立配置"：使用专门的守护进程配置
   - "📋 {Profile名}"：共享已有的 API Profile
3. 保存配置

## 兼容性

- 旧配置自动识别为独立配置
- 两种模式可随时切换
- 不影响现有用户
