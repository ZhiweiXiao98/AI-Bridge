# 🎨 PySide6 沙盒环境配置指南

> **配置时间**: 2026-03-11 05:14:06
> **状态**: ✅ 已配置完成

---

## 📋 概述

为了支持 GUI 插件的开发和测试，我们在 Docker 沙盒环境中添加了 PySide6 支持。

### 主要变更

1. **Dockerfile 更新**
   - 添加了 Qt 相关的系统依赖库
   - 安装了 PySide6 >= 6.6.0
   - 支持无头模式（offscreen）运行

2. **测试脚本**
   - `test_pyside6.py` - PySide6 功能测试
   - `test_plugin_system.py` - 插件系统测试
   - `build_and_test_pyside6.sh` - 自动化构建测试脚本

---

## 🐳 Docker 镜像配置

### 系统依赖

添加的 Qt 相关库：

```dockerfile
RUN apt-get update && apt-get install -y --no-install-recommends \
    libxcb-xinerama0 \
    libxcb-icccm4 \
    libxcb-image0 \
    libxcb-keysyms1 \
    libxcb-randr0 \
    libxcb-render-util0 \
    libxcb-shape0 \
    libxkbcommon-x11-0 \
    libdbus-1-3 \
    libgl1 \
    libglib2.0-0 \
    libxcb-cursor0 \
    && rm -rf /var/lib/apt/lists/*
```

### Python 包

```dockerfile
RUN pip install PySide6>=6.6.0
```

---

## 🚀 快速开始

### 方法 1: 使用自动化脚本（推荐）

```bash
# 构建镜像并运行所有测试
./build_and_test_pyside6.sh
```

### 方法 2: 手动构建和测试

```bash
# 1. 构建 Docker 镜像
cd app/core/sandbox
docker build -t ai-bridge-sandbox:pyside6 -f Dockerfile ../../..
cd ../../..

# 2. 运行 PySide6 测试
docker run --rm \
    -v "$(pwd):/workspace" \
    -e QT_QPA_PLATFORM=offscreen \
    ai-bridge-sandbox:pyside6 \
    python test_pyside6.py

# 3. 运行插件系统测试
docker run --rm \
    -v "$(pwd):/workspace" \
    -e QT_QPA_PLATFORM=offscreen \
    ai-bridge-sandbox:pyside6 \
    python test_plugin_system.py
```

---

## 🧪 测试内容

### PySide6 功能测试 (`test_pyside6.py`)

测试项目：

1. ✅ 导入 PySide6 模块
2. ✅ 创建 QApplication
3. ✅ 创建 QMainWindow
4. ✅ 创建基本组件（QLabel, QPushButton, QTextEdit）
5. ✅ 测试信号和槽机制
6. ✅ 测试 QDockWidget
7. ✅ 测试样式表（QSS）
8. ✅ 测试插件系统组件（DockablePanel）

### 插件系统测试 (`test_plugin_system.py`)

测试项目：

1. ✅ 导入插件基类
2. ✅ 导入插件加载器
3. ✅ 创建插件加载器实例
4. ✅ 扫描插件目录
5. ✅ 加载插件
6. ✅ 验证插件配置
7. ✅ 测试配置管理

---

## 💡 使用场景

### 1. 开发 GUI 插件

```bash
# 进入容器交互式 shell
docker run -it --rm \
    -v "$(pwd):/workspace" \
    -e QT_QPA_PLATFORM=offscreen \
    ai-bridge-sandbox:pyside6 \
    bash

# 在容器内开发和测试
python your_plugin.py
```

### 2. 运行 GUI 测试

```bash
# 运行单个测试文件
docker run --rm \
    -v "$(pwd):/workspace" \
    -e QT_QPA_PLATFORM=offscreen \
    ai-bridge-sandbox:pyside6 \
    pytest tests/test_gui.py -v
```

### 3. 调试插件加载

```bash
# 运行插件系统测试
docker run --rm \
    -v "$(pwd):/workspace" \
    -e QT_QPA_PLATFORM=offscreen \
    ai-bridge-sandbox:pyside6 \
    python test_plugin_system.py
```

---

## 🔧 环境变量

### QT_QPA_PLATFORM

设置 Qt 平台插件：

- `offscreen` - 无头模式，不需要显示服务器（推荐用于测试）
- `xcb` - X11 模式，需要 X 服务器
- `wayland` - Wayland 模式

```bash
# 无头模式（推荐）
export QT_QPA_PLATFORM=offscreen

# X11 模式（需要 X 服务器）
export QT_QPA_PLATFORM=xcb
export DISPLAY=:0
```

### PYTHONPATH

确保项目根目录在 Python 路径中：

```bash
export PYTHONPATH=/workspace
```

---

## 📊 镜像信息

### 基础镜像

- **镜像**: `python:3.13-slim`
- **操作系统**: Debian Bookworm/Trixie
- **Python 版本**: 3.13

### 安装的包

**系统包**:
- Qt 相关库（13 个）
- 构建工具
- Git

**Python 包**:
- PySide6 >= 6.6.0
- ChromaDB >= 0.5.0
- FastEmbed >= 0.5.0
- LangChain >= 0.4.0
- 其他工具包

### 镜像大小

预计大小：约 1.5-2 GB（包含所有依赖）

---

## ⚠️ 注意事项

### 1. 无头模式限制

在 `offscreen` 模式下：

- ✅ 可以创建和操作 GUI 组件
- ✅ 可以测试信号和槽
- ✅ 可以测试布局和样式
- ❌ 无法显示窗口
- ❌ 无法进行可视化交互
- ❌ 无法截图

### 2. 性能考虑

- 首次构建镜像需要下载大量依赖，可能需要 10-20 分钟
- 后续构建会使用缓存，速度较快
- 运行测试通常在几秒内完成

### 3. 兼容性

- PySide6 需要 Python 3.7+
- 某些 Qt 功能可能在无头模式下不可用
- 建议在实际环境中进行最终测试

---

## 🐛 故障排除

### 问题 1: 导入 PySide6 失败

**错误信息**:
```
ModuleNotFoundError: No module named 'PySide6'
```

**解决方案**:
```bash
# 重新构建镜像
docker build -t ai-bridge-sandbox:pyside6 -f app/core/sandbox/Dockerfile .
```

### 问题 2: Qt 平台插件错误

**错误信息**:
```
qt.qpa.plugin: Could not find the Qt platform plugin
```

**解决方案**:
```bash
# 设置环境变量
export QT_QPA_PLATFORM=offscreen
```

### 问题 3: 缺少系统库

**错误信息**:
```
ImportError: libxcb-xxx.so.0: cannot open shared object file
```

**解决方案**:
```bash
# 检查 Dockerfile 中是否包含所有必需的库
# 重新构建镜像
```

---

## 📚 相关文档

- [PySide6 官方文档](https://doc.qt.io/qtforpython/)
- [Qt for Python 教程](https://doc.qt.io/qtforpython/tutorials/index.html)
- [插件系统开发指南](plugins/panels/README.md)
- [Docker 测试环境指南](app/core/sandbox/README.md)

---

## 🔄 更新日志

### 2024-01-XX

- ✅ 添加 PySide6 支持
- ✅ 添加 Qt 系统依赖
- ✅ 创建 PySide6 测试脚本
- ✅ 创建自动化构建脚本
- ✅ 更新文档

---

**文档生成时间**: 2026-03-11 05:14:06
**维护者**: AI Bridge Team
