# 桌面远程客户端构建验证

`.github/workflows/desktop-build.yml` 使用标准 GitHub-hosted runner：Windows x64（`windows-latest`）、macOS ARM64（`macos-latest`）、macOS x64（`macos-15-intel`）。不选用 larger/付费标签；实际计费仍取决于 GitHub 账户和仓库政策。

入口为 `boot_remote.py`，不是启动 Python 子进程的 `start_client.py`。CI 在 CPython 3.12.10 的全新 venv 中安装完全固定版本的远程客户端依赖，并记录实际 wheel URL/哈希。构建、重建和库重新组合步骤见 [DESKTOP_REBUILD.md](DESKTOP_REBUILD.md)。

Windows 输出：`build/desktop/dist/AI-Bridge-Remote/AI-Bridge-Remote.exe`。macOS 输出：`build/desktop/dist/AI-Bridge-Remote.app`。需要保留整个目录或 app；它们分别对应 runner 架构，不是通用二进制。macOS 可有 PyInstaller 自动生成的 ad-hoc 签名，没有 Developer ID 签名或公证。

## 实际产物、许可与发行门槛

CI 只上传两个明确的审查 JSON：`desktop-inventory.json` 与 `recombination-test.json`，不上传执行文件、app、依赖二进制或原始安装报告。

- 构建前：仅从白名单依赖复制真实 LICENSE / COPYING / NOTICE /版权文本，结合固定版本的 Qt LGPLv3/GPLv3、PySide 说明和 CPython 文本。不会把名为 `licenses` 的 Python 包源码或完整 METADATA 当作许可材料
- 打包时：将生成的 `THIRD_PARTY_NOTICES` 放入 PyInstaller 数据项，发生在 macOS 签名之前。Windows 在 `_internal/THIRD_PARTY_NOTICES`；macOS 在 `Contents/Resources/THIRD_PARTY_NOTICES`
- 构建后：读取实际最终执行文件内 PYZ 成员、`base_library.zip` 成员和所有产物文件，结合 PyInstaller TOC 与已安装 distribution 文件表映射来源，保留哈希；将只存在于构建环境的包单列，绝不把它们全部当作应用依赖
- 验证：逐文件校验打包许可证与生成文本的 SHA-256。冻结 smoke 留下真正运行的 Python/PySide/Qt 版本。PE 文件版本、Mach-O load-command 版本能取得时单独记录；无法解析或归属的项目明确列为未解决
- 重新组合：修改 PySide LGPL Python 支持模块后重建、运行并读取标记，验证该部分可以重新组合；不把它写成所有原生 Qt 库的替换认证

`binary_distribution_approved` 始终为 false。Qt 内嵌第三方 codecs/平台/TLS 库、Qt 翻译、Windows 再分发条款、完整源码对应性与原生替换测试尚须核验。许可证清单和版本匹配不是完整合规保证；当前不需要也不进行商业许可证购买。

## Qt 原生范围约束

QtGui hook 在依赖分析前排除不用的 PDF 图像插件和虚拟键盘插件。最终文件名/路径继续禁止 VirtualKeyboard、Pdf、Qml、Quick native 组件。此范围检查不能代替完整依赖许可证审查。

## 隐私与功能范围

仓库静态数据仍只复制根目录 `LICENSE`；声明材料从固定白名单及有校验和的 `licenses/desktop` 生成，不递归复制仓库。不会复制 `assets/`、vendored `lib/`、文档、浏览器驱动/配置、数据库、用户配置、日志、凭证、插件或服务器/移动端工具。缺少装饰图标时保留文字按钮。

清单检查实际文件与 ZIP 成员中的敏感运行数据路径；构建来源仅导出相对路径或不带目录的未解决文件名，去除 runner / 用户绝对路径。该检查不是对任意二进制内容的完整秘密扫描，也不是生产隐私/安全审计。

这是经过登录/启动 smoke 的远程客户端，仍需要单独配置可访问的服务器，不代表完整桌面功能等价。本地 RAG、Docker 执行、浏览器自动化、源码热更新、本地 pytest 不打包。smoke 在新临时目录运行，不登录或联系服务器。

运行状态写入 Windows `%LOCALAPPDATA%/AI-Bridge` 或 macOS `~/Library/Application Support/AI-Bridge`，不写入安装目录。可用 `AI_BRIDGE_CLIENT_HOME` 指定独立可写目录；更新方式是重建并替换整个 bundle。
