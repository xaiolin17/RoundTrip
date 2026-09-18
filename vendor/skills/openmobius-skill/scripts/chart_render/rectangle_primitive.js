// rectangle_primitive.js — lightweight-charts ISeriesPrimitive
// 画一个 time×price 范围的矩形（带半透明 fill + 边框 + label）。
//
// 使用：
//   const rect = new RectanglePrimitive({
//     time_start:    1700000000,         // 秒
//     time_end:      1700036000,         // 秒（null/undefined → 延伸到右边界）
//     price_top:     74210,
//     price_bottom:  73182,
//     fillColor:     '#26a69a',
//     fillOpacity:   0.15,
//     borderColor:   '#26a69a',
//     borderWidth:   1,
//     borderDash:    [4, 4],             // null = solid
//     label:         'bullish FVG',
//     labelColor:    '#26a69a',
//   });
//   candleSeries.attachPrimitive(rect);

(function() {
  // ── helper ──────────────────────────────────────────────────────────────
  function hexToRgba(hex, alpha) {
    if (!hex) return 'rgba(128,128,128,' + alpha + ')';
    hex = hex.replace('#', '');
    let r, g, b, a = alpha;
    if (hex.length === 6) {
      r = parseInt(hex.slice(0, 2), 16);
      g = parseInt(hex.slice(2, 4), 16);
      b = parseInt(hex.slice(4, 6), 16);
    } else if (hex.length === 8) {
      r = parseInt(hex.slice(0, 2), 16);
      g = parseInt(hex.slice(2, 4), 16);
      b = parseInt(hex.slice(4, 6), 16);
      a = parseInt(hex.slice(6, 8), 16) / 255;
    } else {
      return hex;
    }
    return `rgba(${r},${g},${b},${a})`;
  }

  // ── Pane renderer ──────────────────────────────────────────────────────
  class RectanglePaneRenderer {
    constructor() {
      this._data = null;
    }
    update(data) {
      this._data = data;
    }
    draw(target) {
      const d = this._data;
      if (!d) return;
      if (d.x1 == null || d.x2 == null || d.y1 == null || d.y2 == null) return;

      target.useBitmapCoordinateSpace(scope => {
        const ctx = scope.context;
        const hr = scope.horizontalPixelRatio;
        const vr = scope.verticalPixelRatio;

        const xa = Math.round(Math.min(d.x1, d.x2) * hr);
        const xb = Math.round(Math.max(d.x1, d.x2) * hr);
        const ya = Math.round(Math.min(d.y1, d.y2) * vr);
        const yb = Math.round(Math.max(d.y1, d.y2) * vr);
        const w = Math.max(1, xb - xa);
        const h = Math.max(1, yb - ya);

        ctx.save();

        // Fill
        if (d.fillColor) {
          ctx.fillStyle = d.fillColor;
          ctx.fillRect(xa, ya, w, h);
        }

        // Border
        if (d.borderColor && d.borderWidth > 0) {
          ctx.strokeStyle = d.borderColor;
          ctx.lineWidth = Math.max(1, d.borderWidth * Math.min(hr, vr));
          if (d.borderDash && d.borderDash.length) {
            ctx.setLineDash(d.borderDash.map(v => v * Math.min(hr, vr)));
          }
          // 偏移半个 lineWidth 让边框对齐像素
          const off = ctx.lineWidth / 2;
          ctx.strokeRect(xa + off, ya + off, w - ctx.lineWidth, h - ctx.lineWidth);
        }

        // Label（左上内侧）
        if (d.label) {
          const fontPx = 12 * Math.min(hr, vr);
          ctx.font = `${fontPx}px system-ui, sans-serif`;
          ctx.textBaseline = 'top';
          // 文字背景以提高可读性
          const padding = 3 * Math.min(hr, vr);
          const txt = ctx.measureText(d.label);
          const txtW = txt.width;
          const txtH = fontPx;
          ctx.fillStyle = 'rgba(0,0,0,0.55)';
          ctx.fillRect(xa + padding, ya + padding,
                       txtW + padding * 2, txtH + padding);
          ctx.fillStyle = d.labelColor || d.borderColor || '#fff';
          ctx.fillText(d.label, xa + padding * 2, ya + padding * 1.5);
        }

        ctx.restore();
      });
    }
  }

  // ── Pane view ──────────────────────────────────────────────────────────
  class RectanglePaneView {
    constructor(source) {
      this._source = source;
      this._renderer = new RectanglePaneRenderer();
    }
    update() {
      const src = this._source;
      if (!src._chart || !src._series) return;
      const ts = src._chart.timeScale();
      const ser = src._series;
      const opts = src._options;

      const x1 = ts.timeToCoordinate(opts.time_start);
      let x2;
      if (opts.time_end == null) {
        x2 = ts.width();
      } else {
        x2 = ts.timeToCoordinate(opts.time_end);
        if (x2 == null) {
          // time_end 在可见范围之外 → 用 width 兜底
          x2 = ts.width();
        }
      }
      const y1 = ser.priceToCoordinate(opts.price_top);
      const y2 = ser.priceToCoordinate(opts.price_bottom);

      this._renderer.update({
        x1, x2, y1, y2,
        fillColor:   opts.fillColor,
        borderColor: opts.borderColor,
        borderWidth: opts.borderWidth || 0,
        borderDash:  opts.borderDash,
        label:       opts.label,
        labelColor:  opts.labelColor,
      });
    }
    renderer() { return this._renderer; }
    zOrder()   { return 'bottom'; }   // 画在 K 线后面，K 线压在矩形上
  }

  // ── Primitive ──────────────────────────────────────────────────────────
  class RectanglePrimitive {
    constructor(options) {
      this._options = options || {};
      this._chart = null;
      this._series = null;
      this._paneView = null;
    }
    attached(param) {
      this._chart = param.chart;
      this._series = param.series;
      this._paneView = new RectanglePaneView(this);
      // 首次 update
      this._paneView.update();
    }
    detached() {
      this._chart = null;
      this._series = null;
      this._paneView = null;
    }
    updateAllViews() {
      this._paneView && this._paneView.update();
    }
    paneViews() {
      return this._paneView ? [this._paneView] : [];
    }
  }

  // 暴露
  window.QKRectangle = { RectanglePrimitive, hexToRgba };
})();
