# Changelog

本项目遵循 [Semantic Versioning](https://semver.org/lang/zh-CN/)。

## [v0.1.3] - 2026-03-06

### Added
- 新增独立的分析模型配置项 `llm_analysis_provider_id`，可在配置页单独指定 WebUI 分析和 `/作息 分析` 使用的模型供应商。
- 新增 WebUI 前端日志上报接口，关键请求和错误会同步输出到 AstrBot 终端，便于排查线上问题。

### Fixed
- 修复 WebUI 个性化分析请求路径错误：前端由错误的 `/api/analyze` 改为后端实际提供的 `/api/analysis`。
- 修复 WebUI 分析结果字段读取错误：前端改为消费后端真实返回的 `analysis_text`。
- 明确区分“回复模型”和“分析模型”的配置与解析逻辑，避免 WebUI 分析隐式落到不明确的 provider 上。

## [v0.1.2] - 2026-03-06

### Changed

- 调整独立 WebUI 默认配置：新安装时默认关闭，避免因未配置登录令牌导致插件首次加载失败。
- 重写独立 WebUI 相关配置项说明，使配置页文案与实际行为保持一致。

### Fixed

- 修复“独立 WebUI 开关开启但登录令牌为空”时的配置歧义：插件读取配置时会自动将开关回写为关闭并持久化，配置页重新打开后可看到同步后的关闭状态。
- 强化独立 WebUI 启动保护：当用户未配置登录令牌时，不再尝试启动独立 WebUI，也不会影响插件主功能加载。

## [v0.1.1] - 2026-03-05

### Fixed

- 修复插件独立 WebUI 在 AstrBot 重启后偶发端口未释放的问题：当检测到端口被占用时，会尝试通知旧实例优雅关停并等待端口回收后再启动。
- 强化独立 WebUI 停止流程：停止超时会记录告警并执行任务取消，避免服务残留导致端口长期占用。
- 修复排行榜 `metric` 参数“可传但不生效”的语义问题：当前仅支持 `activity`，非法值返回明确错误。
- 修复 SQLite 单连接在并发场景下的事务串扰风险：统一 DB 访问锁，确保事务边界隔离。

### Security

- 强化插件 Web API 显式鉴权（`/api/plug/*`）：未通过宿主鉴权时统一返回 `401 unauthorized`。
- 强化独立 WebUI 登录安全：新增登录失败限流与短期锁定策略，缓解暴力尝试风险。
- 强化 Cookie `Secure` 判定：支持 `X-Forwarded-Proto`，改善反向代理 TLS 终止场景下的安全性。
- 收敛 CORS 策略：从宽松策略改为受控来源集合。

### Performance

- 将事件快照刷新调整为后台任务，降低消息主路径阻塞概率，改善高频群聊场景响应稳定性。

## [v0.1.0] - 2026-03-04

### Added

- 新增早安/晚安正则识别能力，支持多规则与大小写/宽度归一化处理。
- 新增睡眠会话模型（`open / closed / abandoned`）与事件日志存储。
- 新增单边事件策略：
  - 孤立早安（`warn_only`）
  - 自动补全闭合会话（`create_closed_session`）
- 新增重复晚安策略：`ignore / update_open / create_new`。
- 新增事件回复双模式：`static / llm`，并支持 LLM 失败回退。
- 新增命令能力：`状态`、`看板`、`统计`、`分析`、`会话`、`修正`。
- 新增 LLM Tool：`oyasumi_sleep_stats`、`oyasumi_sleep_analysis`。
- 新增独立 WebUI 服务（插件自带端口），包含登录页与会话 Cookie 鉴权。
- 新增 WebUI 群聊看板接口：
  - `overview`
  - `leaderboard`
  - `user_insight`
- 新增看板可视化能力：
  - 群聊 KPI
  - 入睡/起床热力图
  - 群聊趋势图
  - Top10 活跃榜与用户下钻
  - 会话筛选、LLM 分析、Snapshot 展示

### Changed

- WebUI 布局升级为面板化结构：
  - 桌面端固定侧边栏 + 工作区
  - 移动端抽屉导航
- 看板默认视角调整为公共群聊优先，不再以单用户为首页主入口。
- 时间范围交互统一为预设区间 + 自定义区间，并支持 15 秒自动刷新。

### Security

- 独立 WebUI 全部 API 统一鉴权保护（未登录返回 `401`）。
- 登录后采用 HttpOnly Cookie 会话，支持主动退出。

### Docs

- 完成 README 定稿，文档与当前功能、接口和 WebUI 行为保持一致。
- 新增 CHANGELOG，记录版本变化。
