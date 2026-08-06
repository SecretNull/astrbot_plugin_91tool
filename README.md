# astrbot_plugin_91tool

91porn 的 AstrBot 插件，采用 **Tool-first 架构**：业务功能主要通过 LLM Tools 暴露，AI 拿到的是结构化数据，而不是指令式的"当前页序号"。

## 架构分层

- `core/`：纯业务层，**不依赖 astrbot**、消息事件或聊天指令，可独立单测。
- `tools/`：LLM Tool 适配层，薄壳 + 纯函数，把 `core` 能力包成结构化输入输出。
- `main.py`：AstrBot `Star` 入口，装配 `core` 服务、注册 Tool 与管理命令。

## 核心设计

- 查询返回 `result_id`，每个视频有稳定 `video_id`；可用 `(result_id, index)` 或 `video_id` 定位。
- AI 可组合筛选：分类、关键词、最小时长、最大时长、HD、页码、条目数量。
- 原视频 / MP4 预览 / GIF 共享同一媒体缓存包。
- 保留旧项目已验证的可信 video_id 校验与详情页刷新机制。
- Tool 只返回结构化结果，**唯一真正发包的是 `91tool_send_media`**；发送失败可降级为纯文字。

## 提供的 Tool

`91tool_query` / `91tool_video_info` / `91tool_render_list` / `91tool_prepare_video` / `91tool_prepare_preview` / `91tool_send_media` / `91tool_cache_status`

## 开发

```bash
pip install -r requirements.txt
pytest -q
```

## 迁移进度

- [x] 阶段 0：项目骨架
- [x] 阶段 1：结构化查询服务 + `91tool_query`
- [ ] 阶段 2：详情与可信校验
- [ ] 阶段 3：完整视频准备与媒体缓存
- [ ] 阶段 4：预览采样
- [ ] 阶段 5：长图渲染（选定条目）
- [ ] 阶段 6：媒体发送策略（QQ 官方适配器）
- [ ] 阶段 7：缓存状态与管理命令
