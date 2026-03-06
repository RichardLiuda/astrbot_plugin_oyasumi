# 睡了喵~（astrbot_plugin_oyasumi）

基于正则触发的早安/晚安会话追踪插件，面向群聊场景提供：

- 事件识别与会话记录
- 统计查询与修正
- LLM 个性化分析
- 独立 WebUI 看板（含登录鉴权）

## 功能概览

- 早晚安正则触发
  - 通过可配置正则识别 `good_night` / `good_morning`。
- 会话模型
  - 以会话为核心存储睡眠数据：`open / closed / abandoned`。
- 单边事件处理
  - 仅晚安：创建进行中会话。
  - 仅早安：记录孤立事件，或按策略自动补全闭合会话。
- 事件回复模式
  - `reply_mode=static`：固定回复模板。
  - `reply_mode=llm`：早晚安事件回复使用大模型（可失败回退固定回复）。
- 统计与分析
  - 命令行统计、会话列表、WebUI 图表看板。
  - 分析接口与 `/作息 分析` 均支持 LLM 分析输出。
- 独立 WebUI
  - 插件自带端口，无需依赖 AstrBot Dashboard。
  - 登录页 + 会话 Cookie 鉴权。
  - 群聊总览、趋势热力图、Top10 活跃榜、用户下钻、会话筛选。

## 安装

在 AstrBot 根目录执行：

```bash
uv pip install -r data/plugins/astrbot_plugin_oyasumi/requirements.txt
```

## 核心配置项

配置 Schema：`_conf_schema.json`

### 识别与策略

- `enabled`：是否启用插件
- `good_morning_patterns_text`：早安正则（每行一条）
- `good_night_patterns_text`：晚安正则（每行一条）
- `ignore_case`：正则匹配忽略大小写
- `normalize_width`：匹配前执行全角半角归一化
- `duplicate_night_policy`：`ignore / update_open / create_new`
- `orphan_morning_policy`：`warn_only / create_closed_session`
- `auto_fill_default_hours`：自动补全会话默认时长（小时）
- `day_boundary_hour`：统计日界线小时（0-12）

### 回复与 LLM

- `reply_mode`：`static / llm`
- `llm_enabled`：是否启用早晚安事件的 LLM 回复
- `llm_fallback_to_static`：事件 LLM 失败是否回退固定回复
- `llm_provider_id`：可选，指定早晚安回复使用的模型供应商
- `llm_analysis_provider_id`：可选，指定统计分析和 WebUI 分析使用的模型供应商
- `llm_temperature` / `llm_max_tokens` / `llm_timeout_sec`
- `llm_prompt_morning` / `llm_prompt_night` / `llm_prompt_analysis`

### 权限与统计

- `allow_user_edit_self`：是否允许用户修正自己的会话
- `admin_only_global_query`：是否仅管理员可查询他人数据
- `include_auto_fill_in_stats`：统计是否包含自动补全会话
- `max_open_session_hours`：进行中会话超时阈值

### 独立 WebUI

- `standalone_webui_enabled`：是否启用独立 WebUI，默认关闭；若登录令牌为空，保存后会自动恢复为关闭
- `standalone_webui_host`：监听地址（局域网可用 `0.0.0.0`）
- `standalone_webui_port`：监听端口（默认 `6196`）
- `standalone_webui_token`：登录口令；启用独立 WebUI 时必须设置，建议使用强随机值

## 命令

- `/作息`：帮助
- `/作息 状态`
- `/作息 看板 [days]`
- `/作息 统计 [start_date] [end_date] [target_user_id]`
- `/作息 分析 [start_date] [end_date] [target_user_id]`
- `/作息 会话 [limit] [target_user_id]`
- `/作息 修正 <session_id> [sleep_time] [wake_time]`

时间格式：

- `YYYY-MM-DD`
- `YYYY-MM-DDTHH:MM`
- `YYYY-MM-DDTHH:MM:SS`

## 独立 WebUI 使用说明

默认访问地址：

- `http://127.0.0.1:6196/`

鉴权行为：

- 未登录访问根路径会跳转 `/login`。
- 登录成功后由服务端下发 HttpOnly 会话 Cookie。
- 会话失效后接口返回 `401`，前端自动跳转登录页。

当前看板结构（现状）：

- 左侧固定导航（移动端为抽屉）
- 群聊总览 KPI
- 趋势图谱（入睡热力图 / 起床热力图 / 群聊趋势）
- Top10 活跃榜 + 用户下钻
- 用户详情与会话明细筛选
- LLM 分析与 Snapshot 折叠区

刷新策略：

- 15 秒自动轮询 + 手动刷新

## Web API（现状）

以下接口同时支持：

- AstrBot 注册路由：`/oyasumi/*`
- 独立 WebUI 路由：`/api/*`

### 兼容接口

- `GET /users`
- `GET /dashboard`
- `GET /sessions`
- `GET /summary`
- `POST /analysis`
- `GET /snapshot`

### 群聊看板接口

- `GET /overview`
  - 参数：`days` 或 `start_date/end_date`
  - 返回：`kpis`、`daily_series`、`sleep_heatmap`、`wake_heatmap`
- `GET /leaderboard`
  - 参数：`days` 或 `start_date/end_date`、`limit`、`metric(activity)`
  - 返回：活跃榜明细（Top N）
- `GET /user_insight`
  - 参数：`user_id` + 时间范围
  - 返回：用户 KPI、日趋势、时段分布、最近会话

## 事件归属逻辑

- 仅晚安：创建 `open` 会话
- 仅早安：
  - `warn_only`：记录孤立早安事件
  - `create_closed_session`：按默认时长补全会话并闭合
- 重复晚安：按 `duplicate_night_policy` 处理
- 超时进行中会话：超过 `max_open_session_hours` 后标记 `abandoned`

## 数据文件

- 数据库：`data/plugin_data/astrbot_plugin_oyasumi/oyasumi.db`
- WebUI 快照：`data/plugin_data/astrbot_plugin_oyasumi/webui_snapshot.json`

## LLM Tools

- `oyasumi_sleep_stats`
- `oyasumi_sleep_analysis`

## 常见排查

- 配置了 LLM 但事件仍是固定回复：
  - 检查 `reply_mode` 是否为 `llm`
  - 检查 `llm_enabled` 是否为 `true`
  - 检查模型供应商是否可用
- WebUI 无法访问：
  - 检查 `standalone_webui_enabled`、`host`、`port`
  - 若已开启独立 WebUI，确认 `standalone_webui_token` 已设置
  - 检查服务器防火墙与端口放行
- 登录后仍被踢回登录页：
  - 检查 token 是否一致
  - 检查反向代理是否保留 Cookie

## 文档

- 需求文档：`REQUIREMENTS.md`
- 设计文档：`DESIGN.md`
- 更新日志：`CHANGELOG.md`

## 参考

[Soulter/astrbot_plugin_essential: AstrBot Q群插件 | 随机动漫图片、以图搜番、Minecraft服务器、一言、今天吃什么、群早晚安记录、EPIC喜加一。](https://github.com/Soulter/astrbot_plugin_essential)

[SHOOTING-STAR-C/astrbot_plugin_sleep_tracker: 一个基于 AstrBot 的睡眠记录插件，帮助用户记录和分析睡眠作息情况](https://github.com/SHOOTING-STAR-C/astrbot_plugin_sleep_tracker)

## 许可证

[LICENSE](LICENSE)
