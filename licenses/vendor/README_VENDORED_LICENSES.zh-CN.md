# AI-Bridge 内置前端资源归属补充

核验日期：2026-10-01（UTC）

本目录是**仅增加文本的归属补丁**。它没有修改任何 JS/CSS，没有改写项目主许可证，也没有向仓库或公共服务提交任何内容。只核验下列五个继承资源，不代表整个应用、Python 依赖、安装包或运行时的完整许可证审计。

## 已核验的资源

- `lib/tom-select/tom-select.complete.min.js` 与 `lib/tom-select/tom-select.css`：逐字节匹配 npm 官方 `tom-select@2.0.0-rc.4`；保留该版本 Apache-2.0 许可证原文。
- `lib/vis-9.1.2/vis-network.css`：逐字节匹配 npm 官方 `vis-network@9.1.2` 的 `dist/dist/vis-network.min.css`。本地扩展名未标记 `min`，不能据此认定它是上游非压缩样式。
- `lib/vis-9.1.2/vis-network.min.js`：与 PyVis `v0.3.2` 副本仅差 26 处 CRLF→LF。相对 npm 官方 `vis-network@9.1.2` 的 `dist/vis-network.min.js`，则是 3 处 U+00A0 被替换为普通空格，另少一个文件末尾 LF。三个替换发生在 JS 字符串数据中，**不能把 npm→PyVis 的差异表述为“纯格式化”或“逐字节一致”**。此补丁不修复这些继承差异。Vis 的 Apache-2.0 与 MIT 两份原文均予保留。
- `lib/bindings/utils.js`：逐字节匹配 WestHealth/PyVis `v0.3.2`（commit `ccb7ce745ee4159ce45eac70b9848ab965fc0906`）的 `pyvis/lib/bindings/utils.js`，保留 BSD-3-Clause 原文。

五个文件均可在上述 PyVis 固定版本找到精确或明确换行转换后的对应副本。这证明可复核的上游对应关系，不证明当初具体从哪个地址下载，也不能仅凭相同内容推断唯一的历史来源或唯一 PyVis 版本。

## 打包依赖与声明

通过上述 npm 发布包中的对应 source map，核对了 12 个打包依赖的 425 段源代码；每一段都与指定 npm 版本的源码文件逐字节一致：

- Tom Select：`@orchidjs/sifter@0.9.0`
- Vis：`@babel/runtime-corejs3@7.17.8`、`@egjs/hammerjs@2.0.17`、`component-emitter@1.3.0`、`core-js-pure@3.21.1`、`keycharm@0.4.0`、`regenerator-runtime@0.13.9`、`timsort@0.3.0`、`tslib@2.3.1`、`uuid@8.3.2`、`vis-data@7.1.4`、`vis-util@5.0.3`

`third_party_licenses/` 保存发布物的原始 LICENSE 和版权声明，保留原始字节、版权人及换行。`tslib` 的 `CopyrightNotice.txt` 也已收录。Sifter 0.9.0 的 npm 包和固定 tag 中未找到独立 LICENSE/NOTICE；它的 npm 元数据与精确匹配源码声明 Apache-2.0，相关源码版权声明已保留，Apache 全文可见 Tom Select 的许可证副本。

`SOURCE-NOTICES.txt` 是从对应发布包 source map 中逐字提取的版权、许可及作者注释，包含 Tom Select 的 MicroPlugin、Sifter、highlight 及插件作者，以及 Vis 内嵌组件的声明。标题和分隔线是本补丁增加的导航文字；它**不是上游提供的 NOTICE 文件**，不应冒充上游 NOTICE。检查的顶层项目固定源码树与 Tom Select/Vis npm 包未发现独立 NOTICE 文件。

## 仍需显式处理的边界

1. Tom Select 中 `highlight v3` 的精确源码声明 MIT，并列出 Johann Burkard、Marshal、Brian Reavis；原始注释已保留，但尚未取得并核验原始 v3 发行物独立、完整的 MIT 许可证文本。原作者页面可以读取，旧 v3 JS 下载返回 403；没有用第三方镜像或臆造版权年份填补。
2. Tom Select 的改写版 MicroEvent 明确署名 Jerome Etienne。官方原项目存在 MIT 许可证，但该改写版对应的原项目历史 revision 尚未确定。已保留 Tom Select 发布源码中的原始署名；没有声称它逐字节匹配某个原始 MicroEvent 版本，也没有将未经该对应关系核验的独立许可文本混入已核验副本。

以上两项详细证据和官方链接列在 `VENDORED_PROVENANCE.json` 的 `open_issues`。可先审阅、合入这些已确定的归属补充；不能据此宣称“所有第三方许可已经完整核验”或据此放行整个二进制发行。正式发行前应闭合或由负责人明确审阅这些边界。不要擅自删除或重写继承资源以绕过问题。

## 文件与使用方式

- `VENDORED_PROVENANCE.json`：五个资源的 SHA-256、Git blob SHA-1、固定来源链接、精确差异、12 个依赖版本、官方 npm 压缩包完整性记录和未闭合项
- `LICENSE_FILES_SHA256.json`：本补丁文本文件的 SHA-256 清单（不包含清单自身）
- `third_party_licenses/`：已核验原文及声明摘录
- `verify_vendored_licenses.py`：仅使用 Python 标准库的只读校验，不联网、不写入目标源码树

从本目录执行 `python verify_vendored_licenses.py --source-root /path/to/AI-Bridge`，校验补丁文本与五个目标资源。没有源代码目录时可执行 `python verify_vendored_licenses.py`，只校验补丁自身。

这些新增文件位于 `licenses/vendor/`；不要覆盖或更换项目已有主 `LICENSE`。从项目根目录可运行 `python licenses/vendor/verify_vendored_licenses.py --source-root .`。源码分发时保留这些资料和资源自带声明；二进制发行仍需单独确保实际发行包携带相应许可资料。若资源更新，必须重新核验并更新来源记录，不能沿用旧哈希。

本补丁提供技术证据与许可原文，不代替法律意见。
