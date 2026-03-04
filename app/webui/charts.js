(function () {
  const brandColors = {
    primary: "#005cbb",      // MD3 Primary
    primaryContainer: "#d7e3ff",
    secondary: "#166f5c",    // Darker teal/green
    tertiary: "#715573",     // Muted purple
    accent1: "#3b82f6",
    accent2: "#8b5cf6",
    accent3: "#10b981",
    textMain: "#1a1c1e",
    textMuted: "#73777f",
    gridLine: "#e1e2e8",     // Soft MD3 Outline variant
    tooltipBg: "rgba(255, 255, 255, 0.9)",
  };

  const chartFontFamily = '"Noto Sans SC", system-ui, sans-serif';

  function normalizeDates(rows) {
    const dateSet = new Set();
    for (const row of rows || []) {
      if (row && row.stat_date) {
        dateSet.add(String(row.stat_date));
      }
    }
    return Array.from(dateSet).sort((a, b) => a.localeCompare(b));
  }

  function compactDate(value) {
    if (!value) return "-";
    const text = String(value);
    return text.length >= 10 ? text.slice(5, 10).replace('-', '/') : text;
  }

  function minutesToHourText(minutes) {
    const total = Number(minutes || 0);
    const h = Math.floor(total / 60);
    const m = total % 60;
    if (h <= 0) return `${m} 分钟`;
    return `${h} 小时 ${m} 分钟`;
  }

  // 共用的提示框配置 (Premium Feel)
  const tooltipBase = {
    backgroundColor: brandColors.tooltipBg,
    borderColor: 'transparent',
    padding: [12, 16],
    textStyle: {
      color: brandColors.textMain,
      fontFamily: chartFontFamily,
      fontSize: 13,
    },
    extraCssText: 'box-shadow: 0 8px 24px rgba(0,0,0,0.08); border-radius: 12px; backdrop-filter: blur(8px);'
  };

  function buildHeatmapOption(title, rows, yAxisLabel) {
    const dates = normalizeDates(rows);
    const values = (rows || []).map((item) => [
      dates.indexOf(String(item.stat_date)),
      Number(item.hour || 0),
      Number(item.count || 0),
    ]);
    const maxCount = values.length
      ? Math.max.apply(null, values.map((item) => item[2]))
      : 0;

    return {
      backgroundColor: "transparent",
      animationDuration: 800,
      animationEasing: 'cubicOut',
      title: {
        text: title,
        left: 0,
        textStyle: {
          color: brandColors.textMain,
          fontSize: 16,
          fontWeight: 600,
          fontFamily: chartFontFamily,
        },
      },
      tooltip: {
        ...tooltipBase,
        trigger: "item",
        formatter(params) {
          const dateText = dates[params.value[0]] || "-";
          const hour = Number(params.value[1] || 0);
          const cnt = Number(params.value[2] || 0);
          return `<div style="font-weight:600;margin-bottom:4px;color:${brandColors.primary}">${dateText}</div>
                  <div style="color:${brandColors.textMuted}">${yAxisLabel}时段: ${hour}:00</div>
                  <div style="margin-top:2px;">活跃频次: <b>${cnt}</b></div>`;
        },
      },
      grid: { top: 50, left: 40, right: 20, bottom: 30 },
      xAxis: {
        type: "category",
        data: dates,
        axisLabel: { color: brandColors.textMuted, fontFamily: chartFontFamily, formatter: compactDate },
        axisLine: { lineStyle: { color: brandColors.gridLine } },
        axisTick: { show: false },
        splitArea: { show: false },
      },
      yAxis: {
        type: "category",
        data: Array.from({ length: 24 }, (_, hour) => hour),
        axisLabel: { color: brandColors.textMuted, fontFamily: chartFontFamily, formatter: (val) => `${val}`.padStart(2, "0") },
        axisLine: { lineStyle: { color: brandColors.gridLine } },
        axisTick: { show: false },
        splitArea: { show: false },
      },
      visualMap: {
        min: 0,
        max: Math.max(maxCount, 1),
        calculable: true,
        orient: "horizontal",
        left: "right",
        top: 0,
        itemWidth: 12,
        itemHeight: 120,
        textStyle: { color: brandColors.textMuted, fontSize: 12 },
        inRange: { color: ["#f1f4f9", "#c6d8fc", "#8baef7", "#3b82f6", "#0f52ba"] }, // Smooth MD3 blue gradient
      },
      series: [
        {
          type: "heatmap",
          data: values,
          label: { show: false },
          itemStyle: { borderRadius: 4, borderWidth: 2, borderColor: '#fff' },
          emphasis: {
            itemStyle: { shadowBlur: 10, shadowColor: 'rgba(59, 130, 246, 0.4)' }
          },
        },
      ],
    };
  }

  function buildGroupTrendOption(rows) {
    const dates = (rows || []).map((item) => String(item.stat_date || ""));
    const totalMinutes = (rows || []).map((item) => Number(item.total_minutes || 0));
    const sessionCount = (rows || []).map((item) => Number(item.session_count || 0));
    const activeUsers = (rows || []).map((item) => Number(item.active_user_count || 0));

    return {
      backgroundColor: "transparent",
      animationDuration: 1000,
      animationEasing: 'cubicOut',
      tooltip: { ...tooltipBase, trigger: "axis", axisPointer: { type: 'line', lineStyle: { color: brandColors.gridLine, width: 2 } } },
      legend: {
        top: 0,
        right: 0,
        icon: 'circle',
        itemGap: 24,
        textStyle: { color: brandColors.textMuted, fontFamily: chartFontFamily, fontSize: 13 },
        data: ["总时长 (分钟)", "打卡会话", "活跃人数"],
      },
      grid: { top: 40, left: 50, right: 30, bottom: 30 },
      xAxis: {
        type: "category",
        data: dates,
        axisLabel: { color: brandColors.textMuted, formatter: compactDate, margin: 12 },
        axisLine: { lineStyle: { color: brandColors.gridLine, width: 2 } },
        axisTick: { show: false },
        boundaryGap: false,
      },
      yAxis: [
        {
          type: "value",
          name: "总时长",
          nameTextStyle: { color: brandColors.textMuted, padding: [0, 20, 0, 0] },
          axisLabel: { color: brandColors.textMuted },
          splitLine: { lineStyle: { color: brandColors.gridLine, type: 'dashed' } },
        },
        {
          type: "value",
          name: "人数/会话",
          nameTextStyle: { color: brandColors.textMuted, padding: [0, 0, 0, 20] },
          axisLabel: { color: brandColors.textMuted },
          splitLine: { show: false },
        },
      ],
      series: [
        {
          name: "总时长 (分钟)",
          type: "line",
          yAxisIndex: 0,
          smooth: 0.4,
          symbol: 'none',
          lineStyle: { width: 3, color: brandColors.accent1 },
          areaStyle: {
            color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
              { offset: 0, color: 'rgba(59, 130, 246, 0.4)' },
              { offset: 1, color: 'rgba(59, 130, 246, 0.0)' }
            ])
          },
          data: totalMinutes,
        },
        {
          name: "打卡会话",
          type: "line",
          yAxisIndex: 1,
          smooth: 0.4,
          symbolSize: 8,
          symbol: 'circle',
          itemStyle: { color: brandColors.accent2, borderColor: '#fff', borderWidth: 2 },
          lineStyle: { width: 2, color: brandColors.accent2 },
          data: sessionCount,
        },
        {
          name: "活跃人数",
          type: "line",
          yAxisIndex: 1,
          smooth: 0.4,
          symbolSize: 8,
          symbol: 'circle',
          itemStyle: { color: brandColors.accent3, borderColor: '#fff', borderWidth: 2 },
          lineStyle: { width: 2, color: brandColors.accent3 },
          data: activeUsers,
        },
      ],
    };
  }

  function buildUserTrendOption(rows, userLabel) {
    const dates = (rows || []).map((item) => String(item.stat_date || ""));
    const totalMinutes = (rows || []).map((item) => Number(item.total_minutes || 0));
    const sessionCount = (rows || []).map((item) => Number(item.session_count || 0));

    return {
      backgroundColor: "transparent",
      animationDuration: 800,
      title: {
        text: `${userLabel}`,
        left: 0,
        textStyle: { color: brandColors.textMain, fontSize: 16, fontWeight: 600, fontFamily: chartFontFamily },
      },
      tooltip: { ...tooltipBase, trigger: "axis" },
      legend: {
        top: 0,
        right: 0,
        icon: 'circle',
        textStyle: { color: brandColors.textMuted, fontFamily: chartFontFamily },
        data: ["时长 (分钟)", "打卡次数"],
      },
      grid: { top: 40, left: 45, right: 20, bottom: 25 },
      xAxis: {
        type: "category",
        data: dates,
        axisLabel: { color: brandColors.textMuted, formatter: compactDate },
        axisLine: { lineStyle: { color: brandColors.gridLine } },
        axisTick: { show: false },
      },
      yAxis: [
        {
          type: "value",
          axisLabel: { color: brandColors.textMuted },
          splitLine: { lineStyle: { color: brandColors.gridLine, type: 'dashed' } },
        },
        {
          type: "value",
          axisLabel: { color: brandColors.textMuted },
          splitLine: { show: false },
        },
      ],
      series: [
        {
          name: "时长 (分钟)",
          type: "bar",
          yAxisIndex: 0,
          barWidth: "30%",
          itemStyle: {
            color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
              { offset: 0, color: '#3b82f6' },
              { offset: 1, color: '#1d4ed8' }
            ]),
            borderRadius: [6, 6, 0, 0],
          },
          data: totalMinutes,
        },
        {
          name: "打卡次数",
          type: "line",
          yAxisIndex: 1,
          smooth: true,
          symbolSize: 8,
          symbol: 'circle',
          itemStyle: { color: brandColors.accent2, borderColor: '#fff', borderWidth: 2 },
          lineStyle: { width: 3, color: brandColors.accent2 },
          data: sessionCount,
        },
      ],
    };
  }

  function buildHourlyBarOption(rows, title, colorStart, colorEnd) {
    const hours = Array.from({ length: 24 }, (_, hour) => hour);
    const counts = Array.from({ length: 24 }, () => 0);
    for (const row of rows || []) {
      const hour = Number(row.hour || 0);
      counts[hour] = Number(row.count || 0);
    }

    return {
      backgroundColor: "transparent",
      animationDuration: 700,
      title: {
        text: title,
        left: 0,
        textStyle: { color: brandColors.textMain, fontSize: 14, fontWeight: 500, fontFamily: chartFontFamily },
      },
      tooltip: {
        ...tooltipBase,
        trigger: "axis",
        formatter(params) {
          if (!params || !params.length) return "";
          const item = params[0];
          return `<div style="color:${brandColors.textMuted}">${item.axisValue}:00 - ${parseInt(item.axisValue) + 1}:00</div>
                  <div style="font-weight:600;margin-top:4px;font-size:14px;color:${colorStart}">频次: ${item.value}</div>`;
        },
      },
      grid: { top: 35, left: 30, right: 10, bottom: 25 },
      xAxis: {
        type: "category",
        data: hours,
        axisLabel: { color: brandColors.textMuted, fontSize: 11, interval: 2 },
        axisLine: { lineStyle: { color: brandColors.gridLine } },
        axisTick: { show: false },
      },
      yAxis: {
        type: "value",
        axisLabel: { color: brandColors.textMuted, fontSize: 11 },
        splitLine: { lineStyle: { color: brandColors.gridLine, type: 'dashed' } },
      },
      series: [
        {
          type: "bar",
          data: counts,
          barWidth: "50%",
          itemStyle: {
            color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
              { offset: 0, color: colorStart },
              { offset: 1, color: colorEnd }
            ]),
            borderRadius: [4, 4, 0, 0],
          },
          emphasis: {
            itemStyle: { opacity: 0.8 }
          }
        },
      ],
    };
  }

  function buildSleepHourlyOption(rows) {
    return buildHourlyBarOption(rows, "入睡习惯时段", "#6366f1", "#4338ca");
  }

  function buildWakeHourlyOption(rows) {
    return buildHourlyBarOption(rows, "起床习惯时段", "#10b981", "#047857");
  }

  function fallbackTrendTable(rows) {
    if (!rows || rows.length === 0) {
      return "<div class='premium-empty-state minimal'><p>暂无趋势数据</p></div>";
    }
    return `
      <div class="table-container-premium" style="max-height: 300px; margin-top:0; border:none; box-shadow:none;">
        <table class="md3-table" style="margin:0;">
          <thead>
            <tr><th>日期</th><th>时长(分)</th><th>会话</th><th>活跃用户</th></tr>
          </thead>
          <tbody>
            ${rows
        .map(
          (row) => `
                  <tr>
                    <td>${row.stat_date || "-"}</td>
                    <td><span class="md3-badge neutral">${row.total_minutes || 0}</span></td>
                    <td>${row.session_count || 0}</td>
                    <td>${row.active_user_count || 0}</td>
                  </tr>
                `
        )
        .join("")}
          </tbody>
        </table>
      </div>
    `;
  }

  window.OyasumiCharts = {
    buildHeatmapOption,
    buildGroupTrendOption,
    buildUserTrendOption,
    buildSleepHourlyOption,
    buildWakeHourlyOption,
    fallbackTrendTable,
    minutesToHourText,
  };
})();
