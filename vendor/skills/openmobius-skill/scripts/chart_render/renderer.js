// renderer.js — panels 协议 → lightweight-charts 图元。
// 从 chart-web/frontend/src/chart/renderer.ts 移植（去 TS，去 React）。
//
// 用法（在 index.html 中）:
//   const handle = QKRenderer.renderPayload(rootEl, payload, theme);
//   handle.dispose();  // 切换主题/数据时清理
//
// payload schema (与 chart-web types.ts 一致):
//   {
//     symbol: 'BTCUSDT', interval: '1h',
//     klines: [{ time: 1700000000, open, high, low, close, volume }, ...],
//     panels: [
//       { id: 'main', overlay: true, height_ratio: 3.0, items: [...] },
//       { id: 'rsi', overlay: false, height_ratio: 1.0, value_range: [0,100], items: [...] }
//     ]
//   }

(function() {
  const LWC = window.LightweightCharts;
  if (!LWC) {
    console.error('lightweight-charts 未加载');
    return;
  }
  const { createChart, LineStyle, CrosshairMode } = LWC;
  const { colorFor } = window.QKTheme;
  const QKRect = window.QKRectangle; // 可能 undefined（如果没加载 rectangle_primitive.js）

  // ── 主入口 ────────────────────────────────────────────────────────────────
  function renderPayload(root, payload, theme) {
    root.innerHTML = '';
    root.style.display = 'flex';
    root.style.flexDirection = 'column';
    root.style.width = '100%';
    root.style.height = '100%';

    const charts = [];
    const panels = payload.panels || [];
    const lastIdx = panels.length - 1;

    panels.forEach((panel, idx) => {
      const div = document.createElement('div');
      div.style.flex = `${panel.height_ratio || 1} 1 0`;
      div.style.minHeight = '80px';
      div.style.position = 'relative';
      if (idx !== 0) {
        div.style.borderTop = `1px solid ${theme.border}`;
      }
      root.appendChild(div);

      const chart = createChart(div, buildChartOptions(theme, idx === lastIdx));
      charts.push(chart);
      renderPanel(chart, panel, payload, theme);
    });

    // K 线左对齐 + 两侧留间隙
    // 左边 LEFT_GAP 根 bar 空白（不顶到画布左边），右边 RIGHT_GAP 根（给 hline label）
    const klineCount = (payload.klines || []).length;
    if (klineCount > 0) {
      const LEFT_GAP = 3;
      const RIGHT_GAP = 20;
      charts.forEach(chart => {
        chart.timeScale().setVisibleLogicalRange({
          from: -LEFT_GAP,
          to:   klineCount - 1 + RIGHT_GAP,
        });
      });
    }

    // 同步 timeScale（多 panel 时联动）
    wireTimeScaleSync(charts);

    return {
      dispose() {
        charts.forEach(c => c.remove());
        root.innerHTML = '';
      },
    };
  }

  // ── Panel 渲染 ─────────────────────────────────────────────────────────────
  function renderPanel(chart, panel, payload, theme) {
    let anchor = null;

    // 主图（overlay = true）铺 K 线
    if (panel.overlay) {
      const candle = chart.addCandlestickSeries({
        upColor: theme.upColor,
        downColor: theme.downColor,
        borderVisible: false,
        wickUpColor: theme.upColor,
        wickDownColor: theme.downColor,
        priceLineVisible: false,
      });
      candle.setData((payload.klines || []).map(k => ({
        time: k.time,
        open: k.open,
        high: k.high,
        low: k.low,
        close: k.close,
      })));
      anchor = candle;

      // 如果 panel 给了 value_range，锚定 priceScale 让 K 线不被 hline 拉变形
      applyValueRange(chart, panel, payload.klines || []);
    }

    const items = panel.items || [];

    // Pass 1: 画带数据的 series（line / histogram / area / band）
    for (const item of items) {
      if (item.type === 'hline' || item.type === 'markers' || item.type === 'rectangle') continue;
      const s = renderSeriesItem(chart, item, theme);
      if (s && !anchor) anchor = s;
    }

    // Pass 2: 需要 anchor 的 item（hline / markers / rectangle）
    const needsAnchor = items.some(i =>
      i.type === 'hline' || i.type === 'markers' || i.type === 'rectangle'
    );
    if (!anchor && needsAnchor) {
      anchor = chart.addLineSeries({ color: 'transparent', priceLineVisible: false });
    }
    // Accumulate markers across all `markers` items so we only call setMarkers
    // once (lightweight-charts' setMarkers replaces, not appends).
    const allMarkers = [];
    for (const item of items) {
      if (item.type === 'hline') {
        if (!anchor) continue;
        renderHline(anchor, item, theme);
      } else if (item.type === 'markers') {
        if (!anchor) continue;
        const itemColor = colorFor(theme, item.style && item.style.role, theme.roles.muted);
        for (const m of (item.data || [])) {
          if (m.time == null) continue;
          allMarkers.push({
            time:     m.time,
            position: m.position || 'aboveBar',
            color:    m.color || itemColor,
            shape:    m.shape || 'circle',
            text:     m.text || '',
            size:     m.size,
          });
        }
      } else if (item.type === 'rectangle') {
        if (!anchor) continue;
        attachRectangle(anchor, item, theme);
      }
    }
    if (anchor && allMarkers.length) {
      allMarkers.sort((a, b) => (a.time || 0) - (b.time || 0));
      anchor.setMarkers(allMarkers);
    }
  }

  // ── rectangle (ISeriesPrimitive plugin) ────────────────────────────────
  function attachRectangle(series, item, theme) {
    if (!QKRect) {
      console.warn('QKRectangle plugin 未加载，跳过 rectangle item');
      return;
    }
    const style = item.style || {};
    const role = style.role;
    const baseColor = colorFor(theme, role, theme.roles.muted);
    const opacity = style.fill_opacity != null ? style.fill_opacity : 0.15;
    const borderWidth = style.border_width != null ? style.border_width : 1;
    const dashStr = style.dash;
    const borderDash = dashStr === 'dashed' ? [6, 4]
                     : dashStr === 'dotted' ? [2, 3]
                     : null;
    const primitive = new QKRect.RectanglePrimitive({
      time_start:   item.time_start,
      time_end:     item.time_end,        // null/undefined → 延伸到右
      price_top:    item.price_top,
      price_bottom: item.price_bottom,
      fillColor:    QKRect.hexToRgba(baseColor, opacity),
      borderColor:  baseColor,
      borderWidth:  borderWidth,
      borderDash:   borderDash,
      label:        item.label,
      labelColor:   baseColor,
    });
    series.attachPrimitive(primitive);
  }

  // ── 单 item 渲染（有数据系列） ─────────────────────────────────────────────
  function renderSeriesItem(chart, item, theme) {
    const color = colorFor(theme, item.style && item.style.role, theme.roles.muted);
    const lineWidth = (item.style && item.style.width) || 2;
    const dash = item.style && item.style.dash;
    const lineStyle =
      dash === 'dashed' ? LineStyle.Dashed :
      dash === 'dotted' ? LineStyle.Dotted :
      LineStyle.Solid;

    switch (item.type) {
      case 'line': {
        const lvv = (item.style && item.style.lastValueVisible);
        const s = chart.addLineSeries({
          color, lineWidth, lineStyle,
          priceLineVisible: false,
          // Default false so dense BOS/CHoCH dashed connectors don't clutter
          // the right axis with price labels; opt in via style.lastValueVisible.
          lastValueVisible: lvv === true,
          crosshairMarkerVisible: false,
          title: item.label || '',
        });
        s.setData((item.data || []).map(p => ({ time: p.time, value: p.value })));
        return s;
      }
      case 'histogram': {
        const s = chart.addHistogramSeries({
          color,
          base: (item.style && item.style.baseline) != null ? item.style.baseline : 0,
          priceLineVisible: false,
          lastValueVisible: !!(item.style && item.style.lastValueVisible),
          title: item.label || '',
        });
        // Per-bar color via `color` field on each data point (used for volume:
        // green when close > open, red when close < open). Falls back to series color.
        s.setData((item.data || []).map(p => {
          const d = { time: p.time, value: p.value };
          if (p.color) d.color = p.color;
          return d;
        }));
        return s;
      }
      case 'area': {
        const s = chart.addAreaSeries({
          lineColor: color,
          topColor: color + '55',
          bottomColor: color + '00',
          priceLineVisible: false,
          title: item.label || '',
        });
        s.setData((item.data || []).map(p => ({ time: p.time, value: p.value })));
        return s;
      }
      case 'band': {
        const upper = chart.addLineSeries({
          color, lineWidth: 1, lineStyle: LineStyle.Solid,
          priceLineVisible: false, title: item.label || '',
        });
        upper.setData((item.upperData || []).map(p => ({ time: p.time, value: p.value })));
        const lower = chart.addLineSeries({
          color, lineWidth: 1, lineStyle: LineStyle.Solid,
          priceLineVisible: false,
        });
        lower.setData((item.lowerData || []).map(p => ({ time: p.time, value: p.value })));
        return upper;
      }
      default:
        return null;
    }
  }

  // ── hline 渲染（markers 已在主循环统一收集） ─────────────────────────────
  function renderHline(anchor, item, theme) {
    const color = colorFor(theme, item.style && item.style.role, theme.roles.muted);
    const dash = item.style && item.style.dash;
    const lineStyle =
      dash === 'dashed' ? LineStyle.Dashed :
      dash === 'dotted' ? LineStyle.Dotted :
      LineStyle.Solid;
    anchor.createPriceLine({
      price: item.value,
      color,
      lineWidth: (item.style && item.style.width) || 1,
      lineStyle,
      axisLabelVisible: (item.style && item.style.axisLabelVisible !== false),
      title: item.label || '',
    });
  }

  // ── Chart 选项 ─────────────────────────────────────────────────────────────
  function buildChartOptions(theme, isLast) {
    return {
      layout: {
        background: { color: theme.background },
        textColor: theme.text,
      },
      grid: {
        vertLines: { color: theme.grid },
        horzLines: { color: theme.grid },
      },
      crosshair: { mode: CrosshairMode.Normal },
      rightPriceScale: {
        borderColor: theme.border,
        scaleMargins: { top: 0.08, bottom: 0.08 },
      },
      timeScale: {
        borderColor: theme.border,
        timeVisible: isLast,
        secondsVisible: false,
        visible: isLast,
        rightOffset: 20,             // 右边留 20 根 bar 宽度，给 hline label 腾位置
        barSpacing: 6,
      },
      autoSize: true,
    };
  }

  // ── 应用 panel.value_range：通过 invisible anchor series 撑大 priceScale ──
  // 让 K 线 ±buffer 范围一定被包含，hline 在 buffer 内时不会再拉伸 scale。
  // (lightweight-charts 没有硬 min/max API，这是社区惯用 hack)
  function applyValueRange(chart, panel, klines) {
    const vr = panel.value_range;
    if (!Array.isArray(vr) || vr.length !== 2) return;
    if (!klines || klines.length < 2) return;
    const lo = Math.min(vr[0], vr[1]);
    const hi = Math.max(vr[0], vr[1]);
    try {
      const anchor = chart.addLineSeries({
        color:                  'rgba(0,0,0,0)',
        priceLineVisible:       false,
        lastValueVisible:       false,
        crosshairMarkerVisible: false,
      });
      const t0 = klines[0].time;
      const t1 = klines[klines.length - 1].time;
      anchor.setData([
        { time: t0, value: lo },
        { time: t1, value: hi },
      ]);
    } catch (e) {
      console.warn('applyValueRange failed:', e);
    }
  }

  // ── TimeScale 同步 ─────────────────────────────────────────────────────────
  function wireTimeScaleSync(charts) {
    let syncing = false;
    charts.forEach((src, i) => {
      src.timeScale().subscribeVisibleLogicalRangeChange(range => {
        if (syncing || !range) return;
        syncing = true;
        charts.forEach((dst, j) => {
          if (i !== j) dst.timeScale().setVisibleLogicalRange(range);
        });
        syncing = false;
      });
    });
  }

  // 暴露
  window.QKRenderer = { renderPayload };
})();
