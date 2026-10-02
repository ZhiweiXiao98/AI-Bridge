# 守护进程 Profile 共享功能 - 实施完成

> 历史阶段记录（2026-09-05 整理）：以下原文用于追溯当时的设计、实现与验证；当前能力见[项目状态](当前项目状态.md)，当前测试命令见[测试说明](../tests/README.md)。

## 功能概述

守护进程现在支持两种配置方式：
1. **共享 API Profile**：选择已有的 API 配置，无需重复输入
2. **独立配置**：使用专门的守护进程配置，与 API 模式独立

## 用户体验

### 使用场景 1：共享已有 Profile
1. 在 API 配置中心创建 Profile（如 "欧亿"）
2. 在守护进程配置区，选择 "📋 欧亿"
3. 所有配置自动填充（API Key、Base URL、模型等）
4. 保存后，守护进程使用该 Profile 的配置

### 使用场景 2：独立配置
1. 在守护进程配置区，选择 "🔧 独立配置"
2. 手动填写守护进程专用的配置
3. 保存后，守护进程使用独立配置

### 防误触保护
- 所有下拉框和数字输入框都有防滚轮保护
- 必须先点击获得焦点，才能用滚轮修改
- 避免滚动页面时误改配置

## 技术实现细节

### 1. UI 层改动 (app/ui/settings_page.py)

#### 1.1 Profile 选择器（第 411-429 行）
```python
self.daemon_profile_combo = QComboBox()
self.daemon_profile_combo.addItem("🔧 独立配置", "__independent__")
for profile_key in self.api_mode_config.get("profiles", {}).keys():
    profile_name = self.api_mode_config["profiles"][profile_key].get("name", profile_key)
    self.daemon_profile_combo.addItem(f"📋 {profile_name}", profile_key)
```

#### 1.2 防误触保护（第 58-87 行）
在 `_install_safe_wheel_filter` 中添加守护进程控件：
- daemon_profile_combo
- daemon_provider_combo
- daemon_lite_model_combo
- daemon_core_model_combo
- daemon_lite_temp_spin
- daemon_lite_tokens_spin
- daemon_core_temp_spin
- daemon_core_tokens_spin
- daemon_suggest_max_spin
- daemon_suggest_dismiss_spin

#### 1.3 Profile 切换处理（第 540-594 行）
新增 `_on_daemon_profile_changed` 方法：
- 检测 profile_ref
- 如果是 __independent__：从 config.json 加载独立配置
- 如果是 Profile key：从 api_mode_config 加载 Profile 配置
- 自动填充所有 UI 控件

#### 1.4 保存逻辑（第 1455 行）
添加 profile_ref 字段到 daemon 配置中

### 2. 配置层改动 (app/core/daemon/daemon_config.py)

#### 2.1 修改 _load 方法（第 124-180 行）

**核心逻辑**：
1. 读取 config.json 中的 daemon 配置
2. 检查 profile_ref 字段
3. 如果 profile_ref != "__independent__"：
   - 从 APIModeConfigManager 加载对应 Profile
   - 提取 provider、api_key、base_url、proxy_url、model、temperature、max_tokens
   - 构建 lite 和 core 两个 ModelTierConfig
   - lite: max_tokens 限制为 min(profile_max_tokens, 2048)
   - core: max_tokens 限制为 min(profile_max_tokens, 4096)
4. 如果 profile_ref == "__independent__" 或加载失败：
   - 使用 daemon 配置中的独立字段
   - 保持原有逻辑不变

**异常处理**：
- Profile 加载失败时，自动回退到独立配置
- 记录警告日志，不中断程序运行

## 配置文件格式

### config.json 示例

```json
{
  "daemon": {
    "enabled": true,
    "profile_ref": "欧亿",
    "provider": "openai_compatible",
    "api_key": "sk-xxx",
    "base_url": "https://api.openai.com/v1",
    "proxy_url": "",
    "models": {
      "lite": {
        "model": "gpt-4o-mini",
        "max_output_tokens": 1024,
        "temperature": 0.3
      },
      "core": {
        "model": "gpt-4o",
        "max_output_tokens": 2048,
        "temperature": 0.5
      }
    },
    "tasks": {
      "suggest": {
        "enabled": true,
        "max_suggestions": 3,
        "auto_dismiss_seconds": 8
      }
    }
  }
}
```

**说明**：
- `profile_ref` 为 "欧亿" 时，使用 API Profile "欧亿" 的配置
- `profile_ref` 为 "__independent__" 时，使用下面的独立配置字段
- 所有字段都保留，方便在两种模式间切换

## 测试建议

### 场景 1：共享 Profile
1. 创建新 Profile "测试Profile"
2. 守护进程选择该 Profile
3. 验证字段自动填充
4. 保存并重启验证

### 场景 2：独立配置
1. 选择 "🔧 独立配置"
2. 手动填写配置
3. 保存并重启验证
4. 切换模式后验证数据不丢失

### 场景 3：防误触
1. 不点击输入框，滚动鼠标
2. 验证值不变
3. 点击后滚动，验证可改变

## 兼容性

- 旧配置自动识别为独立配置
- 默认 profile_ref 为 "__independent__"
- 两种模式可随时切换

## 已知限制

1. Profile 删除后自动回退到独立配置
2. 修改 Profile 需重新加载守护进程
3. 使用 Profile 时 lite/core 共享同一模型
