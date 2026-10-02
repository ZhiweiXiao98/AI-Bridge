# GoAmzAI 平台技术情报

> 本文档记录数据源平台（GoAmzAI）的关键技术信息，供 AI 协作者理解浏览器模式爬取目标的技术栈和对抗策略。
> 最后更新：2026-05-10（新增 §3 window.aiSiteInfo 配置结构、§4 Amethyst Design System、页面布局层级、站点指纹、选择器补充）

---

## 1. 平台身份

### 名称
**GoAmzAI** — 商业级私有化 AIGC 集成平台

### 当前已知站点
| 站点 | URL | 备注 |
|------|-----|------|
| 欧亿AI | `https://ai8.rcouyi.com` | 当前主要数据源 |
| 天道AI | `https://www.tiandaoai.top` | 备用 |
| xstech | `https://xstech.one/chat` | 备用 |

**重要**：这些站点使用同一套 GoAmzAI 源码部署，前端结构完全一致，选择器通用。站长仅在后台填写了不同的网站名称（如"欧亿AI-8.0 Pro"只是后台配置的显示名，不是框架名）。

### 性质
- **非开源**：付费授权/倒卖源码的商业系统
- **面向场景**：让不懂技术的运营者快速搭建 AI 镜像站并收费
- **自带**：支付接口（微信/支付宝）、卡密系统、分销返利、积分扣费倍率

---

## 2. 技术栈

| 层 | 技术 | 关键特征 |
|----|------|----------|
| **前端框架** | Vue3 + Vite | SPA，路由由前端控制；资源命名含 hash（如 `app-NH56F_z3.js`） |
| **UI 组件库** | NaiveUI | 所有原生组件带 `n-` 前缀（n-button, n-image, n-scrollbar-container 等）；实测使用 42 个组件 |
| **代码编辑器** | Monaco Editor | `.monaco-editor` 容器，`.view-lines` 渲染行，按视口懒渲染；预加载 40+ 语法高亮模块 |
| **Markdown 渲染** | Markstream | class `markstream vue markdown-renderer`，节点化渲染（`.node-slot[data-node-type]`） |
| **图标库** | Iconify | 多图标集混用：`ri`/`ic`/`ph`/`fluent`/`ant-design`/`tabler`/`material-symbols`/`icon-park-outline`/`fa` |
| **自定义前缀** | `aa-` | GoAmzAI 自定义 CSS（aa-chat-input, aa-sidebar-list-item 等） |
| **设计系统** | Amethyst Design System V3.0 | 自建 CSS 变量体系，品牌色 `#764AF1`，支持亮/暗模式语义切换 |
| **后端** | Golang + Gin | 高并发，低内存（<100MB） |
| **数据库** | MySQL 5.7 + Redis | 关系存储 + 缓存加速 |
| **部署** | 宝塔面板 | 5 分钟快速部署 |

### 前端关键 DOM 特征

```
#app                    → Vue 应用根节点
#app-main               → 主体内容容器（class 含 "dark"）
.global-header          → 顶部导航栏（logo + 语言 + 套餐 + 用户）
.global-layout          → 主布局容器（sidebar + content）
.n-layout-sider         → 左侧边栏（菜单 + 会话列表）
.n-layout-content       → 右侧内容区（聊天区域）
.mobile-global-menu     → 移动端菜单（桌面端 display:none）
n-scrollbar-container   → NaiveUI 滚动容器（聊天消息区域）
n-button                → NaiveUI 按钮
n-image                 → NaiveUI 图片组件
.monaco-editor          → Monaco 编辑器容器
.view-lines             → Monaco 渲染的代码行
.code-block-container   → 代码块外层包装
.chat-item              → 单条聊天消息
[data-message-ai="true/false"]  → AI/User 角色标记
.aa-chat-input          → 输入区域
.aa-sidebar-list-item   → 左侧会话列表项
.markstream             → Markstream Markdown 渲染器
.node-slot[data-node-type]  → 渲染节点（code_block/text/image 等）
```

### GoAmzAI 站点指纹

通过 `<meta>` 标签可快速识别 GoAmzAI 部署的站点：

```html
<meta name="generator" content="GoAmzAI(EP-Version)">
```

此标签在所有 GoAmzAI 站点中均存在，可用于爬取前验证目标是否为 GoAmzAI 平台。

### 页面布局层级

从 `page_outer.html` 解析确认的完整布局层级：

```
body.theme-dark
└── div#app
    └── div.n-config-provider (全局主题，CSS 变量注入点)
        └── div#app-main.dark
            ├── div.global-header (顶部栏)
            │   ├── div.l (logo + 站点名，含 .logo-scan-light 动画)
            │   └── div.r (语言切换 + 套餐按钮 + 用户头像)
            ├── div.global-layout.user-layout (主布局)
            │   └── div.n-layout (NaiveUI 布局容器)
            │       └── div.n-layout-scroll-container (flex row)
            │           ├── div.n-layout-sider (左侧边栏)
            │           │   ├── 导航菜单 (chat/draw/video/... 14项)
            │           │   ├── 会话列表 (.aa-sidebar-list-item)
            │           │   └── 工具按钮 (新建/折叠/更多)
            │           └── div.n-layout-content (右侧内容区)
            │               └── 聊天消息 + 输入区
            └── div.mobile-global-menu (移动端菜单，桌面端隐藏)
```

**关键观察**：
- `#app-main` 的 class 包含 `"dark"`，是暗黑模式的标记
- `.n-config-provider` 上注入了 `--aa-c-primary` 和 `--aa-c-primary-low` 两个 CSS 变量，是全局主题色入口
- 侧边栏使用 NaiveUI 的 `n-layout-sider`，带 `animate__animated animate__fadeInLeft` 动画
- 移动端菜单 `.mobile-global-menu` 在桌面端 `display:none`，但 DOM 中完整存在 16 个 `.menu-item`

### 2026-05-10 实测 DOM 契约

以下信息来自当前 `https://ai8.rcouyi.com/chat#550028` 页面只读探测，未执行点击、输入或清空。

**聊天消息滚动容器**

页面存在多个 `.n-scrollbar-container`，不能只取第一个。真实聊天消息滚动容器满足：

```json
{
  "className": "n-scrollbar-container",
  "hasChatItem": true,
  "chatItemCount": 50,
  "scrollHeight": 51158,
  "clientHeight": 1130,
  "childClass": "n-scrollbar-content"
}
```

当前可靠定位：

```xpath
//div[contains(@class, 'n-scrollbar-container')][.//div[contains(@class, 'chat-item')]]
```

注意：`n-scrollbar-rail[data-scrollbar-rail="true"]` 是 NaiveUI 的视觉滚动条轨道，鼠标不靠近时会隐藏；它不是实际滚动容器，不应作为 `scrollTop` 操作对象。

**消息节点**

```html
<div class="chat-item p-3 mode-list ai"
     data-message-id="6007369"
     data-message-ai="true">
  ...
</div>
```

用户消息同样使用 `.chat-item`，通过 `data-message-ai="false"` 区分。

**AI 正文与代码块**

当前 AI 消息正文结构：

```html
<div class="aa-html" chatid="6007369" isshare="false">
  <div class="aa-html-content">
    <div class="markstream vue markdown-renderer dark">
      <div class="node-slot" data-node-index="54" data-node-type="code_block">
        <div class="node-content">
          <div class="code-block-container ...">
            <div class="code-block-header">...</div>
            <div class="code-block-shell-content">
              <div class="code-editor-container" data-mode-id="plaintext">
                <div class="monaco-editor">...</div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</div>
```

代码块检测应优先使用：

```css
.node-slot[data-node-type="code_block"]
```

再 fallback 到：

```css
.code-block-container, pre
```

不要优先以 `.monaco-editor` 作为代码块边界；它是 Monaco 内部布局层，受视口渲染影响更大。

**底部输入区**

真实输入框：

```html
<textarea class="n-input__textarea-el" rows="3" placeholder="输入消息内容"></textarea>
```

可靠定位：

```css
div.aa-chat-input textarea
```

页面上会存在大量 Monaco 内部隐藏或离屏 `textarea.inputarea`，因此不要全局搜索普通 `textarea` 后取第一个。

**清空按钮**

当前清空按钮位于底部输入区附近：

```html
<button class="n-button n-button--default-type n-button--tiny-type n-button--ghost clickable"
        type="button">
  <span class="n-button__content">清空</span>
</button>
```

定位时应优先限定在 `.aa-chat-input` 或 `.chat-input-box` 下，再匹配文本 `清空`。不要全页面扫所有按钮直接点击。

**发送按钮**

当前发送按钮也位于底部输入区附近：

```html
<button class="n-button n-button--primary-type n-button--small-type n-button--secondary"
        type="button">
  <span class="n-button__content">发送</span>
</button>
```

输入框为空时按钮会带 disabled 状态。定位同样应优先限定在 `.aa-chat-input` 或 `.chat-input-box` 下。

**附件按钮与文件输入**

当前底部输入区存在附件按钮：

```html
<button class="n-button n-button--default-type n-button--small-type" type="button">
  <span class="n-button__content">附件</span>
</button>
```

可靠定位：

```xpath
//button[contains(@class, 'n-button') and .//span[contains(text(), '附件')]]
```

文件选择入口由 NaiveUI Upload 组件创建，项目当前使用：

```css
input.n-upload-file-input
```

以及通用 fallback：

```css
input[type="file"]
```

注意：Selenium 上传文件不依赖原生文件选择窗口，最终应对 `input[type="file"]` 执行 `send_keys(file_path)`。如果点击 `附件` 后 DOM 中没有创建或暴露文件输入，上传会失败。

**AI 消息操作按钮**

AI 消息外层使用：

```css
.chat-item[data-message-ai="true"][data-message-id]
```

当前已确认的 `复制` 按钮来自代码块头部，不是整条 AI 消息操作：

```html
<button type="button" class="chat-md-action-btn" aria-label="复制">...</button>
```

这类按钮位于：

```css
.node-slot[data-node-type="code_block"] .code-block-container .chat-md-action-btn[aria-label]
```

因此解析“复制 AI 输出内容”时必须先区分两类复制：

| 操作 | 当前状态 | 风险 |
|------|----------|------|
| 复制代码块内容 | 已实测，`aria-label="复制"`，位于 `.code-block-container` 内 | 只能复制单个代码块 |
| 复制整条 AI 输出 | 已实测，AI 消息 hover 操作栏第 1 个 tiny `n-button`，`iconify--ph` 双矩形复制图标 | 不能误点代码块复制 |
| 删除 AI 输出对话 | 已实测，AI 消息 hover 操作栏第 5 个 tiny `n-button`，`iconify--ant-design` 垃圾桶图标 | 属于破坏性操作，必须精确限定到目标 `.chat-item[data-message-id]` |
| 重新生成 AI 对话 | 已实测，AI 消息 hover 操作栏第 4 个 tiny `n-button`，`iconify--tabler` 双循环箭头图标 | 会改变当前对话状态，执行前需要确认目标消息 |

用户提供的 hover 操作栏 DOM 存放于 `docs/dom`。完整页面 DOM 样本存放于 `docs/page_outer.html`，大小约 2MB；其中确认当前页面有 50 条真实 `.chat-item`，25 条 user、25 条 AI，最后一组消息 `data-message-id="6007369"`。

该操作栏结构是：

```html
<div role="none" class="n-space">
  <span>2026-05-09 23:17:55</span>
  <span>Gpt 5.5 Medium</span>
  <button class="n-button n-button--default-type n-button--tiny-type">复制整条输出</button>
  <button class="n-button n-button--default-type n-button--tiny-type">引用/引用回复</button>
  <button class="n-button n-button--default-type n-button--tiny-type">朗读</button>
  <button class="n-button n-button--default-type n-button--tiny-type">重新生成</button>
  <button class="n-button n-button--default-type n-button--tiny-type">删除</button>
</div>
```

该组按钮未提供 `aria-label` 或 `title`，不能直接按可访问文本定位。已知图标特征：

| 操作 | 图标库 | 关键 path |
|------|--------|-----------|
| 复制整条输出 | `iconify--ph`，`viewBox="0 0 256 256"` | `M216 40v128h-48V88H88V40Z` |
| 重新生成 | `iconify--tabler`，`viewBox="0 0 24 24"` | `M20 11A8.1 8.1 0 0 0 4.5 9M4 5v4h4...` |
| 删除 | `iconify--ant-design`，`viewBox="0 0 1024 1024"` | `M864 256H736v-80c0-35.3...` |

复制整条输出与代码块复制的区别：

- 整条 AI 输出复制：位于 `.chat-item[data-message-ai="true"]` 的消息级 hover 操作栏，按钮是 NaiveUI tiny `n-button`。
- 代码块复制：位于 `.node-slot[data-node-type="code_block"] .code-block-container` 内，按钮是 `.chat-md-action-btn[aria-label="复制"]`。

建议定位策略：

1. 先锁定目标 AI 消息：

```css
.chat-item[data-message-ai="true"][data-message-id="目标消息ID"]
```

2. 在该消息内查找 hover 操作栏，但排除代码块内部按钮：

```js
button:not(.code-block-container button)
```

3. 对没有 `aria-label/title` 的消息级按钮，按同一操作栏内的顺序和图标 path 二次确认。

如果 GoAmzAI 版本更新导致按钮顺序变化，必须重新采集 hover 操作栏 DOM；不要只根据视觉位置猜测。

当前代码落点：

```python
app/core/driver/interaction.py
InteractionManager.click_ai_message_action(action, message_id=None, confirm_delete=False)

app/core/driver/__init__.py
ChromeConnector.click_ai_message_action(action, message_id=None, confirm_delete=False)
```

支持 `copy`、`regenerate`、`delete` 三个动作。`delete` 默认受保护，必须显式传入 `confirm_delete=True`。

---

## 3. window.aiSiteInfo 站点配置结构

GoAmzAI 在每个页面的 `<head>` 中注入 `window.aiSiteInfo` 全局配置对象。这是理解平台功能开关、菜单结构、认证方式的关键数据源，也可用于运行时动态适配不同 GoAmzAI 站点。

### 3.1 完整结构

```javascript
window.aiSiteInfo = {
  name: "欧亿AI-8.0 Pro",           // 站点显示名（站长后台配置，非框架名）
  logo: "https://.../logo.png",     // 站点 Logo URL
  style: { ... },                    // 主题样式配置
  menus: [ ... ],                    // 导航菜单配置
  gm: {},                            // 未知用途，当前为空对象
  ofd: true,                         // 未知开关
  setting: { ... },                  // 站点功能设置
  auth: { ... },                     // 认证方式配置
  mt: { icx: true },                 // 未知模块标记
  dd: "mfoS2YWk4LnJjb3V5aS5jb20=cG0J9"  // Base64 编码的域名信息
}
```

### 3.2 style 主题样式配置

```javascript
style: {
  primaryColor: "#764AF1",           // 主色
  primaryColorHover: "#8B61FF",      // 悬停色
  primaryColorPressed: "#6538D6",    // 按下色
  primaryLowColorDark: "#1A1137",    // 暗模式低饱和背景
  borderRadius: "8px",               // 全局圆角
  logoScanLight: true,               // Logo 扫光动画开关
  primaryColorSuppl: "#8B61FF",      // 补充色
  primaryLowColor: "#F4F0FF",        // 亮模式低饱和背景
  defMode: "auto"                    // 默认主题模式 (auto/light/dark)
}
```

**利用价值**：
- `primaryColor` 与 `.n-config-provider` 上的 `--aa-c-primary` CSS 变量一致，可用于验证主题色是否加载
- `logoScanLight` 控制 logo 的扫光 CSS 动画（`.logo-scan-light` class）
- `defMode` 决定首次加载的明暗模式，影响 DOM 中 `#app-main` 的 class

### 3.3 menus 导航菜单配置

菜单分为两类：**系统菜单**（`sys: true`）和**自定义菜单**（`sys` 缺省或为 false）。

**系统菜单**（12 个，GoAmzAI 内置，所有站点一致）：

| key | 路由 | 图标 | 功能 |
|-----|------|------|------|
| chat | /chat | ri:chat-ai-line | AI 对话 |
| draw | /draw | ic:outline-draw | AI 绘画 |
| video | /video | ri:video-on-ai-line | AI 视频 |
| music | /music | ph:music-notes-duotone | AI 音乐 |
| ppt | /ppt | icon-park-outline:ppt | AI PPT |
| img-create | /img-create | fluent:image-sparkle-16-regular | 图像创作 |
| app | /app | ri:apps-2-ai-line | 应用中心 |
| galleries | /galleries | ant-design:picture-outlined | 画廊 |
| mind | /mind | material-symbols:mindfulness-outline | 思维导图 |
| pdf | /pdf | ph:file-pdf-duotone | PDF 对话 |
| rag | /rag | ph:book-duotone | 知识库 |
| promotion | /promotion | ph:handshake-duotone | 推广 |

**自定义菜单**（站长后台添加，各站不同）：

```javascript
{
  name: "画布绘画",                    // 显示名
  badgeColor: "#CB1B1B",
  key: "0f75e6c36a1c256ea9ff9b0a3d535405",  // MD5 hash 作为 key
  action: "url",                       // 跳转方式：url=外链, path=站内路由
  value: "https://ai.dian-ying.cn",    // 外链地址
  open: true,
  icon: "fa fa-file-alt"               // FontAwesome 图标
}
```

**利用价值**：
- 系统菜单的 `key` 和 `value` 在所有 GoAmzAI 站点中一致，可用于硬编码路由映射
- 自定义菜单的 `action: "url"` 表示外链跳转，`action: "path"` 表示站内路由
- 自定义菜单的 `key` 是 MD5 hash，无规律，不能硬编码
- 菜单的 `open` 字段控制是否显示，可用于检测某功能是否启用

### 3.4 setting 站点功能设置

```javascript
setting: {
  captchaMode: "slide",              // 验证码类型（slide=滑块）
  builtinAvatar: false,              // 是否使用内置头像
  guestUserAccess: true,             // ★ 游客是否可访问（无需登录即可使用）
  footerContent: "",                 // 页脚内容
  oauth: [],                         // 第三方登录（当前为空）
  integralIcon: "⚡",                // 积分图标
  wechatBrowserPay: false,           // 微信浏览器内支付
  authPageBanner: null,              // 登录页 Banner
  integralName: "积分",              // 积分显示名（可自定义，如"额度""Token"）
  captchaOffLogin: false,            // 登录时是否关闭验证码
  mobileMaxShow: 6,                  // 移动端最多显示菜单数
  codeCaptcha: true,                 // 是否启用验证码
  giftSign: true,                    // 是否启用签到送积分
  share: true                        // 是否启用分享功能
}
```

**关键发现**：
- `guestUserAccess: true` 意味着当前站点允许未登录用户直接使用，这对自动化操作是利好——可能无需处理登录流程
- `captchaMode: "slide"` 表示使用滑块验证码，自动化时需要处理
- `integralName` 可自定义，不同站点的积分名称可能不同（"积分"/"额度"/"Token"），UI 文本匹配时不能硬编码
- `mobileMaxShow: 6` 表示移动端只显示前 6 个菜单，其余折叠

### 3.5 auth 认证方式配置

```javascript
auth: {
  phoneReg: true,                    // 手机号注册
  phoneCodeLogin: true,              // 手机验证码登录
  phoneRegValidate: true,            // 手机号注册需验证
  mailReg: true,                     // 邮箱注册
  mailCodeLogin: true,               // 邮箱验证码登录
  mailRegValidate: true              // 邮箱注册需验证
}
```

**利用价值**：
- 所有认证方式均开启，自动化登录时可选择最方便的方式
- 邮箱验证码登录可能比手机号更容易自动化（无需接码平台）

### 3.6 dd 字段

```javascript
dd: "mfoS2YWk4LnJjb3V5aS5jb20=cG0J9"
```

Base64 解码后包含站点域名信息。这是 GoAmzAI 的授权校验字段，用于验证当前域名是否有合法授权。不应修改或伪造。

### 3.7 运行时读取方式

在 Selenium 中可通过以下方式读取完整配置：

```python
config = driver.execute_script("return window.aiSiteInfo;")
```

**应用场景**：
1. 爬取前验证目标是否为 GoAmzAI 平台（检查 `window.aiSiteInfo` 是否存在）
2. 动态获取菜单结构，无需硬编码路由
3. 检查 `guestUserAccess` 判断是否需要登录
4. 读取 `integralName` 适配不同站点的积分显示文本
5. 通过 `menus` 判断某功能模块是否启用（`open: true/false`）

---

## 4. Amethyst Design System V3.0

GoAmzAI 使用自建的 CSS 设计系统，名为 **Amethyst Design System V3.0**（紫晶设计系统），通过 `<style>` 标签注入页面。该系统定义了完整的语义化 CSS 变量体系。

### 4.1 CSS 变量结构

```css
:root {
  /* 品牌色阶 */
  --brand-purple-500: #764AF1;    /* 核心主色 */
  --brand-purple-400: #8B61FF;    /* Hover/亮色 */
  --brand-purple-600: #6538D6;    /* Pressed/深色 */

  /* 中性色阶 */
  --neutral-0: #FFFFFF;
  --neutral-50: #F9FAFB;
  --neutral-100: #F3F4F6;
  --neutral-200: #E5E7EB;
  --neutral-500: #6B7280;
  --neutral-700: #374151;
  --neutral-800: #1F2937;
  --neutral-900: #111827;

  /* 语义变量（亮模式默认值） */
  --bg-canvas: var(--neutral-50);
  --bg-surface: var(--neutral-0);
  --bg-surface-secondary: #F4F0FF;
  --bg-interactive: var(--neutral-0);
  --bg-brand: var(--brand-purple-500);
  --text-primary: var(--neutral-800);
  --text-secondary: var(--neutral-500);
  --text-on-brand: var(--neutral-0);
  --text-link: var(--brand-purple-500);
  --border-default: var(--neutral-200);
  --border-interactive: var(--brand-purple-500);

  /* 几何与节奏 */
  --radius-sm: 4px;
  --radius-md: 8px;
  --radius-lg: 16px;
  --radius-full: 9999px;
  --spacing-unit: 4px;
}

/* 暗黑模式覆盖 */
html[data-theme='dark'], body.dark-mode {
  --bg-canvas: var(--neutral-900);       /* #111827 */
  --bg-surface: var(--neutral-800);      /* #1F2937 */
  --bg-surface-secondary: #1A1137;       /* 紫色低饱和 */
  --bg-interactive: #24184E;             /* 输入框背景 */
  --text-primary: var(--neutral-50);
  --border-default: var(--neutral-700);
  --border-interactive: var(--brand-purple-400);
}
```

### 4.2 与 NaiveUI 主题的交互

NaiveUI 组件的运行时主题通过 `.n-config-provider` 的 inline style 注入：

```html
<div class="n-config-provider" style="--aa-c-primary: #764AF1; --aa-c-primary-low: #1A1137;">
```

这两个 `--aa-` 前缀变量来自 `window.aiSiteInfo.style`，是 GoAmzAI 桥接自身配置与 NaiveUI 主题的接口。

### 4.3 对自动化的影响

- 暗黑模式下输入框背景为 `#24184E`，截图比对时需注意
- 品牌色 `#764AF1` 可用于视觉定位关键按钮（如发送按钮）
- `--bg-interactive` 是输入框等交互组件的背景色，可用于验证输入框是否获得焦点

---

## 5. 懒加载机制详解（三层叠加）

### 第 1 层：NaiveUI NVirtualList（最致命）

NaiveUI 的虚拟滚动列表 `NVirtualList` 内部使用 `IntersectionObserver` 控制哪些 DOM 节点保留、哪些回收。

**正常行为**：滚动时，Observer 检测到新元素进入视口 → 触发渲染回调 → DOM 节点创建。
**最小化时**：Observer 被冻结 → 离屏消息 DOM 被回收 → `find_elements()` 找到的元素数量骤减。

### 第 2 层：Monaco Editor 视口渲染

Monaco Editor 只渲染视口内可见的代码行（`.view-lines`），折叠代码块更是需要用户点击才展开并异步布局。

**正常行为**：点击展开按钮 → Monaco 异步布局 → `offsetHeight` 从占位高度变为实际高度。
**最小化时**：布局计算被冻结 → `offsetHeight` 永远是 0 或占位高度 → height 轮询超时。

### 第 3 层：项目代码的视口依赖

`scroll_traverse()` 中使用 `document.elementFromPoint(window.innerWidth/2, window.innerHeight/2)` 检测当前视口中心是否在代码块上。

**最小化时**：viewport 变为 0×0 → `elementFromPoint` 返回 null → 代码块检测失效 → 滚动策略选错。

---

## 6. 最小化后数据采集失效的完整因果链

```
窗口最小化
  │
  ├─→ Windows 通知 Chrome "窗口被遮挡" (occlusion)
  │     │
  │     └─→ Chrome 进入节能模式
  │           ├─ 渲染暂停
  │           ├─ JS 定时器节流
  │           └─ IntersectionObserver 冻结
  │                 │
  │                 ├─→ NaiveUI NVirtualList 不触发渲染回调
  │                 │     → 离屏消息 DOM 被回收
  │                 │     → find_elements() 结果不完整
  │                 │
  │                 └─→ Monaco Editor 布局计算冻结
  │                       → 展开按钮点击后 offsetHeight 不更新
  │                       → manual_toggle_block() height 轮询超时
  │
  └─→ viewport 变为 0×0
        │
        └─→ elementFromPoint() 返回 null
              → scroll_traverse() 代码块检测失效
              → 滚动速度策略选错

最终结果：数据采集全部中断，软件空转
```

### 图片附件上传失败的单独链路

在未修改 Chrome 启动参数前，最小化浏览器后“添加图片附件”会失败，和消息采集失败同源，但表现路径更靠近 NaiveUI Upload 组件：

```
窗口最小化
  │
  ├─→ Chrome 认为窗口被遮挡
  │     └─→ 渲染、布局、定时器、Observer 被节流或冻结
  │
  ├─→ 点击“附件”后 Upload 组件的弹层/隐藏 input 未及时创建或未完成布局
  │     └─→ DOM 中找不到可用的 input[type="file"] / input.n-upload-file-input
  │
  ├─→ 即使找到了 input，后续“确认”按钮或上传列表状态也可能不刷新
  │     └─→ 脚本等待确认按钮、上传完成状态或图片预览时超时
  │
  └─→ 打开窗口后恢复渲染
        └─→ input、上传列表、确认按钮正常出现，上传恢复
```

项目当前上传逻辑是：

1. 找到并点击 `附件` 按钮。
2. 等待短时间。
3. 查找 `input.n-upload-file-input`。
4. 对文件输入执行 `send_keys(file_path)`。
5. 如存在 `确认` 按钮，再点击确认。

失败点主要在第 1-3 步：最小化时点击虽然可能被 Selenium 发送出去，但前端组件没有完成后续渲染，导致文件输入没有出现在 DOM 中。打开窗口后，Chrome 恢复布局与异步任务，文件输入和上传确认流程才完整。

建议后续改造：

- 优先检查页面是否已经存在 `input[type="file"]`，存在则直接 `send_keys`，减少对点击 `附件` 的依赖。
- 点击 `附件` 后用显式等待轮询 `input[type="file"], input.n-upload-file-input`，不要固定 sleep。
- 上传失败时记录细分错误：`upload_trigger_not_found`、`upload_input_not_created`、`upload_input_send_keys_failed`、`upload_confirm_not_found`。
- 在未验证新启动参数效果前，不把“最小化可稳定上传”视为已解决，只记录为理论修复方向。

---

## 7. 对抗方案

### Step 1：Chrome 启动参数（必做，1 行改动）

**文件**：`start_server.py` → `launch_chrome()`

```python
cmd = (
    f'start "" "{self.chrome_path}" '
    f'--remote-debugging-port={CHROME_PORT} '
    f'--user-data-dir="{user_data}" '
    f'--disable-backgrounding-occluded-windows '        # 阻止最小化时节流
    f'--disable-features=CalculateNativeWinOcclusion '  # 阻止 Windows 通知遮挡
    f'"https://ai8.rcouyi.com/chat"'
)
```

**原理**：
- `--disable-backgrounding-occluded-windows`：Chrome 不降低被遮挡窗口的渲染优先级
- `--disable-features=CalculateNativeWinOcclusion`：禁用 Windows 原生遮挡检测，Chrome 以为窗口始终可见

**效果**：IntersectionObserver 正常触发 → NVirtualList 正常工作 → Monaco 布局正常完成。**同时解决第 1 层和第 2 层懒加载问题。**

**代价**：最小化后 CPU/内存占用略增（因为 Chrome 继续渲染）。对于持续采集场景，这个代价完全合理。

### Step 2：注入 IntersectionObserver 劫持（兜底保险）

**文件**：`connection.py` → `connect()` 成功后

```python
force_lazy_js = """
const OriginalIO = window.IntersectionObserver;
window.IntersectionObserver = function(callback, options) {
    const observer = new OriginalIO(callback, options);
    const origObserve = observer.observe.bind(observer);
    observer.observe = function(target) {
        callback([{
            isIntersecting: true,
            target: target,
            intersectionRatio: 1.0,
            boundingClientRect: target.getBoundingClientRect(),
            rootBounds: null,
            time: Date.now()
        }], observer);
        return origObserve(target);
    };
    return observer;
};
window.IntersectionObserver.prototype = OriginalIO.prototype;
"""
self.driver.execute_cdp_cmd('Page.addScriptToEvaluateOnNewDocument', {'source': force_lazy_js})
```

**原理**：让所有 IntersectionObserver 的回调立即触发，NaiveUI 以为所有消息都在视口内，不回收 DOM。

**副作用**：所有懒加载内容同时渲染，可能短暂卡顿。对采集场景可接受。

### Step 3：替换 elementFromPoint（代码层根治）

**文件**：`interaction.py` → `scroll_traverse()`

将原来的视口像素检测：
```python
js_check_view = """
var el = document.elementFromPoint(window.innerWidth / 2, window.innerHeight / 2);
if (el && el.closest('.code-block-container, .monaco-editor, pre')) return true;
return false;
"""
```

替换为基于 DOM 结构的检测：
```python
js_check_view = """
var container = document.evaluate(arguments[0], document, null,
    XPathResult.FIRST_ORDERED_NODE_TYPE, null).singleNodeValue;
if (!container) return false;
var scrollTop = container.scrollTop;
var viewHeight = container.clientHeight || 600;
var midY = scrollTop + viewHeight / 2;
var codeBlocks = container.querySelectorAll('.node-slot[data-node-type="code_block"]');
if (!codeBlocks.length) {
    codeBlocks = container.querySelectorAll('.code-block-container, pre');
}
for (var i = 0; i < codeBlocks.length; i++) {
    var rect = codeBlocks[i].getBoundingClientRect();
    var containerRect = container.getBoundingClientRect();
    var blockTop = scrollTop + (rect.top - containerRect.top);
    var blockBottom = blockTop + (codeBlocks[i].offsetHeight || rect.height || 0);
    if (midY >= blockTop && midY <= blockBottom) return true;
}
return false;
"""
in_code_block = self.driver.execute_script(js_check_view, target_xpath)
```

**原理**：用 `getBoundingClientRect` + 滚动位置的数学关系判断，不依赖实际可见的 viewport 像素。即使窗口 0×0 也能正确判断。

---

## 8. 选择器参考（GoAmzAI 通用）

以下是项目 `app/core/driver/config.py` 中已验证的选择器，适用于所有 GoAmzAI 站点：

| 用途 | 选择器 | 来源 |
|------|--------|------|
| 聊天消息 | `.chat-item[data-message-id][data-message-ai]` | 2026-05-10 实测 |
| AI 正文 | `.aa-html .aa-html-content` | 2026-05-10 实测 |
| 内容块 | `.node-slot[data-node-index][data-node-type]` | Markstream 渲染层 |
| 代码块 | `.node-slot[data-node-type="code_block"]` | 2026-05-10 实测 |
| 输入框 | `div.aa-chat-input textarea` | GoAmzAI 自定义 |
| 清空按钮 | `.aa-chat-input button, .chat-input-box button` 中文本为 `清空` | 2026-05-10 实测 |
| 发送按钮 | `.aa-chat-input button, .chat-input-box button` 中文本为 `发送` | 2026-05-10 实测 |
| 会话列表 | `.aa-sidebar-list-item` | GoAmzAI 自定义 |
| 活跃会话 | `.aa-sidebar-list-item.active` | GoAmzAI 自定义 |
| 滚动容器 | `//div[contains(@class, 'n-scrollbar-container')][.//div[contains(@class, 'chat-item')]]` | NaiveUI |
| 附件按钮 | `//button[contains(@class, 'n-button') and .//span[contains(text(), '附件')]]` | NaiveUI |
| 文件输入 | `input.n-upload-file-input`, `input[type="file"]` | NaiveUI 上传 |
| 代码块收起/全屏/复制按钮 | `.chat-md-action-btn[aria-label]`，如 `收起`、`复制`、`退出全屏` | 2026-05-10 实测 |
| AI 整条消息复制按钮 | 目标 `.chat-item[data-message-ai="true"][data-message-id]` hover 操作栏内第 1 个 tiny `n-button`，`iconify--ph` 复制图标 | 2026-05-10 用户提供 DOM |
| 删除 AI 输出对话 | 目标 `.chat-item[data-message-ai="true"][data-message-id]` hover 操作栏内第 5 个 tiny `n-button`，`iconify--ant-design` 垃圾桶图标 | 2026-05-10 用户提供 DOM |
| 重新生成 AI 对话 | 目标 `.chat-item[data-message-ai="true"][data-message-id]` hover 操作栏内第 4 个 tiny `n-button`，`iconify--tabler` 双循环箭头图标 | 2026-05-10 用户提供 DOM |
| 全局配置读取 | `window.aiSiteInfo` | 2026-05-10 page_outer.html 解析 |
| 主题色 CSS 变量 | `.n-config-provider` 上的 `--aa-c-primary` | 2026-05-10 page_outer.html 解析 |
| 暗黑模式标记 | `#app-main.dark` 或 `html.theme-dark` | 2026-05-10 page_outer.html 解析 |
| Logo 容器 | `.logo-scan-light`（扫光动画） | 2026-05-10 page_outer.html 解析 |
| 顶部栏 | `.global-header` | 2026-05-10 page_outer.html 解析 |
| 主布局容器 | `.global-layout.user-layout` | 2026-05-10 page_outer.html 解析 |
| 套餐按钮 | `.head-plan-ent`（class 含 success-type） | 2026-05-10 page_outer.html 解析 |
| 聊天工具栏 | `.chat-toolbar`（时间戳 + 模型名 + 操作按钮） | 2026-05-10 page_outer.html 解析 |
| Markstream 渲染器 | `.markstream.vue.markdown-renderer` | 2026-05-10 page_outer.html 解析 |
| 渲染节点 | `.node-slot[data-node-index][data-node-type]` | 2026-05-10 page_outer.html 解析 |

**注意**：这些选择器可能随 GoAmzAI 源码更新而变化，需定期检查。`n-` 前缀的 NaiveUI 选择器相对稳定，`aa-` 前缀的自定义选择器变动风险更高。

---

## 9. 关于 CDP 的说明

项目已通过 `--remote-debugging-port=9527` 开启了 CDP，但当前仅用于 Selenium 连接。以下是对 CDP 能力的澄清：

| CDP 方法 | 能做什么 | 不能做什么 |
|----------|---------|-----------|
| `Runtime.evaluate` | 执行 JS（等同于 `execute_script`） | 不能绕过懒加载，懒加载内容不在 DOM 中 |
| `DOM.getDocument` | 获取当前 DOM 快照 | 不能拿到虚拟滚动已回收的节点 |
| `Page.addScriptToEvaluateOnNewDocument` | 页面加载前注入 JS | 这是 Step 2 的正确用法 |
| `Input.dispatchMouseEvent` | 模拟鼠标事件 | 可以替代 Selenium 的 click，但不解决懒加载 |

**结论**：CDP 不是解决懒加载的银弹。`DOM.getDocument` 拿不到 NaiveUI 虚拟滚动已回收的 DOM 节点，`Runtime.evaluate` 执行 JS 时如果 IntersectionObserver 不触发，代码块的渲染回调不会执行。必须先用 Step 1 让 Chrome 以为窗口可见，Observer 才能正常工作。
