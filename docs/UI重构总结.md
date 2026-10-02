# Settings Page UI 重构总结

> 历史阶段记录（2026-09-05 整理）：以下原文用于追溯当时的设计、实现与验证；当前能力见[项目状态](当前项目状态.md)，当前测试命令见[测试说明](../tests/README.md)。

## 重构日期
2026-05-04

## 重构目标
将 Settings Page 的 API 配置界面从旧的单一 Fallback Chain 设计升级为新的多 Chain 管理设计。

## 主要变更

### 1. Fallback Chains 管理区域重构

**旧设计：**
- 只有一个全局的 Fallback Chain
- 直接在 API 配置中管理 Profile 列表
- 无法创建多个命名的 Chain

**新设计：**
- 支持创建多个命名的 Fallback Chain
- Chain 列表显示所有已创建的 Chain
- 每个 Chain 可以独立管理其 Profile 列表
- 支持 Chain 的创建、重命名、删除操作
- 支持向 Chain 添加/移除 Profile，以及调整顺序

**新增 UI 组件：**
- `api_chain_list`: Chain 列表
- `api_chain_add_btn`: 新建 Chain 按钮
- `api_chain_rename_btn`: 重命名 Chain 按钮
- `api_chain_delete_btn`: 删除 Chain 按钮
- `api_chain_profile_combo`: Profile 候选下拉框
- `api_chain_profile_add_btn`: 添加 Profile 到 Chain 按钮
- `api_chain_profile_list`: Chain 中的 Profile 列表
- `api_chain_profile_up_btn`: 上移 Profile 按钮
- `api_chain_profile_down_btn`: 下移 Profile 按钮
- `api_chain_profile_remove_btn`: 移除 Profile 按钮

**新增方法：**
- `_on_chain_selected()`: Chain 选中时加载其 Profile 列表
- `_reload_chain_profile_candidates()`: 重新加载可添加的 Profile 候选列表
- `_reload_chain_list()`: 重新加载 Chain 列表
- `_create_chain()`: 创建新的 Fallback Chain
- `_rename_chain()`: 重命名 Fallback Chain
- `_delete_chain()`: 删除 Fallback Chain
- `_add_profile_to_chain()`: 向 Chain 添加 Profile
- `_remove_profile_from_chain()`: 从 Chain 移除 Profile
- `_move_chain_profile_up()`: 上移 Chain 中的 Profile
- `_move_chain_profile_down()`: 下移 Chain 中的 Profile

**删除的旧方法：**
- `save_fallback_chain_only()`
- `get_fallback_chain_from_ui()`
- `reload_fallback_candidates()`
- `reload_fallback_chain_list()`
- `add_fallback_profile()`
- `remove_fallback_profile()`
- `move_fallback_up()`
- `move_fallback_down()`

### 2. 守护进程配置重构

**旧设计：**
- 使用 `profile_ref` 引用单个 Profile 或使用独立配置
- 包含完整的 API 配置（provider, api_key, base_url, proxy_url）
- 包含 lite 和 core 两个模型的完整配置
- 回复建议包含 `auto_dismiss_seconds` 配置

**新设计：**
- Core 模型和 Lite 模型分别选择 Profile 或 Chain
- 每个模型配置包含类型（profile/chain）和引用（ref）
- 移除了独立的 API 配置字段
- 回复建议移除了 `auto_dismiss_seconds` 配置

**新增 UI 组件：**
- `daemon_core_type_profile_rb`: Core 模型选择 Profile 单选按钮
- `daemon_core_type_chain_rb`: Core 模型选择 Chain 单选按钮
- `daemon_core_combo`: Core 模型选择下拉框
- `daemon_core_summary_btn`: Core 模型查看摘要按钮
- `daemon_lite_type_profile_rb`: Lite 模型选择 Profile 单选按钮
- `daemon_lite_type_chain_rb`: Lite 模型选择 Chain 单选按钮
- `daemon_lite_combo`: Lite 模型选择下拉框
- `daemon_lite_summary_btn`: Lite 模型查看摘要按钮

**移除的 UI 组件：**
- `daemon_profile_combo`: 旧的 Profile 选择器
- `daemon_provider_combo`: Provider 选择器
- `daemon_api_key_edit`: API Key 输入框
- `daemon_base_url_edit`: Base URL 输入框
- `daemon_proxy_edit`: 代理 URL 输入框
- `daemon_lite_model_combo`: Lite 模型输入框
- `daemon_lite_temp_spin`: Lite 温度设置
- `daemon_lite_tokens_spin`: Lite 最大 Tokens 设置
- `daemon_core_model_combo`: Core 模型输入框
- `daemon_core_temp_spin`: Core 温度设置
- `daemon_core_tokens_spin`: Core 最大 Tokens 设置
- `daemon_suggest_dismiss_spin`: 自动消失时间设置

**新增方法：**
- `_populate_daemon_combo()`: 填充守护进程配置下拉框
- `_on_daemon_core_type_changed()`: 守护进程 Core 类型切换
- `_on_daemon_lite_type_changed()`: 守护进程 Lite 类型切换
- `_show_daemon_summary()`: 显示守护进程配置摘要

**删除的旧方法：**
- `_on_daemon_provider_changed()`
- `_on_daemon_profile_changed()`
- `_refresh_daemon_provider_ui()`
- `_toggle_daemon_key_visibility()`

### 3. API 模式对话配置（新增）

**新增功能：**
- 为 API 模式对话单独配置使用的模型
- 可以选择单个 Profile 或 Fallback Chain

**新增 UI 组件：**
- `api_mode_usage_group`: API 模式对话配置分组
- `api_mode_usage_type_profile_rb`: 选择 Profile 单选按钮
- `api_mode_usage_type_chain_rb`: 选择 Chain 单选按钮
- `api_mode_usage_combo`: 选择下拉框
- `api_mode_usage_summary_btn`: 查看摘要按钮

**新增方法：**
- `_build_api_mode_usage_section()`: 构建 API 模式对话配置区域
- `_populate_usage_combo()`: 填充 API 模式对话配置下拉框
- `_on_api_mode_usage_type_changed()`: API 模式对话类型切换
- `_show_api_mode_usage_summary()`: 显示 API 模式对话配置摘要

### 4. 配置结构变更

**旧的 daemon 配置结构：**
```json
{
  "daemon": {
    "enabled": true,
    "profile_ref": "default",
    "provider": "openai_compatible",
    "api_key": "...",
    "base_url": "...",
    "proxy_url": "...",
    "models": {
      "lite": {"model": "...", "max_output_tokens": 1024, "temperature": 0.3},
      "core": {"model": "...", "max_output_tokens": 2048, "temperature": 0.5}
    },
    "tasks": {
      "suggest": {
        "enabled": true,
        "max_suggestions": 3,
        "auto_dismiss_seconds": 30
      }
    }
  }
}
```

**新的 daemon 配置结构：**
```json
{
  "daemon": {
    "enabled": true,
    "core": {"type": "profile", "ref": "default"},
    "lite": {"type": "chain", "ref": "fast-chain"},
    "tasks": {
      "suggest": {
        "enabled": true,
        "max_suggestions": 3
      }
    }
  },
  "api_mode_usage": {
    "type": "profile",
    "ref": "default"
  }
}
```

**配置变更说明：**
- `daemon.profile_ref` → `daemon.core.ref` 和 `daemon.lite.ref`
- 移除了 `daemon.provider`, `daemon.api_key`, `daemon.base_url`, `daemon.proxy_url`
- 移除了 `daemon.models.lite` 和 `daemon.models.core` 的详细配置
- 移除了 `daemon.tasks.suggest.auto_dismiss_seconds`
- 新增了 `api_mode_usage` 顶层配置

## 影响范围

### 需要同步更新的模块

1. **DaemonManager** (`app/core/daemon/daemon_manager.py`)
   - 需要适配新的配置结构
   - 从 `core.type` 和 `core.ref` 解析配置
   - 从 `lite.type` 和 `lite.ref` 解析配置
   - 支持 Profile 和 Chain 两种引用方式

2. **API 模式对话处理** (待确认具体位置)
   - 需要读取 `api_mode_usage` 配置
   - 根据类型（profile/chain）加载对应配置

3. **配置迁移**
   - 需要提供从旧配置到新配置的迁移逻辑
   - 或在加载时兼容旧配置格式

### 不受影响的模块

- API Profile 管理（已有功能保持不变）
- 主 Agent 配置（不涉及）
- 浏览器模式配置（不涉及）

## 待办事项

- [ ] 更新 DaemonManager 以适配新配置结构
- [ ] 实现 API 模式对话的配置读取逻辑
- [ ] 添加配置迁移或兼容逻辑
- [ ] 测试所有新增的 UI 交互
- [ ] 更新相关文档

## 文件变更统计

- **修改文件**: `app/ui/settings_page.py`
- **原始行数**: 1519 行
- **当前行数**: 1493 行
- **新增方法**: 14 个
- **删除方法**: 12 个
- **新增 UI 组件**: 约 30 个
- **删除 UI 组件**: 约 15 个

## 测试建议

1. **Fallback Chains 管理测试**
   - 创建新 Chain
   - 重命名 Chain
   - 删除 Chain
   - 向 Chain 添加 Profile
   - 从 Chain 移除 Profile
   - 调整 Chain 中 Profile 的顺序

2. **守护进程配置测试**
   - 切换 Core 模型类型（Profile/Chain）
   - 切换 Lite 模型类型（Profile/Chain）
   - 选择不同的 Profile 或 Chain
   - 查看配置摘要

3. **API 模式对话配置测试**
   - 切换类型（Profile/Chain）
   - 选择不同的 Profile 或 Chain
   - 查看配置摘要

4. **配置保存测试**
   - 保存配置后验证配置文件内容
   - 重启应用后验证配置是否正确加载

## 注意事项

1. 旧配置格式的用户需要手动迁移或提供自动迁移逻辑
2. DaemonManager 需要同步更新才能正常工作
3. API 模式对话功能需要实现配置读取逻辑
4. 建议在测试环境充分测试后再部署到生产环境

---

## 实施进度

### ✅ 已完成

1. **Settings Page UI 重构** (2026-05-04)
   - Fallback Chains 管理升级
   - 守护进程配置重构
   - 新增 API 模式对话配置
   - 代码清理和优化

2. **DaemonConfig 适配** (已存在)
   - `daemon_config.py` 已经支持新配置结构
   - 支持从 `core.type` 和 `core.ref` 读取配置
   - 支持从 `lite.type` 和 `lite.ref` 读取配置
   - `_resolve_profile` 方法支持 Profile 和 Chain 两种引用

3. **API 模式对话配置读取** (2026-05-04)
   - 在 `APIModeConfigManager._default_config` 中添加 `api_mode_usage` 默认配置
   - 修改 `APIModeConfigManager.get_active_profile` 方法
   - 优先从 `api_mode_usage` 读取配置
   - 支持 Profile 和 Chain 两种引用方式
   - 引用无效时自动回退到 `active_profile`
   - 所有测试通过

### 🚧 待完成

1. **配置迁移逻辑**
   - 检测旧配置格式
   - 自动转换或提示用户手动迁移
   - 建议在 `ConfigManager` 或 `APIModeConfigManager.load` 中实现

2. **UI 功能测试**
   - Fallback Chains 管理测试
   - 守护进程配置测试
   - API 模式对话配置测试
   - 配置保存和加载测试

3. **文档更新**
   - 更新用户手册
   - 更新配置说明文档


### 🐛 紧急修复 (2026-05-04)

**问题**：运行时报错 `'SettingsPage' object has no attribute 'get_fallback_chain_from_ui'`

**原因**：Settings Page UI 重构时遗漏了旧代码清理

**修复**：
- 删除 `save_api_settings_to_current_session` 中对 `get_fallback_chain_from_ui()` 的调用
- 删除 `reload_api_settings` 中对 `reload_fallback_chain_list()` 的调用

**影响**：
- 修复后 Settings Page 可以正常保存和重载配置
- 不影响新架构的 Fallback Chains 管理功能


### 🐛 修复配置保存问题 (2026-05-04)

**问题**：保存配置后重载恢复默认配置

**根本原因**：
- `api_mode_usage` 应该保存到 `config/api_mode_config.json`
- 但被错误地保存到了 `config.json`
- 两个配置文件不同步

**修复**：
1. 初始化时从 `api_mode_config` 读取（而不是 `config`）
2. 保存时写入 `api_mode_config.json`（而不是 `config.json`）

**影响**：
- ✅ 配置能正确保存和加载
- ✅ 重载后配置不会丢失
- ✅ `api_mode_usage` 和其他 API 配置保持在同一个文件中

