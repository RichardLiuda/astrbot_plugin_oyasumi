# Changelog

本项目遵循 [Semantic Versioning](https://semver.org/lang/zh-CN/)。

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
