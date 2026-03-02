# astrbot_plugin_oyasumi

基于正则触发的早安/晚安会话追踪插件。  
支持固定回复与大模型回复切换，支持统计、修正、分析，并可输出实时快照供 WebUI 展示。

## 功能特性

- 正则触发：通过可配置规则识别“早安/晚安”
- 会话模型：按睡眠会话存储，不再按“每天一条”覆盖
- 单边事件处理：
- 仅晚安：创建进行中会话
- 仅早安：按策略记录孤立事件或自动补全会话
- 回复策略：`static` / `llm` 双模式，可失败回退
- 统计能力：区间统计、看板趋势、会话列表
- 修正能力：支持会话时间手工修正（权限可控）

## 安装与依赖

在 AstrBot 根目录执行：

```bash
uv pip install -r data/plugins/astrbot_plugin_oyasumi/requirements.txt
```

## 核心配置

配置文件由 `_conf_schema.json` 定义，关键项如下：

- `enabled`: 是否启用插件
- `reply_mode`: `static` 或 `llm`
- `good_morning_patterns_text`: 早安正则（每行一条）
- `good_night_patterns_text`: 晚安正则（每行一条）
- `duplicate_night_policy`: `ignore` / `update_open` / `create_new`
- `orphan_morning_policy`: `warn_only` / `create_closed_session`
- `llm_enabled`: 是否启用早晚安事件的大模型回复
- `llm_fallback_to_static`: 早晚安事件的大模型回复失败是否回退固定回复
- `admin_only_global_query`: 是否仅管理员可查询他人数据

## 指令

- `/作息`：查看帮助
- `/作息 状态`：查看插件运行状态
- `/作息 看板 [days]`：查看最近趋势
- `/作息 统计 [start_date] [end_date] [target_user_id]`
- `/作息 分析 [start_date] [end_date] [target_user_id]`
- `/作息 会话 [limit] [target_user_id]`
- `/作息 修正 <session_id> [sleep_time] [wake_time]`

时间格式：

- `YYYY-MM-DD`
- `YYYY-MM-DDTHH:MM`
- `YYYY-MM-DDTHH:MM:SS`

## LLM 工具

- `oyasumi_sleep_stats`
- `oyasumi_sleep_analysis`

## 数据落盘

- 数据库：`data/plugin_data/astrbot_plugin_oyasumi/oyasumi.db`
- 实时快照：`data/plugin_data/astrbot_plugin_oyasumi/webui_snapshot.json`

## 事件处理说明

### 仅晚安（无早安）

- 创建进行中会话（`status=open`）
- 超过 `max_open_session_hours` 会被自动标记为 `abandoned`

### 仅早安（无晚安）

- `warn_only`: 记录孤立早安事件，不自动补全
- `create_closed_session`: 自动补全闭合会话，`source=auto_fill`

### 重复晚安

- `ignore`: 只记录事件，不改会话
- `update_open`: 更新最近进行中会话的入睡时间
- `create_new`: 新建进行中会话

## 开发文档

- 需求文档：`REQUIREMENTS.md`
- 设计文档：`DESIGN.md`


## 独立 WebUI（插件自带端口）

本插件支持不依赖 AstrBot Dashboard 的独立 WebUI 服务。

默认配置：
- `standalone_webui_enabled`: `true`
- `standalone_webui_host`: `127.0.0.1`
- `standalone_webui_port`: `6196`
- `standalone_webui_token`: `""`（为空表示不鉴权）

启动插件后直接访问：
- `http://127.0.0.1:6196/`

如需局域网访问：
- 将 `standalone_webui_host` 改为 `0.0.0.0`
- 然后通过 `http://<你的机器IP>:6196/` 访问
