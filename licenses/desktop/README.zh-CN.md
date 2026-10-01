# 第三方许可与源码说明（构建审查材料）

AI-Bridge 自有代码采用项目根目录 LICENSE 中的 MIT 许可证。此目录中的第三方作品保留各自许可证，不能用项目 MIT 许可证替代。

本程序使用 Qt、PySide6 与 Shiboken6。对已确认支持开源路线的相关组件，本项目选择 LGPLv3 路线；完整 LGPLv3 与其引用的 GPLv3 正文随此目录提供。PySide6 官方相应版本 README 同时保留其许可说明。Qt、PySide6、Shiboken6 的版权归 The Qt Company Ltd. 及相应源码列明的其他贡献者所有。原始源码头和第三方组件声明应随对应源码保留。

允许依许可证修改这些库，并为调试修改而进行逆向工程。重建方法见项目 docs/DESKTOP_REBUILD.md。重新组合不需要项目的私有签名密钥；macOS 重新构建使用临时签名（ad-hoc），不代表 Apple 公证。未来发行渠道或条款不得取消相关库许可证所赋予的权利。

## 内容与边界

- `python-packages.json`：隔离构建环境中候选软件包的版本、许可文本哈希、可取得的 wheel 来源以及对应版本源码入口
- `python/`：从本次安装的软件包中复制的实际许可证、版权及 NOTICE 文本。可能包含构建工具的补充声明；不能据此断定该工具随应用分发
- `sources.json`、`python-sources.json`：明确版本的上游源码地址、公布的 SHA-256 和核验范围
- `CPython-3.12.10-LICENSE.txt`：目标 CI 所用 CPython 3.12.10 的许可证及其中第三方说明；不是其他 Python 版本的核验证据
- CI 的 `desktop-inventory.json`：最终执行文件内 PYZ 成员、实际文件哈希及其 TOC/安装记录来源。以此区分实际携带代码和仅在环境中安装的工具

certifi 的 MPL-2.0 许可文本位于 `python/certifi-<版本>/`。其相应版本源码地址与校验和列于 `python-sources.json`；MPL 对该覆盖部分的源码权利不会把 AI-Bridge 的所有自有代码自动改为 MPL。

PyInstaller 的 COPYING.txt 包含其许可证与 bootloader exception。该例外不取消其他依赖的义务。

## 尚未批准二进制公开发行

这些材料是技术核验输入，不是完整许可合规或可重复构建认证。仍需核对原生库内嵌的第三方 codecs、平台库、OpenSSL、Qt 翻译等版权/源码，核对 Windows 再分发权限，完成各平台修改库重新组合与最终归档隐私检查。源档案版本相同不等于它与具体 wheel 的编译选项/补丁完全对应。

这里提供已核验的源码入口与公开校验和，不代表已经下载、保留或独立编译全部源码，也不构成代用户作出的长期书面源码提供承诺。未来发布者仍须保证适用源码持续可取得，并在下载处给出清晰方向。当前工作流只上传审查 JSON，二进制上传没有启用开关。
