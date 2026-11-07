# 外链解析 Ex | astrbot_plugin_link_ex

![外链解析 Ex](logo.png)

**EX 版维护：[@Enderyouling](https://github.com/Enderyouling)** · **当前版本：3.0.3**

基于 [EndermanMYR/astrbot_plugin_link_preview](https://github.com/EndermanMYR/astrbot_plugin_link_preview) v2.5.0 的 AstrBot 扩展版本。EX 版新增国内平台预览并加强网络请求安全检查，原作署名与 MIT 许可证保留。

[下载 v3.0.3](https://github.com/Enderyouling/astrbot_plugin_link_ex/releases/tag/v3.0.3) · [更新记录](CHANGELOG.md) · [本仓库 PR #1](https://github.com/Enderyouling/astrbot_plugin_link_ex/pull/1)

## 3.0.3 更新

- 兼容 Clash 等代理/TUN 的 Fake-IP DNS：通过固定公网 IP 的 Cloudflare 或 Google DNS-over-HTTPS 查询真实 A/AAAA 地址，再继续公网校验与 IP 固定连接。
- 增加 DoH 超时、响应大小上限、缓存和第二解析器回退；内网、组播、特殊 IPv6、压缩/超大响应和恶意跳转仍会被拒绝。

## 3.0.2 更新

- 新增 Ex 专属图标，放置于根目录 `logo.png`，供 AstrBot 插件市场与本地插件列表识别。
- 文档图标引用改用完整地址，兼容商店文档页面。图标由 imagegen 辅助生成。
- 本次仅更新图标、文档及版本元数据；插件运行逻辑沿用 3.0.1。

## 3.0.1 更新

维护者：Enderyouling（EX 版）。参考并移植 [原作截至 6fbbaf9（3.1.0）的更新](https://github.com/EndermanMYR/astrbot_plugin_link_preview/commit/6fbbaf9)，保留原作与 MIT 署名。

- 支持自动识别不带协议的域名、中文域名、额外顶级域配置和通用网页预览；增加域名屏蔽列表。
- 新增快手、西瓜视频、腾讯视频、优酷、爱奇艺公开页面预览；补充微博视频链接格式。含原有知乎，共 29 个命名平台，另有通用网页兜底。
- 移植看板娘与配色，并提供 show_mascot 开关。修正远端文转图未传入内嵌字体的问题，改进相对封面地址与站点名清理。
- 字体子集采用有上限的 LRU 缓存，字体处理和图片裁边移出事件循环；磁盘缓存清理每五分钟最多执行一次。
- 卡片和全文共用并发上限（默认 3），满载时不无限排队；X 评论超时或抓取失败时取消任务，限制评论缓存容量。
- 翻译结果在渲染前重新过滤；拦截组播地址和超大尺寸图片；保留 DNS 固定 IP、每跳校验、响应大小限制和私有内容拦截。
- 按商城建议删除 render.py 的标准库 logging.getLogger 调用，仅用 AstrBot logger 记录插件事件。

没有引入上游 yt-dlp/ffmpeg 视频下载：它们的外部网络请求不经过 EX 的公网校验。也没有引入证书错误自动降级 HTTP 或 Fake-IP 放行。新增视频站点为公开元信息预览，登录、验证码、站点改版仍可能导致失败。

本版本仍为 astrbot_plugin_link_ex，3.0.0 升级保留同一配置和数据目录。测试使用模拟网络及本地 HTML；真实 AstrBot/QQ 收发、平台实网风控与外部渲染服务隔离未验收。


> EX 3.0.0 基于 v2.5.0，新增 B站（bilibili）、抖音（douyin）、小红书（xiaohongshu）、微博（weibo）、知乎（zhihu）。
>
> B站支持 BV/av 视频及 b23.tv 短链，读取标题、UP主、封面、时长及互动数。其余四个平台读取公开分享页的标题、简介、封面；抖音和小红书支持常见分享短链。不是完整 App 内容抓取，不支持登录后内容、验证码绕过或国内平台评论。平台仅返回登录/验证页时会明确失败；页面结构和网络风控可能影响可用性。
>
> 网络安全：预览和配图仅访问解析到公网 IP 的 HTTP(S) 地址，每次连接（含跳转）固定已验证 IP；不自动使用环境代理，仍支持配置项 proxy。检测到 Fake-IP DNS（例如部分 TUN 模式）时，会通过固定公网 IP 的 DNS-over-HTTPS 查询真实地址，仍拒绝内网地址。管理员配置的 X 内网服务使用独立客户端，不受公网限制。GitHub 私有仓库被拒绝；图片只允许常见位图类型，并在读取时限制大小。正文响应上限 8 MiB。
>
> 新增平台可在 platforms 中分别关闭。X 预览不再使用登录态正文降级；评论只采用公开接口能读取的内容，公开接口不可用时会减少评论。正文响应只接受未压缩传输，拒绝不遵守 Accept-Encoding: identity 的响应，以防解压膨胀；这可能影响少数站点。原版配置与数据不会自动迁移，切换步骤见安装说明。

![Python](https://img.shields.io/badge/Python-3.10%2B-blue)
![AstrBot](https://img.shields.io/badge/AstrBot-v4.16%2B-brightgreen)
![Platform](https://img.shields.io/badge/平台-QQ%20%7C%20OneBot-12B7F5)
![Render](https://img.shields.io/badge/渲染-AstrBot%20文转图-2EAD33)
![License](https://img.shields.io/badge/License-MIT-yellow)

## ✅ 简介 | Introduction

<table>
  <tr>
    <td width="190" align="center">
      <img width="170" alt="外链解析 Ex 图标" src="https://raw.githubusercontent.com/Enderyouling/astrbot_plugin_link_ex/EX-main/logo.png" style="border-radius: 24px;" />
    </td>
    <td>
      <strong>外链解析 · Ex</strong><br />
      B站 · 抖音 · 小红书 · 微博 · 知乎 · YouTube<br />
      <sub>群里发一条链接，回一张排版好的卡片图。</sub>
    </td>
  </tr>
</table>

这是一个为 **AstrBot** 编写的插件：群聊里有人发国内外平台的链接时，自动抓取标题、作者、正文、配图、数据和热门评论，渲染成一张卡片图片发回群里。

[![Stars](https://img.shields.io/github/stars/Enderyouling/astrbot_plugin_link_ex?color=yellow&label=%E6%A0%87%E6%98%9F)](https://github.com/Enderyouling/astrbot_plugin_link_ex/stargazers)
[![Issues](https://img.shields.io/github/issues/Enderyouling/astrbot_plugin_link_ex?color=darkgreen&label=%E5%8F%8D%E9%A6%88)](https://github.com/Enderyouling/astrbot_plugin_link_ex/issues)
[![Pull Requests](https://img.shields.io/github/issues-pr/Enderyouling/astrbot_plugin_link_ex?color=blue&label=%E8%AF%B7%E6%B1%82)](https://github.com/Enderyouling/astrbot_plugin_link_ex/pulls)
[![Last Commit](https://img.shields.io/github/last-commit/Enderyouling/astrbot_plugin_link_ex?color=blueviolet&label=%E6%9C%80%E8%BF%91%E6%9B%B4%E6%96%B0)](https://github.com/Enderyouling/astrbot_plugin_link_ex/commits/EX-main)

> [!IMPORTANT]
> 卡片渲染走 **AstrBot 自带的文转图服务**（`html_render`），插件不再依赖 Playwright、不用装 Chromium、也不用 Docker。代价是渲染依赖该服务，详见下方「渲染」一节。

> [!WARNING]
> 插件内置的屏蔽词**不可能覆盖所有敏感内容**，转发抓取内容存在账号被限制或封禁的风险。**使用前请阅读 [免责声明](#️-免责声明--disclaimer)，风险与合规责任由部署者自行承担。**

## ✅ 功能列表 | Features

- **自动识别**：群消息里出现链接就自动出卡片，不需要 @ 或指令
- **29 个平台**：快手、西瓜视频、腾讯视频、优酷、爱奇艺、B站、抖音、小红书、微博、知乎、YouTube、TikTok、Instagram、X、GitHub、Bluesky、pixiv、Steam、Reddit、维基百科、维基文库、Dailymotion、niconico、Spotify、Vimeo、SoundCloud、Threads、Twitch、Facebook
- **热门评论**：YouTube、TikTok、X、Instagram、GitHub Issue/PR、Bluesky、pixiv、Steam 的卡片会附带几条高赞评论
- **X 评论**：登录态服务仅提供候选链接，实际返回内容必须经公开接口再次读取；无法公开读取的评论不发送
- **Steam 评测**：抓社区里最有帮助的评测，带推荐/不推荐、游玩时长和赞数；填了 Web API Key 还能显示当前在线人数
- **评论单独看**：`/评论` 出一张只放评论的卡，最多 10 条
- **维基全文**：`/全文` 把词条或维基文库作品分页渲染，合并转发发出，中文按简体显示
- **敏感词屏蔽**：内置约 150 个政治敏感词，中文支持插字写法识别，命中的评论单独剔除
- **分级过滤**：自建词表 + 平台标记双重判断，命中整条不发
- **出站检查**：机器人自己要发的消息（含合并转发里的文字）也会在发送前过一遍词表
- **按群开关配图**：`/预览图片` 让管理员单独控制本群卡片是否显示配图
- **翻译**：日/韩/英文帖子在卡片里**直接带译文**（`translate_auto` 默认开）；`/翻译 链接` 手动出同样一张带译文的卡，不会另外再发一条文本
- **竖图完整显示**：多图卡片默认是网格裁切（`object-fit: cover`），检测到竖图（高/宽 > 1.25，比如手机截图）会自动改成纵向堆叠，整张显示不裁
- **深色/浅色主题**：一张配置切换
- **字体内嵌**：卡片自带 Noto Sans SC 子集（400/700 字重），不依赖渲染机装了什么字体，不同机器出来的粗细和字形一致
- **平台品牌色**：每个平台用自己的品牌色（YouTube 红、Spotify 绿、Twitch 紫…），纯黑的品牌（X、GitHub、维基）在深色卡片上自动调亮，保证那条渐变和徽章看得见
- **去重**：同一链接在同一个群里 30 秒内只预览一次

<table>
  <tr>
    <td width="50%" align="center" valign="top"><img alt="YouTube 视频卡片，带播放量、点赞和热门评论" src="docs/images/card-youtube.jpg" /></td>
    <td width="50%" align="center" valign="top"><img alt="GitHub 仓库卡片" src="docs/images/card-github.jpg" /></td>
  </tr>
  <tr>
    <td width="50%" align="center" valign="top"><img alt="Steam 游戏卡片，带价格、推荐数和标签" src="docs/images/card-steam.jpg" /></td>
    <td width="50%" align="center" valign="top"><img alt="浅色主题下的维基百科词条卡片" src="docs/images/card-light.jpg" /></td>
  </tr>
  <tr>
    <td width="50%" align="center" valign="top"><img alt="X 帖子卡片，带回复、转帖、喜欢数和三条热门评论" src="docs/images/card-x.jpg" /></td>
    <td width="50%" align="center" valign="top"><img alt="TikTok 视频卡片，带播放量、点赞、评论、分享、收藏" src="docs/images/card-tiktok.jpg" /></td>
  </tr>
</table>

## 🌐 平台支持 | Platforms

| 平台 | 抓取内容 | 评论 |
|---|---|---|
| 快手 / 西瓜视频 / 腾讯视频 / 优酷 / 爱奇艺 | 公开页面标题、简介与封面；不含视频下载 | — |
| B站（bilibili） | BV/av 视频与 b23.tv 短链；标题、UP主、封面、时长与互动数 | — |
| 抖音（douyin） / 小红书（xiaohongshu） | 公开分享页标题、简介、封面及常见短链 | — |
| 微博（weibo） / 知乎（zhihu） | 公开页面标题、简介与封面 | — |
| YouTube | 标题、频道、简介、封面、时长、播放/点赞 | ✔ 热门评论 |
| TikTok | 视频封面或图集、作者、播放/点赞/评论/分享/收藏 | ✔ 按点赞排序 |
| Instagram | 帖子和 Reels 的作者、配文、图片（通过公开的嵌入修复站读取） | ✘ 实测拿不到，见下方说明 |
| X / Twitter | 正文、作者、配图、引用帖、回复/转帖/喜欢/浏览 | ✔ 需填 `x_cookie` + 浏览器服务（较慢，最多等 25 秒，可调） |
| GitHub | 仓库、Issue、PR、用户主页 | ✔ Issue/PR 评论（填 `github_token` 免限流） |
| Bluesky | 正文、作者、配图、互动数 | ✔ 按点赞排序的回复 |
| pixiv | 标题、作者、标签、数据（平台标记为分级的不显示图片） | ✔ |
| Reddit | 标题、作者、版块 | ✘ 机房 IP 会被拦（`hot.json` 直接 403），配 `proxy` 后正常 |
| Steam | 名称、简介、价格、类型、推荐数；填 `steam_api_key` 才有当前在线人数 | ✔ 热门评测（含推荐与否、游玩时长、赞数） |
| 维基百科 | 词条摘要、配图 | — |
| 维基文库 | 作品名、作者、朝代、出处、开头正文；整部书的目录页显示章节列表 | — |
| Dailymotion | 标题、作者、封面、时长、播放/点赞、标签 | — |
| niconico | 标题、作者、封面、时长、播放/评论/收藏、标签 | — |
| Spotify / Vimeo / SoundCloud | 标题、作者、封面 | — |
| Twitch | 频道资料、是否在播、直播标题、观众数、分类、16:9 预览图；切片也行（走公开 GQL，不受登录墙影响） | — |
| Threads / Facebook | 页面元信息（要登录的页面不发） | — |

通用网页也可自动识别（含无协议域名和中文域名），在 platforms.web 中关闭；`/预览 链接` 可手动调用。web_blocklist 对自动和手动入口均生效，也包括已记住的历史链接。

## 📦 安装 | Installation

从本仓库的 [v3.0.2 发行页](https://github.com/Enderyouling/astrbot_plugin_link_ex/releases/tag/v3.0.2) 下载源码 ZIP，或在 AstrBot 中使用本仓库地址安装。默认维护分支为 `EX-main`。

插件显示名为 **外链解析 Ex**，插件 ID 与仓库名统一为 `astrbot_plugin_link_ex`。从原版切换前请备份配置与数据，并停用原版，避免相同命令和自动预览重复触发。新 ID 使用独立配置与数据目录，不会自动导入旧配置；请在 WebUI 重新填写或导入原配置。需要保留自定义词表和群图片开关时，在停用两版后，将旧目录 `data/plugin_data/astrbot_plugin_link_preview/` 中的自定义词表及 `image_switch.json` 复制到新目录 `data/plugin_data/astrbot_plugin_link_ex/`；目标已有文件时先备份并核对，不要直接覆盖。

将插件目录放入：

```
AstrBot/data/plugins/astrbot_plugin_link_ex
```

重启 AstrBot 后即可在 WebUI 中看到插件。

### 🖼️ 渲染：走 AstrBot 的文转图

卡片不再由插件自己开浏览器截图，而是把 HTML 交给 AstrBot 的 `html_render`。所以：

- 插件**不依赖 Playwright**，`requirements.txt` 里没有它
- 不用装 Chromium、不用 `playwright install-deps`、不用 Docker
- 代价：渲染质量与可用性取决于文转图服务

> [!IMPORTANT]
> `t2i_strategy` 必须是 `remote`（默认值）。配成 `local` 时 AstrBot 会直接抛 `NotImplementedError`——本地策略只能画 Markdown，画不了 HTML，卡片会发不出去。

**服务不稳时**：官方端点 `t2i.soulter.top` 偶尔返回 503。插件对每次渲染重试 3 次（间隔 1.2 / 2.4 秒），仍失败就记一条 warning，这条链接不出卡片，其他链接不受影响。AstrBot 支持配置多个 t2i 端点，想自己托管改那里即可。

#### 出图质量

远端服务的视口固定 **800×720、DPR 1**，且忽略 `device_scale_factor`，所以做了三件事让效果接近本机渲染：

| 问题 | 处理 |
|---|---|
| 右侧一大片空白 | 模板加了 `body.t2i` 版式，卡片铺满 800 宽（原来 640） |
| 矮卡片下方留白 | 视口高度不会小于 720，出图后用 Pillow 按背景色裁掉多余边距 |
| 数字英文被撑成「2 0 2 6」 | 字体栈把 `DejaVu Sans` / `sans-serif` 排在 CJK 字体之前。远端机器没装 Noto CJK 时会退到 HanaMin 这类字体，它们的拉丁字形是全角的 |

超长卡片不会被截断——高度会随内容延伸。

> [!NOTE]
> 唯一的差距是分辨率：现在是 800 宽（裁完约 780），原来本机渲染是 1200 宽（600 CSS px × DPR 2）。文字像素高度相同，整图略小一点。

#### 字体

渲染机的字体五花八门：有的没装中文字体，有的只有宋体，有的缺 DejaVu，同一张卡在不同机器上粗细、字形都不一样，深色卡片上还容易「发虚」。

所以卡片**自带字体**：

- `fonts/` 里是 Noto Sans SC 的 400 / 700 两个字重（GB2312 全量 + 拉丁 + 标点，共约 2MB）
- 渲染时按这张卡实际用到的字符**再裁一次**，内联进 HTML，通常只有 10～30 KB
- 没装 `fonttools` 时退回整份字体，效果一样，只是请求大一点
- 顺带去掉了 `-webkit-font-smoothing: antialiased`，它会让深色卡片上的白字变细

## ⚙️ 配置 | Configuration

插件使用 `_conf_schema.json` 定义配置，入口：

```
AstrBot WebUI -> 插件 -> 插件配置
```

### 🔧 基础

| 配置项 | 说明 |
|--------|------|
| `enabled` | 启用自动识别 |
| `platforms` | 分平台开关，默认全开 |
| `max_links_per_message` | 一条消息最多预览几个链接，默认 `2` |
| `dedupe_seconds` | 同一链接在同一个群里多久内不重复预览，默认 `30` |
| `private_enabled` | 私聊里也自动识别，默认关 |
| `group_whitelist` / `group_blacklist` | 只在这些群 / 不在这些群自动识别 |

### 🎨 卡片外观

| 配置项 | 说明 |
|--------|------|
| `theme` | 卡片主题：`dark` / `light` |
| `text_length` | 正文最多显示多少字，默认 `420` |
| `show_images` | 显示配图和封面 |
| `blur_sensitive` | 平台标记为敏感的图片自动模糊 |
| `comment_count` | 卡片里显示几条热门评论，默认 `3`，最大 `10` |
| `translate_target` | 翻译目标语言，默认 `简体中文` |
| `translate_auto` | 自动翻译非中文帖子，**默认开**。每张外语卡片多一次模型调用，出图慢几秒；想省调用就关掉 |

### 🌐 网络与抓取

| 配置项 | 说明 |
|--------|------|
| `proxy` | 访问国外平台用的代理，如 `http://127.0.0.1:7890` |
| `github_token` | GitHub Token（可选），提高 API 限额 |
| `steam_api_key` | Steam Web API Key（可选），填了才显示 Steam 当前在线人数；评测不需要 Key |
| `fetch_timeout` | 抓取超时（秒），默认 `12` |
| `render_timeout` | 渲染超时（秒），默认 `25` |

### 🐦 X 评论

| 配置项 | 说明 |
|--------|------|
| `x_comments` | X 帖子也抓评论 |
| `x_comments_wait` | X 评论等待秒数，默认 `25`。**这个值同时决定出卡速度**：调小更快但可能抓不全，调大更完整但更慢（8=快，15=折中，25=完整）|
| `x_browser_url` / `x_browser_token` | 浏览器服务地址和 Token（抓取 X 评论用） |
| `x_cookie` | 从自己浏览器复制的 X Cookie，抓评论必需 |

X 卡片本身走公开接口，不需要登录；只有「热门评论」需要登录态。插件不替你登录 X，而是**用你自己浏览器里的 Cookie**——比在服务器上跑浏览器自动化稳，也不容易触发风控封 IP。

抓取后端随插件放在 [`x-browser-service/`](x-browser-service/README.md)，起一个容器即可：

```bash
cd x-browser-service
cp .env.example .env      # 填 Token，确认 Cookie 目录
docker compose up -d      # 本地构建，约 10 分钟（主要花在装 chromium）
```

不想等第一次构建的话，在 `.env` 里加 `XBROWSER_IMAGE=ghcr.io/endermanmyr/astrbot-xbrowser:latest` 就能直接拉预构建镜像。`ghcr.io` 在部分网络下不可达，连不上就用默认的本地构建。

再把地址和 Token 填进 `x_browser_url` / `x_browser_token`。不部署也不影响其他平台，只是 X 卡片没有评论。

> [!TIP]
> 不想用 Docker 也能跑：它就是普通的 aiohttp + Playwright 服务，可以用 systemd 裸机部署，详见 [x-browser-service/README.md](x-browser-service/README.md#不用-docker裸机--systemd)。

#### 🔑 Cookie 怎么来：从哪里拿

**前提：在电脑上操作**（手机浏览器看不到开发者工具），并且这个浏览器**已经登录了 x.com**。无痕/隐私窗口不行，关掉就没了。

1. 打开 <https://x.com>，确认右上角是你自己的头像，说明已登录
2. 按 `F12` 打开开发者工具（macOS 是 `Option + Command + I`）
3. 切到 **Application** 标签
   - Chrome / Edge：`Application`
   - Firefox：`Storage` → `Cookies`
   - Safari：先「设置 → 高级 → 显示网页开发者功能」，再按 `Option + Command + I`
4. 左侧展开 **Cookies** → 点 `https://x.com`
5. 在列表上方的过滤框输入 `auth_token`，找到这一行，双击 **Value** 列复制
   - 值是 40 位十六进制，形如 `1a2b3c4d5e6f7a8b9c0d1e2f3a4b5c6d7e8f9a0b`
6. 过滤框改成 `ct0`，同样复制它的 Value
   - **这个是 160 位，很长，别复制漏了**
7. 把两个值拼成一行：

   ```
   auth_token=1a2b3c4d5e6f7a8b9c0d1e2f3a4b5c6d7e8f9a0b; ct0=9f8e7d6c5b4a...
   ```

8. 粘进插件配置的 `x_cookie`，保存 → 在 WebUI 里重载插件（或重启 AstrBot）

> [!TIP]
> 只粘两条值也行，不用写 `auth_token=` 前缀，用分号或空格隔开即可。插件会自动识别。

**怎么确认成功**：群里发一个 X 帖子链接，卡片下面出现「热门评论」就说明 Cookie 生效了。没出来的话看日志有没有 `[LinkPreview] 已写入手填的 X Cookie`。

**Cookie 会过期**：改密码、在别处退出登录、太久不用都可能失效。表现是评论突然变空，重新按上面步骤复制一次即可。

### 📖 维基全文

| 配置项 | 说明 |
|--------|------|
| `full_page_chars` | 每页大约多少字，默认 `3500` |
| `full_max_pages` | 最多发几页，默认 `15` |

### 🛡️ 屏蔽

| 配置项 | 说明 |
|--------|------|
| `block_enabled` | 启用敏感词屏蔽 |
| `block_words_file` | 词表文件；留空用插件数据目录下的 `political.txt` |
| `block_words` | 额外屏蔽词 |
| `block_mode` | 命中后怎么处理：`整条不发` / `打码后发送` |
| `block_outgoing` | 机器人自己的回复也检查，默认开 |
| `restricted_enabled` | 启用分级过滤 |
| `restricted_block_flagged` | 平台标记为分级内容的也整条不发 |
| `restricted_words_file` | 分级词表；留空用插件数据目录下的 `restricted.txt` |
| `restricted_outgoing` | 机器人自己的回复也查分级词，默认关 |
| `block_notice` | 被拦截或发不出去时在群里提醒 |

## 📌 使用说明 | Usage

### 💬 指令

| 指令 | 别名 | 说明 |
|------|------|------|
| `/预览 链接` | `/preview` | 手动预览任意网页，不受平台开关限制 |
| `/评论 [链接]` | `/comments`、`/看评论` | 单独看评论（最多 10 条），不带链接时用本群最近预览的那条 |
| `/翻译 [链接]` | `/translate`、`/翻译帖子` | 出一张带译文的卡片（外语帖子自动预览时已带译文，一般不用再发） |
| `/全文 [维基链接]` | `/fulltext`、`/维基全文` | 维基百科词条或维基文库作品全文，分页后合并转发 |
| `/预览图片 [开/关/默认]` | `/previewimg`、`/预览配图` | 管理员切换本群卡片是否显示配图和封面 |
| `/预览帮助` | `/previewhelp` | 查看帮助 |

> [!NOTE]
> `/全文` 的合并转发只有 QQ（OneBot / aiocqhttp）支持，其他平台会逐张发送。每页约 3500 字，最多 15 页，超出部分会提示看原文。

### 🛡️ 敏感词与分级过滤

- 词表默认放在插件数据目录：`data/plugin_data/astrbot_plugin_link_ex/political.txt`，第一次加载时用插件自带的 `sensitive_words.txt` 创建，之后改这个文件即可，改完立即生效
- 从旧版本升级时，如果插件数据目录里还没有词表、而旧位置 `data/sensitive_words/political.txt` 存在，会先复制一份过来再继续；旧文件保留不动
- 想放在别处，把 `block_words_file` 填成绝对路径或相对 AstrBot 工作目录的路径即可
- 自带词表约 150 个政治敏感词（简繁体），刻意避开了「64」「民主」这类会大量误伤的短词
- 中文词去掉空格、间隔号、星号等插字后匹配；英文词按整词匹配
- 正文、标题、作者命中：默认整条不发，也可以设成打码后发送；评论命中只去掉那一条
- 按账号屏蔽：X 帖子作者的简介（和所在地）里带敏感词或分级词，不管这条帖子发的是什么都不预览
- 维基 `/全文` 也做分级检查，词条正文命中分级词整条不发，不会打码后照发；政治敏感词命中时按 `block_mode` 处理
- 机器人自己的回复默认不查分级词（`restricted_outgoing`）

### 📤 发不出去时

- 命中屏蔽词：链接卡片、`/全文` 和机器人自己的回复都会在群里提醒一句（`block_notice`，默认开）
- 卡片被 QQ 拒收（比如图片没过 QQ 审核）：改发一句文字提醒

## 🧭 网络代理建议 | Network Proxy

插件要访问的多数平台在境外，服务器直连大概率超时。推荐给 Clash 加一条规则，或在配置里直接填 `proxy`：

```yaml
mixin:
  mode: rule

  proxy-groups:
    - name: LINK-PREVIEW
      type: select
      proxies:
        - HK   # ← 改成你的节点
        - DIRECT

  rules:
    - DOMAIN-SUFFIX,youtube.com,LINK-PREVIEW
    - DOMAIN-SUFFIX,ytimg.com,LINK-PREVIEW
    - DOMAIN-SUFFIX,tiktokcdn.com,LINK-PREVIEW
    - DOMAIN-SUFFIX,twitter.com,LINK-PREVIEW
    - DOMAIN-SUFFIX,x.com,LINK-PREVIEW
    - DOMAIN-SUFFIX,twimg.com,LINK-PREVIEW
    - DOMAIN-SUFFIX,bsky.app,LINK-PREVIEW
    - DOMAIN-SUFFIX,pixiv.net,LINK-PREVIEW
    - DOMAIN-SUFFIX,pximg.net,LINK-PREVIEW
    - DOMAIN-SUFFIX,dailymotion.com,LINK-PREVIEW
    - DOMAIN-SUFFIX,niconico.com,LINK-PREVIEW
    - DOMAIN-SUFFIX,githubusercontent.com,LINK-PREVIEW

    - MATCH,DIRECT
```

> [!TIP]
> 维基百科、维基文库、GitHub、Steam 国内多数网络可直连，不必走代理；只把上面这些走代理能省不少流量。

## 🧪 开发验证 | Development

`fetchers.py` 和 `render.py` 的日志走 `from astrbot.api import logger`，所以要在**装了 AstrBot 的环境**里跑——最省事的是进 AstrBot 容器：

```bash
docker exec -it astrbot bash
cd /AstrBot/data/plugins
```

抓取一张卡片，把 HTML 存下来看看排版：

```python
import asyncio, fetchers, render

async def main():
    async with fetchers.make_client(None, 15) as c:
        card = await fetchers.fetch(c, "github",
            "https://github.com/EndermanMYR/astrbot_plugin_link_preview", comments=3)
        card = await render.prepare(c, card)
    open("card.html", "w", encoding="utf-8").write(render.build_html(card, "dark"))

asyncio.run(main())
```

`build_html(card, theme, t2i=True)` 出来的就是交给文转图的完整 HTML，用浏览器打开就能看到最终版式（`t2i=False` 是原来的 640 宽版式）。`render.crop_image(path)` 用来裁掉远端服务留下的空白边距，可以单独拿一张图试。

### 单元测试

测试用标准库 `unittest`，不联网、不需要 AstrBot（`tests/_stub.py` 会在进程内伪造 `astrbot.api.logger`）：

```bash
python -m unittest discover -s tests -t . -v
```

覆盖的是容易悄悄坏掉的部分：链接识别（29 个平台及通用网页）、数字/时长/时间格式化、OpenGraph 解析、全文分页、词表匹配（含插字写法）、配置项与抓取器是否对齐、发布包是否缺文件、模板字体栈顺序、裁边逻辑。CI 在 `.github/workflows/ci.yml`，推送 EX 分支、main 或版本标签时执行。


## 维护者与贡献 | Maintainers & Contributions

- **EX 版维护与扩展：[@Enderyouling](https://github.com/Enderyouling)**，负责国内平台预览、安全加固、EX 版文档与发行维护。
- **原作：ネコの先生 / [@EndermanMYR](https://github.com/EndermanMYR)**，提供 v2.5.0 的插件主体、原有平台解析与渲染实现。
- EX 版在 AI 辅助下完成修改；保留原仓库提交历史与其他贡献记录。GitHub Contributors 由提交记录自动统计。
- 功能与安全修改已提交原作 [PR #2](https://github.com/EndermanMYR/astrbot_plugin_link_preview/pull/2)；此处的 EX 品牌与维护信息独立维护。

## ❤️ 致谢 | Credits

- 卡片渲染基于 AstrBot 自带的文转图（`html_render`）
- 内置字体 [Noto Sans SC](https://fonts.google.com/noto/specimen/Noto+Sans+SC)（SIL OFL 1.1，见 `fonts/OFL.txt`）
- 抓取基于 [httpx](https://www.python-httpx.org/)，模板基于 [Jinja2](https://jinja.palletsprojects.com/)

## ⚠️ 免责声明 | Disclaimer

> [!WARNING]
> 本插件会从第三方平台抓取内容并转发到群聊。**是否合规使用由部署者自行判断并承担全部责任。** 内置的敏感词表与分级词表只是辅助手段，**不构成内容审核，也不保证覆盖任何一类敏感内容**。

### 一、屏蔽词表不保证完整

插件自带约 150 个政治敏感词和一份分级词表，是作者按个人经验整理的，**覆盖面必然有限**。实际内容里存在大量词表无法覆盖的形态：

- 谐音、缩写、拼音首字母、外语、方言、拆字
- 图片、视频、表情包里的文字（词表只检查文本字段）
- 平台未标记的分级内容（判定部分依赖平台标记）
- 新出现的敏感表述，词表更新必然滞后

因此**不能把本插件当作内容审核工具**，更不应据此认为「没被拦截就是安全的」。词表支持自行修改和追加，建议按自己的使用场景维护。

### 二、内容来自第三方

卡片上的标题、正文、作者、配图、评论均抓取自 YouTube、TikTok、X、pixiv 等平台，由第三方用户生成。作者无法控制这些内容，也不对其真实性、准确性、合法性、是否侵犯第三方权利作任何担保。

### 三、账号风险由使用者承担

使用本插件可能导致账号被平台限制、封禁，或导致机器人无法继续使用，包括但不限于：

| 情形 | 可能的后果 |
|---|---|
| 抓取到的内容违反平台服务条款或当地法律法规 | 机器人账号被封禁、群聊被限制 |
| 词表未覆盖的敏感内容被转发到群聊 | 群聊被封、账号被处罚 |
| 高频抓取触发目标平台风控或限流 | X / TikTok 等账号被临时或永久限制 |
| 机器人所在平台对转发内容进行审核处置 | 消息被拦截、账号被降权 |

**因使用本插件造成的账号封禁、限流、内容删除、服务中断、数据丢失，或任何其他直接、间接损失，作者不承担任何责任。**

### 四、部署者的合规义务

部署者应自行确认所在地区法律法规、机器人平台服务条款、目标平台使用条款是否允许此类抓取与转发行为。建议：

- 按自身场景维护词表，不要直接依赖默认词表
- 优先在私密群或小范围使用，避免公开传播抓取内容
- 遵守目标平台的 robots 与 API 条款，控制请求频率
- 涉及分级内容的场景，确保使用者均已成年
- 定期检查机器人所在平台的规则变化

### 五、接口与可用性

插件依赖第三方公开接口与网页结构，随时可能因对方改版、限流、封锁而失效。作者不保证插件持续可用，也不对因此产生的任何后果负责。

### 六、许可与担保

代码以 MIT 许可发布，意为「按原样提供」（AS IS），**不附带任何明示或暗示的担保**，包括但不限于适销性、特定用途适用性和不侵权担保。详见 [LICENSE](LICENSE)。

## 📜 许可证 | License

本项目基于 [MIT License](LICENSE) 发布，可自由使用、修改和分发，保留版权声明即可。

[![License](https://img.shields.io/badge/License-MIT-yellow)](LICENSE)
