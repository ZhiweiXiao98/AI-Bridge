# 📦 面板插件开发指南

## 快速开始

### 1. 创建插件目录

在 `plugins/panels/` 下创建你的插件目录。

### 2. 编写 plugin.json

定义插件元数据。

### 3. 实现插件类

继承 `BasePanelPlugin` 并实现 `create_panel()` 方法。

### 4. 实现面板类

继承 `DockablePanel` 并实现 `create_content()` 方法。

## 示例

查看 `example_panel/` 目录获取完整示例。

---

祝你开发愉快！🚀
