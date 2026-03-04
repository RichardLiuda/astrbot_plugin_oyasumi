const $ = (id) => document.getElementById(id);

const els = {
  userId: $("user_id"),
  days: $("days"),
  limit: $("limit"),
  startDate: $("start_date"),
  endDate: $("end_date"),
  refreshBtn: $("refresh_btn"),
  logoutBtn: $("logout_btn"),
  analysisBtn: $("analysis_btn"),
  statusText: $("status_text"),
  metrics: $("metrics"),
  trendSvg: $("trend_svg"),
  dailyList: $("daily_list"),
  donut: $("session_donut"),
  donutTotal: $("donut_total"),
  donutLegend: $("donut_legend"),
  insightBox: $("insight_box"),
  sessionsBody: $("sessions_tbody"),
  analysisMd: $("analysis_md"),
  snapshot: $("snapshot"),
  toast: $("toast"),
};

let toastTimer = null;
let latestSummary = null;
let latestDailyRows = [];

function initDates() {
  const now = new Date();
  const start = new Date(now);
  start.setDate(now.getDate() - 6);
  els.startDate.value = toDateInput(start);
  els.endDate.value = toDateInput(now);
}

function toDateInput(date) {
  const y = date.getFullYear();
  const m = String(date.getMonth() + 1).padStart(2, "0");
  const d = String(date.getDate()).padStart(2, "0");
  return `${y}-${m}-${d}`;
}

function escapeHtml(raw) {
  return String(raw ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function renderAnalysisMarkdown(markdownText) {
  const raw = String(markdownText || "").trim();
  if (!raw) {
    els.analysisMd.innerHTML = '<p class="md-placeholder">暂无分析内容</p>';
    return;
  }
  els.analysisMd.innerHTML = markdownToHtml(raw);
}

function markdownToHtml(markdown) {
  const codeBlocks = [];
  let src = escapeHtml(markdown).replace(/\r\n/g, "\n");

  src = src.replace(/```([\w-]*)\n([\s\S]*?)```/g, (_m, lang, code) => {
    const index = codeBlocks.length;
    const langClass = lang ? ` class="language-${lang}"` : "";
    codeBlocks.push(
      `<pre><code${langClass}>${code.replace(/\n$/, "")}</code></pre>`,
    );
    return `@@CODE_BLOCK_${index}@@`;
  });

  const lines = src.split("\n");
  const html = [];
  let paragraph = [];
  let inUl = false;
  let inOl = false;

  const closeLists = () => {
    if (inUl) {
      html.push("</ul>");
      inUl = false;
    }
    if (inOl) {
      html.push("</ol>");
      inOl = false;
    }
  };

  const flushParagraph = () => {
    if (paragraph.length === 0) {
      return;
    }
    const content = paragraph.join("<br>");
    html.push(`<p>${inlineMarkdown(content)}</p>`);
    paragraph = [];
  };

  for (const line of lines) {
    const trimmed = line.trim();
    if (!trimmed) {
      flushParagraph();
      closeLists();
      continue;
    }

    const codeBlock = trimmed.match(/^@@CODE_BLOCK_(\d+)@@$/);
    if (codeBlock) {
      flushParagraph();
      closeLists();
      html.push(trimmed);
      continue;
    }

    const heading = trimmed.match(/^(#{1,6})\s+(.+)$/);
    if (heading) {
      flushParagraph();
      closeLists();
      const level = heading[1].length;
      html.push(`<h${level}>${inlineMarkdown(heading[2])}</h${level}>`);
      continue;
    }

    const quote = trimmed.match(/^>\s?(.*)$/);
    if (quote) {
      flushParagraph();
      closeLists();
      html.push(`<blockquote>${inlineMarkdown(quote[1])}</blockquote>`);
      continue;
    }

    const ulItem = trimmed.match(/^[-*+]\s+(.+)$/);
    if (ulItem) {
      flushParagraph();
      if (inOl) {
        html.push("</ol>");
        inOl = false;
      }
      if (!inUl) {
        html.push("<ul>");
        inUl = true;
      }
      html.push(`<li>${inlineMarkdown(ulItem[1])}</li>`);
      continue;
    }

    const olItem = trimmed.match(/^\d+\.\s+(.+)$/);
    if (olItem) {
      flushParagraph();
      if (inUl) {
        html.push("</ul>");
        inUl = false;
      }
      if (!inOl) {
        html.push("<ol>");
        inOl = true;
      }
      html.push(`<li>${inlineMarkdown(olItem[1])}</li>`);
      continue;
    }

    closeLists();
    paragraph.push(trimmed);
  }

  flushParagraph();
  closeLists();

  let merged = html.join("\n");
  merged = merged.replace(/@@CODE_BLOCK_(\d+)@@/g, (_m, idx) => {
    return codeBlocks[Number(idx)] || "";
  });
  return merged;
}

function inlineMarkdown(text) {
  let out = text;
  out = out.replace(
    /\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g,
    '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>',
  );
  out = out.replace(/`([^`]+)`/g, "<code>$1</code>");
  out = out.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
  out = out.replace(/__([^_]+)__/g, "<strong>$1</strong>");
  out = out.replace(/\*([^*]+)\*/g, "<em>$1</em>");
  out = out.replace(/_([^_]+)_/g, "<em>$1</em>");
  out = out.replace(/~~([^~]+)~~/g, "<del>$1</del>");
  return out;
}

function getBaseParams() {
  return {
    user_id: els.userId.value,
    days: els.days.value,
    limit: els.limit.value,
    start_date: els.startDate.value,
    end_date: els.endDate.value,
  };
}

function setLoading(loading) {
  document.body.classList.toggle("loading", loading);
  els.refreshBtn.disabled = loading;
  els.analysisBtn.disabled = loading;
  els.statusText.textContent = loading ? "加载中" : "就绪";
}

function notify(message, type = "info") {
  if (toastTimer) {
    clearTimeout(toastTimer);
  }
  els.toast.textContent = message;
  els.toast.className = `toast show ${type === "error" ? "error" : ""}`.trim();
  toastTimer = setTimeout(() => {
    els.toast.className = "toast";
  }, 2200);
}

async function api(path, method = "GET", body = null) {
  const headers = {};
  if (body !== null) {
    headers["Content-Type"] = "application/json";
  }

  const response = await fetch(path, {
    method,
    headers,
    credentials: "same-origin",
    body: body === null ? null : JSON.stringify(body),
  });
  if (response.status === 401) {
    window.location.href = "/login";
    throw new Error("未登录或登录已过期");
  }

  let payload = null;
  try {
    payload = await response.json();
  } catch (_err) {
    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`);
    }
  }

  if (!response.ok || payload?.status !== "ok") {
    throw new Error(payload?.message || `HTTP ${response.status}`);
  }
  return payload.data;
}

async function checkAuthStatus() {
  const data = await api("/api/auth/status");
  const requireLogin = Boolean(data.require_login);
  const authed = Boolean(data.authenticated);
  if (els.logoutBtn) {
    els.logoutBtn.hidden = !requireLogin;
  }
  if (requireLogin && !authed) {
    window.location.href = "/login";
    return false;
  }
  return true;
}

function minutesText(value) {
  const minutes = Number(value || 0);
  const h = Math.floor(minutes / 60);
  const m = minutes % 60;
  return h > 0 ? `${h}小时${m}分钟` : `${m}分钟`;
}

function shortDate(dateLike) {
  if (!dateLike) {
    return "-";
  }
  const raw = String(dateLike);
  if (raw.length >= 10) {
    return raw.slice(5, 10);
  }
  return raw;
}

function renderMetrics(summary) {
  const rows = [
    ["总睡眠时长", minutesText(summary.total_sleep_minutes)],
    ["总会话数", String(summary.total_sessions ?? 0)],
    ["平均时长", minutesText(summary.avg_sleep_minutes)],
    ["进行中会话", String(summary.open_session_count ?? 0)],
    ["仅早安事件", String(summary.orphan_morning_count ?? 0)],
  ];

  els.metrics.innerHTML = rows
    .map(
      ([key, value]) => `
      <article class="metric">
        <div class="metric-key">${escapeHtml(key)}</div>
        <div class="metric-value">${escapeHtml(value)}</div>
      </article>
    `,
    )
    .join("");
}

function renderTrendChart(dailyRows) {
  if (!dailyRows.length) {
    els.trendSvg.innerHTML = `
      <text x="50%" y="50%" dominant-baseline="middle" text-anchor="middle" fill="#648082" font-size="14">
        暂无趋势数据
      </text>
    `;
    return;
  }

  const rows = [...dailyRows].sort((a, b) => String(a.stat_date).localeCompare(String(b.stat_date)));
  const width = 860;
  const height = 280;
  const pad = { l: 44, r: 18, t: 18, b: 36 };
  const innerW = width - pad.l - pad.r;
  const innerH = height - pad.t - pad.b;

  const values = rows.map((item) => Number(item.total_minutes || 0));
  const maxVal = Math.max(...values, 1);
  const yMax = Math.ceil(maxVal / 30) * 30 || 30;

  const points = rows.map((item, index) => {
    const x = pad.l + (innerW * index) / Math.max(rows.length - 1, 1);
    const v = Number(item.total_minutes || 0);
    const y = pad.t + innerH - (v / yMax) * innerH;
    return { x, y, v, date: item.stat_date };
  });

  const linePath = points
    .map((p, i) => `${i === 0 ? "M" : "L"}${p.x.toFixed(1)},${p.y.toFixed(1)}`)
    .join(" ");
  const areaPath = `${linePath} L ${points[points.length - 1].x.toFixed(1)},${(pad.t + innerH).toFixed(1)} L ${points[0].x.toFixed(1)},${(pad.t + innerH).toFixed(1)} Z`;

  const grid = [0, 0.25, 0.5, 0.75, 1]
    .map((ratio) => {
      const y = pad.t + innerH * ratio;
      const value = Math.round((1 - ratio) * yMax);
      return `
        <line x1="${pad.l}" y1="${y.toFixed(1)}" x2="${(pad.l + innerW).toFixed(1)}" y2="${y.toFixed(1)}" stroke="#d4e4e6" stroke-width="1"/>
        <text x="${pad.l - 8}" y="${(y + 4).toFixed(1)}" text-anchor="end" fill="#6b8587" font-size="11">${value}</text>
      `;
    })
    .join("");

  const markers = points
    .map(
      (p) => `
      <circle cx="${p.x.toFixed(1)}" cy="${p.y.toFixed(1)}" r="4.2" fill="#ffffff" stroke="#2a8e91" stroke-width="2"/>
      <text x="${p.x.toFixed(1)}" y="${(height - 12).toFixed(1)}" text-anchor="middle" fill="#648082" font-size="10">${escapeHtml(shortDate(p.date))}</text>
    `,
    )
    .join("");

  els.trendSvg.innerHTML = `
    <defs>
      <linearGradient id="trendArea" x1="0" y1="0" x2="0" y2="1">
        <stop offset="0%" stop-color="#52b7ba" stop-opacity="0.45" />
        <stop offset="100%" stop-color="#52b7ba" stop-opacity="0.04" />
      </linearGradient>
      <linearGradient id="trendLine" x1="0" y1="0" x2="1" y2="0">
        <stop offset="0%" stop-color="#1f8f92" />
        <stop offset="100%" stop-color="#66bdc0" />
      </linearGradient>
    </defs>
    ${grid}
    <path d="${areaPath}" fill="url(#trendArea)" />
    <path d="${linePath}" fill="none" stroke="url(#trendLine)" stroke-width="3.2" stroke-linejoin="round" stroke-linecap="round" />
    ${markers}
  `;
}

function renderDailyBars(dailyRows) {
  if (!dailyRows.length) {
    els.dailyList.innerHTML = '<div class="section-desc">暂无数据</div>';
    return;
  }
  const rows = [...dailyRows].sort((a, b) => String(a.stat_date).localeCompare(String(b.stat_date)));
  const maxMinutes = Math.max(...rows.map((item) => Number(item.total_minutes || 0)), 1);
  els.dailyList.innerHTML = rows
    .map((item) => {
      const minutes = Number(item.total_minutes || 0);
      const width = Math.max(6, Math.round((minutes / maxMinutes) * 100));
      return `
        <div class="daily-item">
          <div class="daily-date">${escapeHtml(shortDate(item.stat_date))}</div>
          <div class="daily-bar-wrap"><div class="daily-bar" style="width:${width}%"></div></div>
          <div class="daily-value">${escapeHtml(minutesText(minutes))} · ${escapeHtml(item.session_count ?? 0)}次</div>
        </div>
      `;
    })
    .join("");
}

function renderComposition(summary) {
  const totalSessions = Number(summary.total_sessions || 0);
  const openSessions = Number(summary.open_session_count || 0);
  const orphanMorning = Number(summary.orphan_morning_count || 0);
  const closedSessions = Math.max(totalSessions - openSessions, 0);

  const segs = [
    { key: "已完成", val: closedSessions, color: "var(--chart-a)" },
    { key: "进行中", val: openSessions, color: "var(--chart-b)" },
    { key: "仅早安事件", val: orphanMorning, color: "var(--chart-c)" },
  ];
  const sum = Math.max(segs.reduce((acc, cur) => acc + cur.val, 0), 1);

  let from = 0;
  const gradientParts = segs.map((seg) => {
    const pct = (seg.val / sum) * 100;
    const to = from + pct;
    const chunk = `${seg.color} ${from.toFixed(2)}% ${to.toFixed(2)}%`;
    from = to;
    return chunk;
  });
  els.donut.style.background = `conic-gradient(${gradientParts.join(", ")})`;
  els.donutTotal.textContent = String(totalSessions);

  els.donutLegend.innerHTML = segs
    .map(
      (seg) => `
      <div class="legend-item">
        <div class="legend-left">
          <span class="legend-dot" style="background:${seg.color}"></span>
          <span class="legend-name">${escapeHtml(seg.key)}</span>
        </div>
        <span class="legend-val">${escapeHtml(seg.val)}</span>
      </div>
    `,
    )
    .join("");
}

function renderInsights() {
  if (!latestSummary) {
    els.insightBox.innerHTML = "<p>等待数据加载…</p>";
    return;
  }
  const avg = Number(latestSummary.avg_sleep_minutes || 0);
  const open = Number(latestSummary.open_session_count || 0);
  const orphan = Number(latestSummary.orphan_morning_count || 0);
  const dailyAvg = latestDailyRows.length
    ? Math.round(
        latestDailyRows.reduce((acc, row) => acc + Number(row.total_minutes || 0), 0) /
          latestDailyRows.length,
      )
    : 0;

  const hints = [];
  if (avg < 300) {
    hints.push("平均睡眠时长偏低，近期可能存在晚睡或睡眠中断。");
  } else if (avg > 540) {
    hints.push("平均睡眠时长较高，建议结合精力状态评估作息质量。");
  } else {
    hints.push("平均睡眠时长处于常见区间，节律整体较稳定。");
  }
  if (open > 0) {
    hints.push(`当前仍有 ${open} 条未闭合会话，可能存在漏记晚安或早安。`);
  }
  if (orphan > 0) {
    hints.push(`检测到 ${orphan} 条仅早安事件，建议检查时间归属规则。`);
  }
  hints.push(`近窗口每日平均睡眠约 ${minutesText(dailyAvg)}。`);

  els.insightBox.innerHTML = hints.map((item) => `<p>• ${escapeHtml(item)}</p>`).join("");
}

function renderSessions(sessions) {
  if (!sessions.length) {
    els.sessionsBody.innerHTML = '<tr><td colspan="7">暂无数据</td></tr>';
    return;
  }
  els.sessionsBody.innerHTML = sessions
    .map(
      (session) => `
      <tr>
        <td>${escapeHtml(session.id)}</td>
        <td>${escapeHtml(session.user_id)}</td>
        <td>${escapeHtml(session.status || "-")}</td>
        <td>${escapeHtml(session.sleep_time || "-")}</td>
        <td>${escapeHtml(session.wake_time || "-")}</td>
        <td>${escapeHtml(session.duration_minutes ?? "-")}</td>
        <td>${escapeHtml(session.source || "-")}</td>
      </tr>
    `,
    )
    .join("");
}

async function loadUsers() {
  const data = await api("/api/users?limit=200");
  const previous = els.userId.value;
  els.userId.innerHTML = '<option value="">全部用户</option>';
  for (const userId of data.user_ids || []) {
    const option = document.createElement("option");
    option.value = userId;
    option.textContent = userId;
    els.userId.appendChild(option);
  }
  if (previous) {
    els.userId.value = previous;
  }
}

async function loadDashboard() {
  const params = getBaseParams();
  const query = new URLSearchParams({ days: params.days });
  if (params.user_id) {
    query.set("user_id", params.user_id);
  }
  const data = await api(`/api/dashboard?${query.toString()}`);
  latestDailyRows = data.daily || [];
  renderTrendChart(latestDailyRows);
  renderDailyBars(latestDailyRows);
  renderInsights();
}

async function loadSummary() {
  const params = getBaseParams();
  const query = new URLSearchParams({
    start_date: params.start_date,
    end_date: params.end_date,
  });
  if (params.user_id) {
    query.set("user_id", params.user_id);
  }
  latestSummary = await api(`/api/summary?${query.toString()}`);
  renderMetrics(latestSummary);
  renderComposition(latestSummary);
  renderInsights();
}

async function loadSessions() {
  const params = getBaseParams();
  const query = new URLSearchParams({ limit: params.limit });
  if (params.user_id) {
    query.set("user_id", params.user_id);
  }
  const data = await api(`/api/sessions?${query.toString()}`);
  renderSessions(data.sessions || []);
}

async function loadSnapshot() {
  const data = await api("/api/snapshot");
  els.snapshot.textContent = JSON.stringify(data.snapshot || {}, null, 2);
}

async function refreshAll() {
  setLoading(true);
  try {
    await loadUsers();
    await Promise.all([loadDashboard(), loadSummary(), loadSessions(), loadSnapshot()]);
    notify("数据已刷新");
  } catch (err) {
    notify(err.message || String(err), "error");
  } finally {
    setLoading(false);
  }
}

async function generateAnalysis() {
  setLoading(true);
  try {
    const params = getBaseParams();
    const body = {
      user_id: params.user_id,
      start_date: params.start_date,
      end_date: params.end_date,
      use_llm: true,
      user_name: params.user_id || "all_users",
    };
    const data = await api("/api/analysis", "POST", body);
    renderAnalysisMarkdown(data.analysis_text || "");

    if (data.used_llm) {
      notify("分析已生成（LLM）");
    } else {
      const reasonMap = {
        llm_disabled: "未启用 LLM",
        provider_not_found: "未找到可用模型",
        provider_not_found_fallback: "未找到可用模型，已回退统计",
        llm_failed: "LLM 调用失败",
        llm_failed_fallback: "LLM 调用失败，已回退统计",
        not_requested_or_no_data: "无有效会话数据",
      };
      const reasonText = reasonMap[data.llm_reason] || data.llm_reason || "已回退";
      notify(`分析已生成（${reasonText}）`);
    }
  } catch (err) {
    notify(err.message || String(err), "error");
  } finally {
    setLoading(false);
  }
}

async function logout() {
  setLoading(true);
  try {
    await api("/api/auth/logout", "POST", {});
  } catch (_err) {
    // Ignore and force redirect to login page.
  } finally {
    window.location.href = "/login";
  }
}

function bindEvents() {
  els.refreshBtn.addEventListener("click", refreshAll);
  els.analysisBtn.addEventListener("click", generateAnalysis);
  if (els.logoutBtn) {
    els.logoutBtn.addEventListener("click", logout);
  }
}

async function bootstrap() {
  initDates();
  bindEvents();
  renderAnalysisMarkdown("");
  const canContinue = await checkAuthStatus();
  if (!canContinue) {
    return;
  }
  await refreshAll();
}

bootstrap().catch((err) => {
  notify(err.message || String(err), "error");
});
