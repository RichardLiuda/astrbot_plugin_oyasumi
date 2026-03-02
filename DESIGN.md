# 晚安作息追踪插件设计文档

## 1. 设计目标

本设计文档用于指导 `astrbot_plugin_oyasumi` 的落地实现，确保以下目标：

- 从数据模型层面解决夜猫子、回笼觉、重复早晚安覆盖问题
- 保证触发稳定：正则命中即执行插件逻辑，不依赖模型“猜测是否调工具”
- 保持实现可维护：模块职责单一、低耦合、可测试
- 支持双回复模式：`static` 与 `llm`，并有失败回退
- 支持 WebUI 实时展示与配置管理

## 2. 总体架构

```text
Incoming Message
    |
    v
Trigger Matcher (regex + normalize)
    |
    v
Event Service (persist sleep_event)
    |
    v
Session Service (state transition + policy)
    |
    +--> Stats Service (incremental/stat query)
    |
    +--> Response Service (static/llm/fallback)
    |
    v
Reply to User + Emit UI Realtime Event
```

## 3. 模块划分

建议按以下模块拆分：

- `main.py`
- 插件入口、事件订阅、指令注册、依赖注入
- `domain/trigger_matcher.py`
- 文本归一化、正则编译与命中判定
- `domain/session_service.py`
- 睡眠会话状态机与策略执行
- `domain/event_service.py`
- 事件落库与审计字段填充
- `domain/response_service.py`
- 固定回复模板渲染、大模型调用与回退
- `domain/stats_service.py`
- 统计计算与报表数据组装
- `repository/*.py`
- 数据访问层（SQL）
- `webui/*`
- 页面与实时展示

说明：

- `main.py` 不直接写业务 SQL，只编排服务调用
- `session_service` 不直接操作聊天回复，只返回结构化结果

## 4. AstrBot 规范对齐

### 4.1 插件目录与必要文件

插件根目录至少包含：

- `main.py`：插件入口
- `metadata.yaml`：插件元信息
- `_conf_schema.json`：配置定义（用于配置页）
- `README.md`：说明文档
- `requirements.txt`：第三方依赖（按需）

### 4.2 注册与生命周期

- 插件类需继承 `Star` 并通过 `@register(...)` 注册
- 支持实现：
- `async def initialize(self)`：初始化（建库、预编译正则、加载缓存）
- `async def terminate(self)`：资源释放（关闭数据库连接、清理任务）

### 4.3 配置机制

- 配置定义在 `_conf_schema.json`
- 运行时通过 `__init__(..., config: AstrBotConfig)` 注入
- 配置持久化位置由框架管理：`data/config/<plugin_name>_config.json`
- 运行期变更配置后调用 `config.save_config()` 持久化

### 4.4 存储路径规范

- 业务数据不得写入插件源码目录
- 数据库存放到插件数据目录，例如：
- 路径处理统一使用 `pathlib.Path`
- 优先使用 `astrbot.core.utils.path_utils` 获取数据目录/临时目录
- `StarTools.get_data_dir("astrbot_plugin_oyasumi") / "oyasumi.db"`
- 大文件或导出文件放 `data/plugin_data/<plugin_name>/`

### 4.5 事件处理与回复规范

- “正则触发早晚安”主路径建议使用消息事件监听（如 `@filter.event_message_type(...)`）+ 内部正则匹配
- 统计与分析能力可额外通过 `@llm_tool` 暴露给大模型调用
- 消息回复走 AstrBot 事件返回接口（如 `yield event.plain_result(...)`）

### 4.6 依赖与日志规范

- 网络请求优先异步库（如 `httpx` / `aiohttp`）
- 统一使用 AstrBot 的 `logger`
- 提交前执行格式化与静态检查（如 `ruff format`、`ruff check`）

### 4.7 元数据规范

- `metadata.yaml` 必填：`name`、`desc`、`version`、`author`、`repo`
- `name` 建议以 `astrbot_plugin_` 前缀命名
- 可选增强字段：`display_name`、`support_platforms`、`astrbot_version`

## 5. 关键设计决策

### 5.1 会话优先，不按天唯一

- 不使用 `user_id + date` 唯一键
- 用 `sleep_session.id` 标识真实睡眠过程
- 统计日期从会话时间推导，不作为主键语义

### 5.2 事件与会话分离

- `sleep_event` 记录“发生了什么”
- `sleep_session` 记录“当前状态是什么”
- 即使策略忽略某次事件，也要保留事件审计记录

### 5.3 交易边界清晰

一次触发（早安/晚安）应在单事务中完成：

1. 写事件
2. 变更会话
3. 写关联关系/审计

失败则回滚，避免“事件有了，会话没变”。

## 6. 数据库设计（SQLite）

## 6.1 表结构

```sql
CREATE TABLE IF NOT EXISTS sleep_session (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL,
    sleep_time DATETIME,
    wake_time DATETIME,
    status TEXT NOT NULL CHECK(status IN ('open', 'closed', 'abandoned')),
    source TEXT NOT NULL CHECK(source IN ('regex', 'manual_edit', 'api', 'auto_fill')),
    is_auto_filled INTEGER NOT NULL DEFAULT 0,
    auto_fill_reason TEXT,
    created_at DATETIME NOT NULL DEFAULT (datetime('now', 'localtime')),
    updated_at DATETIME NOT NULL DEFAULT (datetime('now', 'localtime'))
);

CREATE TABLE IF NOT EXISTS sleep_event (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL,
    event_type TEXT NOT NULL CHECK(event_type IN ('good_morning', 'good_night', 'manual_edit')),
    event_time DATETIME NOT NULL,
    matched_pattern TEXT,
    raw_message TEXT,
    session_id INTEGER,
    metadata_json TEXT,
    created_at DATETIME NOT NULL DEFAULT (datetime('now', 'localtime')),
    FOREIGN KEY(session_id) REFERENCES sleep_session(id)
);

CREATE INDEX IF NOT EXISTS idx_sleep_session_user_status
ON sleep_session(user_id, status);

CREATE INDEX IF NOT EXISTS idx_sleep_session_user_sleep_time
ON sleep_session(user_id, sleep_time);

CREATE INDEX IF NOT EXISTS idx_sleep_event_user_time
ON sleep_event(user_id, event_time);
```

## 6.2 约束建议

- 同一用户允许多个 `open` 会话，但默认策略尽量避免产生
- `wake_time < sleep_time` 的记录在写入时拒绝或标记异常
- `status='closed'` 时要求 `sleep_time` 与 `wake_time` 非空（应用层保障）

## 7. 状态机设计

## 7.1 会话状态

- `open`：已记录入睡，待记录醒来
- `closed`：已闭合，可参与时长统计
- `abandoned`：超时或人工废弃，不参与有效时长

## 7.2 事件流转规则（核心）

### 晚安事件 `good_night`

1. 查询用户最近 `open` 会话
2. 若不存在：创建新 `open` 会话（`sleep_time=event_time`）
3. 若存在：按 `duplicate_night_policy` 执行

`duplicate_night_policy`：

- `ignore`：不改会话，仅记录事件
- `update_open`：更新该 `open` 会话的 `sleep_time=event_time`
- `create_new`：保留旧 `open`，再创建新 `open`（高风险策略）

### 早安事件 `good_morning`

1. 查询用户最近 `open` 会话（按 `sleep_time DESC`）
2. 若存在：将其 `wake_time=event_time` 并置 `status='closed'`
3. 若不存在：按 `orphan_morning_policy` 执行

`orphan_morning_policy`：

- `warn_only`：记录孤立早安事件，回复提示补录
- `create_closed_session`：自动补全会话

自动补全逻辑：

- `sleep_time = event_time - auto_fill_default_hours`
- `wake_time = event_time`
- `status = 'closed'`
- `source = 'auto_fill'`
- `is_auto_filled = 1`

## 7.3 仅早安/仅晚安处理落地

- 仅晚安：累积 `open` 会话；统计展示“未闭合数”
- 仅早安：生成孤立事件或自动补全会话；均需显式标识

## 8. 统计设计

## 8.1 统计口径

- 有效睡眠时长仅统计 `status='closed'` 且 `wake_time >= sleep_time`
- `open` 与 `abandoned` 不进入有效时长
- `auto_fill` 会话默认计入，但在前端可开关“包含自动补全”

## 8.2 核心指标

- `total_sleep_minutes`
- `avg_sleep_minutes`
- `earliest_sleep_time`
- `latest_sleep_time`
- `earliest_wake_time`
- `latest_wake_time`
- `closed_session_count`
- `open_session_count`
- `orphan_morning_count`

## 8.3 日期归属规则

函数：`resolve_stat_date(dt, day_boundary_hour)`

- 当 `dt.hour < day_boundary_hour`，归属前一日
- 否则归属当日

说明：

- 用于统计聚合，不影响会话主键
- `day_boundary_hour` 可配置（建议默认 `6`）

## 9. 回复生成设计

## 9.1 static 模式

- 模板来源：`morning_static_reply`、`night_static_reply`
- 变量替换：`{user_name}`、`{sleep_time}`、`{wake_time}`、`{duration_minutes}`

## 9.2 llm 模式

- 构造上下文：
- 最近会话摘要
- 当前事件类型
- 统计指标摘要
- 使用提示词：
- `llm_prompt_morning`
- `llm_prompt_night`
- `llm_prompt_analysis`

## 9.3 回退策略

- 条件：超时、调用错误、空响应
- 当 `llm_fallback_to_static=true` 时回退静态模板
- 回退行为写日志键：`reply_fallback=true`

## 10. 配置结构设计

### 10.1 配置文件与注入关系

- `_conf_schema.json` 定义字段、类型、默认值、描述
- AstrBot 按 schema 生成/维护运行配置文件
- 插件实现中通过 `config.get("<key>", <default>)` 读取
- 热更新场景可在管理操作后调用 `config.save_config()`

建议 `_conf_schema.json` 对应以下键：

```json
{
  "enabled": true,
  "reply_mode": "static",
  "good_morning_patterns": ["^(早安|早上好).*$"],
  "good_night_patterns": ["^(晚安|睡觉了).*$"],
  "ignore_case": true,
  "normalize_width": true,
  "morning_static_reply": "早安，今天也要元气满满。",
  "night_static_reply": "晚安，祝你好梦。",
  "llm_enabled": false,
  "llm_fallback_to_static": true,
  "llm_prompt_morning": "",
  "llm_prompt_night": "",
  "llm_prompt_analysis": "",
  "day_boundary_hour": 6,
  "duplicate_night_policy": "ignore",
  "orphan_morning_policy": "warn_only",
  "auto_fill_default_hours": 8,
  "allow_user_edit_self": true,
  "admin_only_global_query": true,
  "max_open_session_hours": 20
}
```

## 11. 后端接口设计

## 11.1 插件能力接口

- `record_good_night(event)`
- `record_good_morning(event)`
- `get_sleep_stats(event, start_date, end_date, user_id=None)`
- `update_sleep_session(event, session_id, sleep_time=None, wake_time=None)`
- `generate_sleep_analysis(event, start_date, end_date, user_id=None)`

事件入口建议拆分：

- `on_message(event)`：消息事件监听入口，处理正则早安/晚安
- `@llm_tool` 能力函数：为大模型提供统计查询与分析工具
- 管理命令函数：用于管理员手工修正（可选）

## 11.2 WebUI API（建议）

- `GET /api/oyasumi/dashboard`
- `GET /api/oyasumi/sessions`
- `PATCH /api/oyasumi/sessions/{id}`
- `DELETE /api/oyasumi/sessions/{id}`
- `GET /api/oyasumi/stats`
- `POST /api/oyasumi/analysis`
- `GET /api/oyasumi/config`
- `PUT /api/oyasumi/config`

## 11.3 实时推送事件（建议）

- 频道：`oyasumi_updates`
- 事件：
- `session_created`
- `session_closed`
- `session_updated`
- `event_recorded`
- `config_updated`

## 12. WebUI 设计

## 12.1 页面结构

- Dashboard
- 今日摘要卡
- 未闭合会话提醒
- 趋势图（7天/30天）
- Sessions
- 表格筛选（用户、状态、日期）
- 行内编辑（sleep_time/wake_time/status）
- Config
- 正则与策略配置
- 回复模式与模板
- Analysis
- 统计摘要 + 大模型分析结果

## 12.2 交互细节

- 修改时间字段时即时校验格式
- `wake_time < sleep_time` 禁止提交
- 自动补全会话使用标记徽章（例如“自动补全”）

## 13. 权限与安全

- 默认“仅本人可查”
- `admin_only_global_query=true` 时，非管理员传入 `user_id` 直接拒绝
- 配置修改接口仅管理员可用
- 敏感日志脱敏：`raw_message` 长度截断，避免泄露过多内容

## 14. 可观测性与日志

关键日志字段：

- `user_id`
- `event_type`
- `matched_pattern`
- `policy_branch`
- `session_id`
- `reply_mode`
- `reply_fallback`
- `latency_ms`

建议日志级别：

- `info`：正常触发与状态流转
- `warning`：孤立早安、重复晚安冲突、自动补全
- `error`：数据库错误、配置错误、LLM 调用失败

## 15. 容错与降级

- 正则编译失败：加载配置失败并回退上一次有效配置
- 数据库异常：返回用户友好提示，不暴露堆栈
- LLM 异常：按开关回退 static
- 实时通道异常：WebUI 降级到轮询

## 16. 测试设计

## 16.1 单元测试

- `trigger_matcher`：正则命中/误命中
- `session_service`：所有策略分支覆盖
- `stats_service`：跨日归属与时长计算
- `response_service`：模板渲染和回退

## 16.2 集成测试

- 晚安 -> 早安 正常闭环
- 仅晚安持续多天
- 仅早安持续多天
- 同日多次睡眠（午睡 + 夜间）
- 重复晚安三策略行为一致
- LLM 故障回退

## 16.3 回归基准样例

- `2026-03-02 06:30` 晚安，`2026-03-02 13:00` 早安，应闭合同一 `open` 会话
- 同日两次晚安 + 两次早安，得到两条 `closed` 会话，不互相覆盖

## 17. 迁移方案（如从旧插件迁移）

- 旧表按记录映射为新 `sleep_session`
- 若旧记录缺少 `wake_time`，迁移为 `open`
- 迁移写入 `source='api'` 并在 `metadata_json` 标记 `migrated=true`
- 迁移脚本幂等：重复执行不产生重复会话

## 18. 实施计划

1. Phase 1：数据库与仓储层
2. Phase 2：触发识别 + 会话状态机
3. Phase 3：回复服务与 LLM 回退
4. Phase 4：统计服务与接口
5. Phase 5：WebUI 与实时更新
6. Phase 6：联调、压测、回归

## 19. 开发完成定义（Definition of Done）

- 所有核心策略分支有测试
- 仅早安/仅晚安场景验证通过
- 不再出现按天唯一导致的覆盖问题
- 配置项在 WebUI 可视化编辑并实时生效
- 文档、日志、错误提示与实现一致
