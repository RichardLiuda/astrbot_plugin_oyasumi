const $ = (id) => document.getElementById(id);

const SECTION_IDS = [
  "section_overview",
  "section_trends",
  "section_leaderboard",
  "section_user_detail",
  "section_analysis",
  "section_snapshot",
];

const els = {
  navRail: $("nav_rail"),
  drawerBackdrop: $("drawer_backdrop"),
  navToggleBtn: $("nav_toggle_btn"),
  statusText: $("status_text"),
  statusPill: $("status_pill"),
  refreshBtn: $("refresh_btn"),
  logoutBtn: $("logout_btn"),
  lastUpdated: $("last_updated"),
  rangeChips: $("range_chips"),
  customRange: $("custom_range"),
  startDate: $("start_date"),
  endDate: $("end_date"),
  autoRefreshToggle: $("auto_refresh_toggle"),
  showFullIdToggle: $("show_full_id_toggle"),
  kpiGrid: $("kpi_grid"),
  trendTabs: $("trend_tabs"),
  groupChart: $("group_chart"),
  groupChartFallback: $("group_chart_fallback"),
  leaderboardList: $("leaderboard_list"),
  selectedUserHint: $("selected_user_hint"),
  userOverviewEmpty: $("user_overview_empty"),
  userOverviewContent: $("user_overview_content"),
  userKpiGrid: $("user_kpi_grid"),
  userSleepHourlyChart: $("user_sleep_hourly_chart"),
  userWakeHourlyChart: $("user_wake_hourly_chart"),
  userDetailLabel: $("user_detail_label"),
  userTrendChart: $("user_trend_chart"),
  sessionStatusFilter: $("session_status_filter"),
  sessionSourceFilter: $("session_source_filter"),
  sessionDateFilter: $("session_date_filter"),
  userSessionsTbody: $("user_sessions_tbody"),
  snapshotJson: $("snapshot_json"),
  analysisScopeSwitch: $("analysis_scope_switch"),
  analysisScopeGroup: $("analysis_scope_group"),
  analysisScopeUser: $("analysis_scope_user"),
  analysisScopeHint: $("analysis_scope_hint"),
  analysisBtn: $("analysis_btn"),
  analysisState: $("analysis_state"),
  analysisMd: $("analysis_md"),
  snackbar: $("snackbar"),
  snackbarContent: document.querySelector("#snackbar .snackbar-content")
};

const state = {
  rangeMode: "7",
  autoRefresh: true,
  showFullId: false,
  activeTrendTab: "series", // Default to series for better initial view
  selectedUserId: "",
  analysisScope: "group",
  activeSection: "section_overview",
  drawerOpen: false,
  sectionObserver: null,
  overview: null,
  leaderboard: [],
  userInsight: null,
  sessions: [],
  snapshot: null,
  pollTimer: null,
  snackbarTimer: null,
  busy: false,
};

const charts = {
  group: null,
  userTrend: null,
  userSleepHourly: null,
  userWakeHourly: null,
};

const hasEcharts = Boolean(window.echarts && window.OyasumiCharts);
const POLL_INTERVAL_MS = 15000;

function isMobileLayout() {
  return window.matchMedia("(max-width: 768px)").matches;
}

function setBusy(busy) {
  state.busy = busy;
  document.body.classList.toggle("is-busy", busy);
  els.refreshBtn.disabled = busy;
  els.analysisBtn.disabled = busy;
  if (busy) {
    els.refreshBtn.classList.add('rotating');
  } else {
    els.refreshBtn.classList.remove('rotating');
  }
  setStatus(busy ? "同步中" : "就绪");
}

function setStatus(text) {
  els.statusText.textContent = text;
}

function normalizedAnalysisScope() {
  return state.analysisScope === "user" ? "user" : "group";
}

function syncAnalysisScopeControls() {
  const scope = normalizedAnalysisScope();
  [els.analysisScopeGroup, els.analysisScopeUser].forEach((btn) => {
    if (!btn) return;
    btn.classList.toggle("active", btn.dataset.scope === scope);
  });

  if (!els.analysisScopeHint) return;
  if (scope === "user") {
    if (state.selectedUserId) {
      els.analysisScopeHint.textContent = `当前范围：用户 ${maskUserId(state.selectedUserId)} 的个体分析`;
      return;
    }
    els.analysisScopeHint.textContent = "当前范围：当前用户分析（请先从排行榜选择用户）";
    return;
  }
  els.analysisScopeHint.textContent = "当前范围：全体成员综合分析";
}

function notify(message, error = false) {
  if (state.snackbarTimer) {
    window.clearTimeout(state.snackbarTimer);
  }
  if (els.snackbarContent) els.snackbarContent.textContent = message;
  else els.snackbar.textContent = message;

  els.snackbar.className = `md3-snackbar show${error ? " error" : ""}`;
  state.snackbarTimer = window.setTimeout(() => {
    els.snackbar.className = "md3-snackbar";
  }, 3000);
}

function escapeHtml(raw) {
  return String(raw ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/\"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function toDateInput(date) {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

function initDateInputs() {
  const today = new Date();
  const start = new Date(today);
  start.setDate(start.getDate() - 6);
  els.startDate.value = toDateInput(start);
  els.endDate.value = toDateInput(today);
}

function setRangeMode(mode) {
  state.rangeMode = mode;
  const chips = els.rangeChips.querySelectorAll("[data-range]");
  chips.forEach((chip) => {
    chip.classList.toggle("active", chip.dataset.range === mode);
  });
  els.customRange.hidden = mode !== "custom";
}

function currentRangeParams() {
  if (state.rangeMode === "custom") {
    const startDate = (els.startDate.value || "").trim();
    const endDate = (els.endDate.value || "").trim();
    return { start_date: startDate, end_date: endDate };
  }
  return { days: state.rangeMode };
}

function concreteRangeFromOverview() {
  if (state.rangeMode === "custom") {
    return {
      start_date: (els.startDate.value || "").trim(),
      end_date: (els.endDate.value || "").trim(),
    };
  }
  if (state.overview) {
    return {
      start_date: state.overview.start_date,
      end_date: state.overview.end_date,
    };
  }
  const days = Number(state.rangeMode || 7);
  const end = new Date();
  const start = new Date(end);
  start.setDate(start.getDate() - Math.max(days, 1) + 1);
  return {
    start_date: toDateInput(start),
    end_date: toDateInput(end),
  };
}

function toQueryString(params) {
  const query = new URLSearchParams();
  Object.entries(params || {}).forEach(([key, value]) => {
    if (value === undefined || value === null) return;
    const text = String(value).trim();
    if (text) {
      query.set(key, text);
    }
  });
  return query.toString();
}

function maskUserId(userId) {
  const text = String(userId || "");
  if (state.showFullId) return text;
  if (text.length <= 4) return `${text.slice(0, 1)}***`;
  if (text.length <= 8) return `${text.slice(0, 2)}***${text.slice(-2)}`;
  return `${text.slice(0, 3)}***${text.slice(-3)}`;
}

function formatMinutes(minutes) {
  return window.OyasumiCharts ? window.OyasumiCharts.minutesToHourText(minutes) : `${minutes} 分钟`;
}

function formatDatetime(value) {
  if (!value) return "-";
  const text = String(value);
  return text.length >= 16 ? text.slice(0, 16).replace('-', '/') : text;
}

function formatPercent(value) {
  return `${Math.round(Number(value || 0) * 100)}%`;
}

function setActiveSection(
  sectionId,
  { scroll = false, smooth = true, closeDrawer = false } = {},
) {
  if (!sectionId || !SECTION_IDS.includes(sectionId)) return;
  state.activeSection = sectionId;

  const buttons = document.querySelectorAll(".nav-dest[data-section-target]");
  buttons.forEach((button) => {
    button.classList.toggle("active", button.dataset.sectionTarget === sectionId);
  });

  if (scroll) {
    const target = document.getElementById(sectionId);
    if (target) {
      target.scrollIntoView({
        behavior: smooth ? "smooth" : "auto",
        block: "start",
      });
    }
  }

  if (closeDrawer && isMobileLayout()) {
    closeSidebarDrawer();
  }
}

function openSidebarDrawer() {
  if (!isMobileLayout()) return;
  state.drawerOpen = true;
  document.body.classList.add("drawer-open");
}

function closeSidebarDrawer() {
  state.drawerOpen = false;
  document.body.classList.remove("drawer-open");
}

function syncSectionByScroll() {
  if (state.sectionObserver) {
    state.sectionObserver.disconnect();
    state.sectionObserver = null;
  }

  if (!("IntersectionObserver" in window)) return;

  const sections = SECTION_IDS.map((id) => document.getElementById(id)).filter(Boolean);
  if (!sections.length) return;

  state.sectionObserver = new IntersectionObserver(
    (entries) => {
      const visibleEntries = entries
        .filter((entry) => entry.isIntersecting)
        .sort((a, b) => b.intersectionRatio - a.intersectionRatio);
      if (!visibleEntries.length) return;
      const topEntry = visibleEntries[0];
      const targetId = topEntry.target?.id;
      if (targetId && targetId !== state.activeSection) {
        setActiveSection(targetId, { scroll: false });
      }
    },
    { threshold: [0.25, 0.45, 0.65], rootMargin: "-80px 0px -50% 0px" }
  );

  sections.forEach((section) => state.sectionObserver.observe(section));
}

async function api(path, method = "GET", body = null) {
  const response = await fetch(path, {
    method,
    credentials: "same-origin",
    headers: body ? { "Content-Type": "application/json" } : {},
    body: body ? JSON.stringify(body) : null,
  });

  if (response.status === 401) {
    window.location.href = "/login";
    throw new Error("会话已过期，请重新登录");
  }

  let payload = null;
  try {
    payload = await response.json();
  } catch (_error) {
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
  }

  if (!response.ok || payload?.status !== "ok") {
    reportClientLog("error", "API request failed", {
      path,
      method,
      status: response.status,
      message: payload?.message || "",
    });
    throw new Error(payload?.message || `HTTP ${response.status}`);
  }

  return payload.data || {};
}

function reportClientLog(level, message, extra = null) {
  const payload = {
    level,
    message,
    extra,
  };

  fetch("/api/client-log", {
    method: "POST",
    credentials: "same-origin",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  }).catch(() => {
    // Ignore logging failures to avoid affecting the UI flow.
  });
}

async function checkAuth() {
  const data = await api("/api/auth/status");
  if (data.require_login) els.logoutBtn.hidden = false;
  if (data.require_login && !data.authenticated) {
    window.location.href = "/login";
    return false;
  }
  return true;
}

function ensureChart(target, key) {
  if (!hasEcharts || !target) return null;
  if (charts[key]) return charts[key];
  charts[key] = window.echarts.init(target, null, { renderer: "canvas" });
  return charts[key];
}

function clearChart(key) {
  if (!charts[key]) return;
  charts[key].dispose();
  charts[key] = null;
}

function renderKpis() {
  const kpis = state.overview?.kpis;
  if (!kpis) {
    els.kpiGrid.innerHTML = "";
    return;
  }

  const cards = [
    { label: "活跃人数", value: String(kpis.active_user_count || 0), sub: "发生闭合会话" },
    { label: "打卡次数", value: String(kpis.total_sessions || 0), sub: "有效睡眠记录" },
    { label: "人均睡眠", value: formatMinutes(kpis.avg_sleep_minutes || 0), sub: "平均时长" },
    { label: "进行中会话", value: String(kpis.open_session_count || 0), sub: "挂机状态" },
    { label: "孤立早安", value: String(kpis.orphan_morning_count || 0), sub: "未补录晚安" },
    { label: "补录率", value: formatPercent(kpis.auto_fill_ratio || 0), sub: `系统自动纠错` },
  ];

  els.kpiGrid.innerHTML = cards.map((card) => `
      <article class="kpi-card">
        <div class="kpi-label">${escapeHtml(card.label)}</div>
        <div class="kpi-value">${escapeHtml(card.value)}</div>
        <div class="kpi-sub">${escapeHtml(card.sub)}</div>
      </article>
  `).join("");
}

function renderGroupChart() {
  const dailySeries = state.overview?.daily_series || [];
  const sleepHeatmap = state.overview?.sleep_heatmap || [];
  const wakeHeatmap = state.overview?.wake_heatmap || [];

  if (!hasEcharts) {
    els.groupChart.innerHTML = "";
    els.groupChartFallback.hidden = false;
    els.groupChartFallback.innerHTML = window.OyasumiCharts
      ? window.OyasumiCharts.fallbackTrendTable(dailySeries)
      : "<p class='empty-text'>图表引擎加载未完备。</p>";
    return;
  }

  els.groupChartFallback.hidden = true;
  const chart = ensureChart(els.groupChart, "group");
  if (!chart) return;

  let option = null;
  if (state.activeTrendTab === "sleep") {
    option = window.OyasumiCharts.buildHeatmapOption("入睡习惯图谱", sleepHeatmap, "入睡");
  } else if (state.activeTrendTab === "wake") {
    option = window.OyasumiCharts.buildHeatmapOption("起床习惯图谱", wakeHeatmap, "起床");
  } else {
    option = window.OyasumiCharts.buildGroupTrendOption(dailySeries);
  }

  chart.setOption(option, true);
}

function renderLeaderboard() {
  const items = state.leaderboard || [];
  if (!items.length) {
    els.leaderboardList.innerHTML = '<div class="premium-empty-state minimal"><p>区间内暂无活跃数据</p></div>';
    return;
  }

  els.leaderboardList.innerHTML = items.map((item, index) => {
    const userId = String(item.user_id || "");
    const userIdEncoded = encodeURIComponent(userId);
    const selectedClass = state.selectedUserId === userId ? "active" : "";
    return `
        <button class="leader-row ${selectedClass}" type="button" data-user-id="${escapeHtml(userIdEncoded)}">
          <span class="rank">#${index + 1}</span>
          <span class="user">${escapeHtml(maskUserId(userId))}</span>
          <span class="meta">${escapeHtml(formatMinutes(item.total_sleep_minutes || 0))}</span>
        </button>
      `;
  }).join("");
}

function renderUserOverview() {
  if (!state.selectedUserId || !state.userInsight) {
    els.userOverviewEmpty.hidden = false;
    els.userOverviewContent.hidden = true;
    els.selectedUserHint.textContent = "未选择";
    els.userDetailLabel.textContent = "未选择用户";
    syncAnalysisScopeControls();
    els.userKpiGrid.innerHTML = "";
    clearChart("userTrend"); clearChart("userSleepHourly"); clearChart("userWakeHourly");
    if (!hasEcharts) {
      els.userTrendChart.innerHTML = ''; els.userSleepHourlyChart.innerHTML = ''; els.userWakeHourlyChart.innerHTML = '';
    }
    return;
  }

  const userIdLabel = maskUserId(state.selectedUserId);
  const kpis = state.userInsight.kpis || {};
  els.userOverviewEmpty.hidden = true;
  els.userOverviewContent.hidden = false;
  els.selectedUserHint.textContent = `${userIdLabel}`;
  els.userDetailLabel.textContent = `${userIdLabel}`;
  syncAnalysisScopeControls();

  const miniCards = [
    { label: "会话总计", value: String(kpis.total_sessions || 0) },
    { label: "熬夜偏晚率", value: formatPercent(kpis.late_sleep_rate || 0) },
    { label: "人均异常", value: String((kpis.orphan_morning_count || 0) + (kpis.open_session_count || 0)) },
  ];
  els.userKpiGrid.innerHTML = miniCards.map((card) => `
      <article class="mini-kpi">
        <div class="mini-kpi-label">${escapeHtml(card.label)}</div>
        <div class="mini-kpi-value">${escapeHtml(card.value)}</div>
      </article>
  `).join("");

  const dailySeries = state.userInsight.daily_series || [];
  if (!hasEcharts) {
    els.userTrendChart.innerHTML = window.OyasumiCharts ? window.OyasumiCharts.fallbackTrendTable(dailySeries) : '';
    return;
  }

  const userTrend = ensureChart(els.userTrendChart, "userTrend");
  if (userTrend) userTrend.setOption(window.OyasumiCharts.buildUserTrendOption(dailySeries, userIdLabel), true);

  const sleepHourly = ensureChart(els.userSleepHourlyChart, "userSleepHourly");
  if (sleepHourly) sleepHourly.setOption(window.OyasumiCharts.buildSleepHourlyOption(state.userInsight.sleep_hourly || []), true);

  const wakeHourly = ensureChart(els.userWakeHourlyChart, "userWakeHourly");
  if (wakeHourly) wakeHourly.setOption(window.OyasumiCharts.buildWakeHourlyOption(state.userInsight.wake_hourly || []), true);
}

function filterSessions(rows) {
  const statusFilter = els.sessionStatusFilter?.value || 'all';
  const sourceFilter = els.sessionSourceFilter?.value || 'all';
  const dateFilter = (els.sessionDateFilter?.value || "").trim();

  return (rows || []).filter((session) => {
    if (statusFilter !== "all" && String(session.status || "") !== statusFilter) return false;
    if (sourceFilter !== "all" && String(session.source || "") !== sourceFilter) return false;
    if (dateFilter) {
      const sleepTime = String(session.sleep_time || "");
      const wakeTime = String(session.wake_time || "");
      if (!sleepTime.startsWith(dateFilter) && !wakeTime.startsWith(dateFilter)) return false;
    }
    return true;
  });
}

function renderSessions() {
  if (!state.selectedUserId) {
    els.userSessionsTbody.innerHTML = '<tr><td colspan="7" style="text-align:center;color:#74777f">请在上方选择用户</td></tr>';
    return;
  }

  const rows = filterSessions(state.sessions);
  if (!rows.length) {
    els.userSessionsTbody.innerHTML = '<tr><td colspan="7" style="text-align:center;color:#74777f">暂无匹配记录</td></tr>';
    return;
  }

  els.userSessionsTbody.innerHTML = rows.map((session) => `
      <tr>
        <td style="color:#74777f;font-family:monospace;font-size:12px;">${escapeHtml(session.id)}</td>
        <td style="font-weight:600;">${escapeHtml(maskUserId(session.user_id))}</td>
        <td><span class="md3-badge ${session.status === 'open' ? 'error' : 'neutral'}">${escapeHtml(session.status || "-")}</span></td>
        <td>${escapeHtml(formatDatetime(session.sleep_time))}</td>
        <td>${escapeHtml(formatDatetime(session.wake_time))}</td>
        <td>${escapeHtml(session.duration_minutes ?? "-")}</td>
        <td>${escapeHtml(session.source || "-")}</td>
      </tr>
  `).join("");
}

function renderSnapshot() {
  els.snapshotJson.textContent = JSON.stringify(state.snapshot || {}, null, 2);
}

function updateLastUpdated() {
  const now = new Date();
  els.lastUpdated.textContent = `最近刷新：${now.toLocaleTimeString("zh-CN")}`;
}

function renderAll() {
  renderKpis();
  renderGroupChart();
  renderLeaderboard();
  renderUserOverview();
  renderSessions();
  renderSnapshot();
}

async function loadOverview(rangeParams) {
  state.overview = await api(`/api/overview?${toQueryString(rangeParams)}`);
}

async function loadLeaderboard(rangeParams) {
  const payload = await api(`/api/leaderboard?${toQueryString({ ...rangeParams, limit: 10, metric: "activity" })}`);
  state.leaderboard = payload.items || [];
}

async function loadSnapshot() {
  const payload = await api("/api/snapshot");
  state.snapshot = payload.snapshot || null;
}

async function loadSelectedUserData(rangeParams) {
  if (!state.selectedUserId) {
    state.userInsight = null;
    state.sessions = [];
    return;
  }
  const [insight, sessionPayload] = await Promise.all([
    api(`/api/user_insight?${toQueryString({ ...rangeParams, user_id: state.selectedUserId })}`),
    api(`/api/sessions?${toQueryString({ user_id: state.selectedUserId, limit: 200 })}`),
  ]);
  state.userInsight = insight;
  state.sessions = sessionPayload.sessions || [];
}

async function refreshAll({ silent = false } = {}) {
  if (!silent) setBusy(true);
  try {
    const rangeParams = currentRangeParams();
    reportClientLog("info", "Refreshing dashboard data", rangeParams);
    await Promise.all([loadOverview(rangeParams), loadLeaderboard(rangeParams), loadSnapshot()]);
    await loadSelectedUserData(rangeParams);
    renderAll();
    updateLastUpdated();
    if (!silent) notify("看板数据已同步");
  } catch (error) {
    reportClientLog("error", "Failed to refresh dashboard data", {
      message: error.message || String(error),
    });
    notify(error.message || String(error), true);
  } finally {
    if (!silent) setBusy(false);
  }
}

async function onLeaderboardClick(event) {
  const target = event.target.closest("[data-user-id]");
  if (!target) return;
  const userId = decodeURIComponent(String(target.dataset.userId || ""));
  if (!userId) return;

  state.selectedUserId = userId;
  setBusy(true);
  try {
    await loadSelectedUserData(currentRangeParams());
    renderLeaderboard();
    renderUserOverview();
    renderSessions();
    setActiveSection("section_user_detail", { scroll: true, closeDrawer: true });
  } catch (error) {
    notify(error.message || String(error), true);
  } finally {
    setBusy(false);
  }
}

function markdownToHtml(markdown) {
  let src = escapeHtml(markdown || "").replace(/\r\n/g, "\n");
  src = src.replace(/```([\w-]*)\n([\s\S]*?)```/g, (_m, lang, code) => `<pre><code>${code.replace(/\n$/, "")}</code></pre>`);

  const lines = src.split("\n");
  const html = [];
  let paragraph = [];

  function flush() {
    if (paragraph.length) html.push(`<p>${paragraph.join("<br>")}</p>`);
    paragraph = [];
  }

  for (const line of lines) {
    const t = line.trim();
    if (!t) { flush(); continue; }
    if (t.startsWith('<pre>')) { flush(); html.push(t); continue; }

    const h = t.match(/^(#{1,6})\s+(.+)$/);
    if (h) { flush(); html.push(`<h${h[1].length}>${h[2]}</h${h[1].length}>`); continue; }

    if (t.match(/^>\s?(.*)$/)) { flush(); html.push(`<blockquote>${t.replace(/^>\s?/, '')}</blockquote>`); continue; }
    if (t.match(/^[-*+]\s+(.+)$/)) { flush(); html.push(`<li>${t.replace(/^[-*+]\s+/, '')}</li>`); continue; }

    paragraph.push(t);
  }
  flush();
  return html.join("\n").replace(/<li>/g, '<ul><li>').replace(/<\/li>\n(?!<li>)/g, '</li></ul>\n').replace(/<\/ul>\n<ul>/g, '\n');
}

async function handleGenerateAnalysis() {
  const rangeParams = concreteRangeFromOverview();
  let scope = normalizedAnalysisScope();
  if (scope === "user" && !state.selectedUserId) {
    scope = "group";
    state.analysisScope = "group";
    syncAnalysisScopeControls();
    notify("尚未选择用户，已切换为全体成员综合分析");
  }
  const options = {
    start_date: rangeParams.start_date,
    end_date: rangeParams.end_date,
    scope,
    user_id: scope === "user" ? (state.selectedUserId || undefined) : undefined,
  };

  els.analysisBtn.disabled = true;
  els.analysisState.textContent = scope === "group"
    ? "LLM 正在综合分析全体成员作息..."
    : "LLM 正在分析当前用户作息...";
  try {
    reportClientLog("info", "Generating analysis", {
      scope,
      user_id: state.selectedUserId || "",
      start_date: options.start_date,
      end_date: options.end_date,
    });
    const payload = await api("/api/analysis", "POST", options);
    if (!payload.analysis_text) throw new Error("返回数据结构异常");
    els.analysisState.textContent = scope === "group" ? "全体成员综合分析已完成" : "用户分析已完成";
    els.analysisMd.innerHTML = markdownToHtml(payload.analysis_text);
  } catch (error) {
    els.analysisState.textContent = "分析失败";
    els.analysisMd.innerHTML = `<p style="color:red;">异常：${escapeHtml(error.message || String(error))}</p>`;
    reportClientLog("error", "Analysis generation failed", {
      message: error.message || String(error),
      scope,
      user_id: state.selectedUserId || "",
    });
    notify(error.message || "生成分析报告异常", true);
  } finally {
    els.analysisBtn.disabled = false;
  }
}

function handleResize() {
  Object.values(charts).forEach((c) => { if (c) c.resize(); });
}

function setupEvents() {
  els.rangeChips?.addEventListener("click", (e) => {
    if (e.target.dataset.range) {
      setRangeMode(e.target.dataset.range);
      refreshAll();
    }
  });

  ['startDate', 'endDate'].forEach(id => els[id]?.addEventListener("change", () => {
    if (state.rangeMode === "custom") refreshAll();
  }));

  els.autoRefreshToggle?.addEventListener("change", (e) => {
    state.autoRefresh = e.target.checked;
    if (state.autoRefresh) schedulePoll();
    else clearTimeout(state.pollTimer);
  });

  els.showFullIdToggle?.addEventListener("change", (e) => {
    state.showFullId = e.target.checked;
    renderLeaderboard(); renderUserOverview(); renderSessions();
  });

  els.trendTabs?.addEventListener("click", (e) => {
    if (e.target.dataset.tab) {
      state.activeTrendTab = e.target.dataset.tab;
      els.trendTabs.querySelectorAll(".segment").forEach(btn => btn.classList.toggle("active", btn.dataset.tab === state.activeTrendTab));
      renderGroupChart();
    }
  });

  els.leaderboardList?.addEventListener("click", onLeaderboardClick);
  els.analysisScopeSwitch?.addEventListener("click", (event) => {
    const target = event.target.closest("[data-scope]");
    if (!target) return;
    state.analysisScope = target.dataset.scope === "user" ? "user" : "group";
    syncAnalysisScopeControls();
  });

  ['sessionStatusFilter', 'sessionSourceFilter', 'sessionDateFilter'].forEach(id =>
    els[id]?.addEventListener("change", renderSessions)
  );

  els.refreshBtn?.addEventListener("click", () => refreshAll());
  els.analysisBtn?.addEventListener("click", handleGenerateAnalysis);

  els.logoutBtn?.addEventListener("click", () => {
    document.cookie = "oyasumi_webui_token=; path=/; max-age=0";
    window.location.href = "/login";
  });

  document.querySelectorAll(".nav-dest[data-section-target]").forEach(btn => {
    btn.addEventListener("click", () => setActiveSection(btn.dataset.sectionTarget, { scroll: true, closeDrawer: true }));
  });

  els.navToggleBtn?.addEventListener("click", () => {
    if (state.drawerOpen) closeSidebarDrawer();
    else openSidebarDrawer();
  });

  els.drawerBackdrop?.addEventListener("click", closeSidebarDrawer);
  window.addEventListener("resize", () => requestAnimationFrame(handleResize));
}

function schedulePoll() {
  clearTimeout(state.pollTimer);
  if (!state.autoRefresh) return;
  state.pollTimer = setTimeout(async () => {
    if (!state.busy) await refreshAll({ silent: true });
    schedulePoll();
  }, POLL_INTERVAL_MS);
}

async function bootstrap() {
  // Intro animation
  document.body.style.opacity = '0';
  setTimeout(() => {
    document.body.style.transition = 'opacity 0.8s cubic-bezier(0.2, 0, 0, 1)';
    document.body.style.opacity = '1';
  }, 100);

  initDateInputs();
  setRangeMode("7");
  setupEvents();

  try {
    const passed = await checkAuth();
    if (!passed) return;
  } catch (e) {
    notify(e.message, true);
    return;
  }

  await refreshAll();
  syncSectionByScroll();
  schedulePoll();
}

bootstrap();
