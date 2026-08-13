# astrbot_plugin_91tool

数字站(91porn)的 AstrBot 插件，采用 **Tool-first 架构**：业务功能通过 LLM 工具提供，AI 拿到结构化数据并智能编排，而不是指令式。对接 QQ / 微信 / Telegram 等多平台。

## 功能一览

- **列表查询**：分类 / 搜索 / 筛选（时长、HD），结果以长图发送
- **视频详情**：文字详情（不下载、不进详情页）
- **预览生成**：MP4 / GIF 预览（打码 / 无码），FFmpeg 采样
- **原片发送**：可信校验下载，超上限自动压缩
- **持久归档**：原片 / 封面 / 无码预览存到 NAS（开关）
- **多平台发送**：图片 / 视频 / 文件通道，发送前大小检查

## 安装

1. 把插件目录放到 AstrBot 的 `plugins/`（或 `git clone` 进去）
2. 装 Python 依赖：`pip install -r requirements.txt`（aiohttp / beautifulsoup4 / yarl / Pillow）
3. **系统依赖**：`ffmpeg` + `ffprobe`（视频校验、预览采样、压缩都靠它）
   - Debian/Ubuntu：`apt install ffmpeg`
   - docker 部署：容器内也得装 ffmpeg
4. 重启 AstrBot 加载插件，首次运行自动建立 Cookie

> docker 用户想用归档：把宿主 NAS 目录映射进容器，如 `-v /你的/nas:/archive`，再到 WebUI 开 `archive_enabled`。

## 配置（AstrBot WebUI）

| 配置项 | 默认 | 说明 |
|---|---|---|
| `image_max_bytes` / `video_max_bytes` | 9961472 (9.5MB) | 图片/视频发送上限，超了拒绝或压缩。用 `/91probe` 探测后调 |
| `default_send_level` | mosaic_only | 默认只发打码版；要无码让 AI 传 `uncensored=true` |
| `archive_enabled` | false | 开启后原片/封面/无码预览自动存 NAS |
| `archive_dir` | /archive/91 | 归档目录（映射 NAS），按 `日期/标题_video_id/` 组织 |
| `proxy` | 空 | HTTP/HTTPS 代理 |
| `video_cache_retention_hours` | 24 | 临时媒体缓存保留时长（归档不受影响） |

其余（抓取间隔、Cookie 引导、预览参数等）都有合理默认，一般不用动。

## 使用：对 AI 说

| 你说 | AI 会 |
|---|---|
| 看数字站热门 / 看 rf 分类 | 发一页长图 |
| 本月最热前 50 条 | 翻页收集 → 一张 50 条长图 |
| 第 3 条详情 / 链接 | 文字回复详情 |
| 发第 2 条预览 | 生成打码 MP4 预览并发 |
| 无和谐 gif 第 5 条 | 生成无码 GIF 并发 |
| 放第 4 条（完整原片） | 校验下载原片并发（超限自动压缩） |
| 帮我爬 / 保存第 N 条 | 下载原片并归档到 NAS（不发消息） |
| 搜一下 XX | 搜索结果长图 |

可叠加筛选："只要 HD 的""10 分钟以上的""第 2 页"——AI 组合条件。

> "数字站"和"91"都指本数据源，AI 都认；回复也用"数字站"措辞。

## 管理命令

| 命令 | 作用 |
|---|---|
| `/91probe [image\|video\|file]` | 探测当前会话平台的发送通道与大小上限 |
| `/91tool_status` | 查看缓存概况（结果数 / 媒体占用） |
| `/91tool_clear` | 清理过期缓存 |
| `/91tool_help` | 帮助 |

## 特性

- **Tool-first**：`core/` 业务层零 AstrBot 依赖，7+ 个 LLM 工具 + 编排工具，AI 智能组合
- **可信校验**：列表 source_id 净化 + 详情页 ID 匹配刷新 + 下载时长双校验，防错位 / 诱饵
- **详情页底线**：只有获取原片才进详情页，查询 / 详情 / 长图只用列表数据
- **媒体缓存共享**：原片 / 预览 / GIF 按 video_id 共享同一缓存包
- **发送策略**：默认打码、容量检查、视频超限自动压缩、逐条发送（QQ 一条一附件）
- **持久归档**：NAS 存原片 / 封面 / 无码预览，按 `日期/标题/` 组织，不被清理

## 注意

- **QQ/微信约 10MB 硬限**：完整原片（通常更大）会自动压缩到 9.5MB 内（长片画质降）；超长（>8 分钟）压缩也压不进时建议发预览。Telegram 等可走文件通道发大文件
- **ffmpeg 必需**：预览生成、视频校验、压缩都依赖系统 ffmpeg/ffprobe
- **首次查询可能慢**：Cookie 引导（几次请求建立会话）

## 开发

```bash
pip install -r requirements.txt
pytest -q
```

`core/` 纯业务层（零 AstrBot 依赖，可单测）；`tools/` 适配层；`main.py` 是 Star 入口。
