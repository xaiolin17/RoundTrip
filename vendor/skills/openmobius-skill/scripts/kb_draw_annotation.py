#!/usr/bin/env python3
"""Draw annotations on a trading chart image.

Pure-Python drawing tool (Pillow). Receives an annotation JSON describing
- chart bounding box(es)
- price axis range per panel
- a list of annotations (horizontal_line, rectangle)
- theme (dark/light)

and produces an annotated image. Designed to be called by the kb-annotate-chart
skill after the platform LLM has determined chart_bbox + y_axis_range + annotations.

Usage:
    # JSON file mode
    python scripts/kb_draw_annotation.py --json annotation.json

    # Inline JSON
    python scripts/kb_draw_annotation.py \\
        --input chart.png \\
        --output chart_annotated.png \\
        --bbox "50,30,800,400" \\
        --y-range "70000,96000" \\
        --annotations '[{"type":"horizontal_line","price":73000,"label":"Entry","color":"#00ff88"}]'

JSON schema:
    {
      "input_image": "/path/to/chart.png",
      "output_image": "/path/to/chart_annotated.png",
      "theme": "dark" | "light",
      "panels": [
        {
          "panel_id": "main",
          "chart_bbox": {"x": 50, "y": 30, "width": 800, "height": 400},
          "y_axis_range": {"top": 96000, "bottom": 70000},
          "annotations": [
            {"type": "horizontal_line", "price": 73000, "label": "Entry",
             "color": "#00ff88", "style": "solid", "label_position": "right"},
            {"type": "rectangle", "price_top": 74500, "price_bottom": 73000,
             "x_pct_start": 0.6, "x_pct_end": 1.0, "label": "FVG",
             "fill_color": "#00ff8830", "border_color": "#00ff88"}
          ]
        }
      ]
    }
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from PIL import Image, ImageDraw, ImageFont


log = logging.getLogger("kb_draw_annotation")

# ============================================================================
# Theme palette
# ============================================================================

THEMES = {
    "dark": {
        "default_text": "#ffffff",
        "label_outline": "#000000",
        "label_bg_alpha": 200,
    },
    "light": {
        "default_text": "#000000",
        "label_outline": "#ffffff",
        "label_bg_alpha": 200,
    },
}

# Default semantic colors（used when JSON 没有显式指定 color）
DEFAULT_COLORS = {
    "entry_long":     "#00ff88",
    "entry_short":    "#ff4444",
    "stop_loss":      "#ff4444",
    "target":         "#4488ff",
    "fvg_bullish":    "#00ff88",
    "fvg_bearish":    "#ff8844",
    "order_block":    "#aa55ff",
    "breaker_block":  "#aa55ff",
    "liquidity":      "#ffaa00",
}


# ============================================================================
# Font loading
# ============================================================================

# CJK 字体 — label 可能含中文，必须先匹配支持 CJK 的字体；
# 否则 DejaVu 等纯拉丁字体会把中文渲染成 "口口口" 乱码
CJK_FONT_CANDIDATES = [
    # macOS
    "/System/Library/Fonts/PingFang.ttc",
    "/System/Library/Fonts/STHeiti Medium.ttc",
    "/Library/Fonts/Arial Unicode.ttf",
    # Linux（Noto / 文泉驿 / 思源黑体）
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
    "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
    "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
    "/usr/share/fonts/opentype/source-han-sans/SourceHanSansSC-Regular.otf",
    # Windows
    "C:\\Windows\\Fonts\\msyh.ttc",      # Microsoft YaHei
    "C:\\Windows\\Fonts\\simhei.ttf",    # SimHei
]

# 纯拉丁字体兜底（仅当系统完全无 CJK 字体时用，会导致中文乱码）
LATIN_FALLBACK_FONTS = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf",
    "/System/Library/Fonts/Helvetica.ttc",
    "C:\\Windows\\Fonts\\arial.ttf",
]

# 兼容旧引用（如 kb_doctor.py 早期读这个列表）
FONT_CANDIDATES = CJK_FONT_CANDIDATES + LATIN_FALLBACK_FONTS


def _cjk_install_hint() -> str:
    """根据当前 OS 给出 CJK 字体安装命令。"""
    if sys.platform == "linux":
        return (
            "  Debian/Ubuntu: sudo apt install fonts-noto-cjk\n"
            "  Fedora/RHEL:   sudo dnf install google-noto-cjk-fonts\n"
            "  Arch:          sudo pacman -S noto-fonts-cjk"
        )
    if sys.platform == "darwin":
        return "  macOS 通常自带 PingFang.ttc — 请检查 /System/Library/Fonts/"
    if sys.platform == "win32":
        return "  Windows 通常自带 msyh.ttc / simhei.ttf — 请检查 C:\\Windows\\Fonts\\"
    return "  请安装任意 Noto Sans CJK / 文泉驿 / PingFang / SimHei / Microsoft YaHei 字体"


def _load_font(size: int = 14) -> ImageFont.FreeTypeFont:
    """加载第一个可用的字体（CJK 优先）。

    没有 CJK 字体时打明确警告并用拉丁字体兜底（中文 label 会渲染为方块）。
    """
    # 1) 找 CJK 字体
    for path in CJK_FONT_CANDIDATES:
        if Path(path).is_file():
            try:
                return ImageFont.truetype(path, size=size)
            except Exception:  # noqa: BLE001
                continue

    # 2) 没找到 → 显式警告 + 兜底
    log.warning(
        "⚠️  未找到 CJK 字体 — 中文 label 将渲染为方块 (口口口)。\n"
        "%s\n"
        "或运行 `python scripts/kb_doctor.py` 做完整环境体检。",
        _cjk_install_hint(),
    )
    for path in LATIN_FALLBACK_FONTS:
        if Path(path).is_file():
            try:
                return ImageFont.truetype(path, size=size)
            except Exception:  # noqa: BLE001
                continue
    log.warning("No TTF font found; using PIL default (very limited).")
    return ImageFont.load_default()


# ============================================================================
# Color utilities
# ============================================================================

def _parse_color(s: str) -> tuple[int, int, int, int]:
    """'#rrggbb' / '#rrggbbaa' → (r,g,b,a). Default alpha = 255."""
    if not s:
        return (255, 255, 255, 255)
    s = s.strip().lstrip("#")
    if len(s) == 6:
        return (int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16), 255)
    if len(s) == 8:
        return (int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16), int(s[6:8], 16))
    raise ValueError(f"unsupported color: {s!r}")


# ============================================================================
# Panel + coordinate translation
# ============================================================================

@dataclass
class Panel:
    panel_id: str
    bbox_x: int
    bbox_y: int
    bbox_w: int
    bbox_h: int
    y_top: float       # price at top of bbox
    y_bottom: float    # price at bottom of bbox
    annotations: list[dict]

    @classmethod
    def from_dict(cls, d: dict) -> "Panel":
        bbox = d.get("chart_bbox") or {}
        yrange = d.get("y_axis_range") or {}
        return cls(
            panel_id=d.get("panel_id") or "main",
            bbox_x=int(bbox.get("x", 0)),
            bbox_y=int(bbox.get("y", 0)),
            bbox_w=int(bbox.get("width", 0)),
            bbox_h=int(bbox.get("height", 0)),
            y_top=float(yrange.get("top", 0)),
            y_bottom=float(yrange.get("bottom", 0)),
            annotations=list(d.get("annotations") or []),
        )

    def price_to_y(self, price: float) -> float:
        """Convert price to pixel y (within panel bbox)."""
        if self.y_top == self.y_bottom:
            return self.bbox_y + self.bbox_h / 2  # degenerate fallback
        rel = (price - self.y_bottom) / (self.y_top - self.y_bottom)
        rel = max(0.0, min(1.0, rel))
        return self.bbox_y + self.bbox_h * (1 - rel)

    def x_pct_to_pixel(self, pct: float) -> float:
        return self.bbox_x + self.bbox_w * pct

    def clip_y_to_bbox(self, y: float) -> float:
        return max(self.bbox_y, min(self.bbox_y + self.bbox_h, y))


# ============================================================================
# Drawing primitives
# ============================================================================

def _draw_horizontal_line(
    overlay: Image.Image,
    draw: ImageDraw.ImageDraw,
    panel: Panel,
    ann: dict,
    font: ImageFont.FreeTypeFont,
    theme: dict,
) -> tuple[float, float, str]:
    """Draw a horizontal price line; return (y, label_x, label_str) for label layout."""
    price = float(ann["price"])
    color = _parse_color(ann.get("color") or DEFAULT_COLORS["target"])
    style = ann.get("style", "solid")
    label = ann.get("label", "")
    label_pos = ann.get("label_position", "right")  # right / left

    y = panel.price_to_y(price)

    x0 = panel.bbox_x
    x1 = panel.bbox_x + panel.bbox_w

    if style == "dashed":
        # Manual dashed line: 8px on / 4px off
        dash = 8
        gap = 4
        x = x0
        while x < x1:
            xe = min(x + dash, x1)
            draw.line([(x, y), (xe, y)], fill=color, width=2)
            x = xe + gap
    else:
        draw.line([(x0, y), (x1, y)], fill=color, width=2)

    # Decide label x
    label_text = f"{label}  {price:g}" if label else f"{price:g}"
    label_x = x1 + 6 if label_pos == "right" else x0 - 6
    return (y, label_x, label_text)


def _draw_rectangle(
    overlay: Image.Image,
    draw: ImageDraw.ImageDraw,
    panel: Panel,
    ann: dict,
    font: ImageFont.FreeTypeFont,
    theme: dict,
) -> Optional[tuple[float, float, str]]:
    """Draw a price-range rectangle (FVG / OB / Breaker / etc.).

    Returns label anchor info for layout, or None if no label.
    """
    p_top = float(ann["price_top"])
    p_bot = float(ann["price_bottom"])
    fill = _parse_color(ann.get("fill_color") or "#00ff8830")
    border = _parse_color(ann.get("border_color") or fill[:3] + (255,))
    label = ann.get("label", "")
    x_start = panel.x_pct_to_pixel(float(ann.get("x_pct_start", 0.0)))
    x_end = panel.x_pct_to_pixel(float(ann.get("x_pct_end", 1.0)))

    y_top = panel.clip_y_to_bbox(panel.price_to_y(p_top))
    y_bot = panel.clip_y_to_bbox(panel.price_to_y(p_bot))
    if y_top > y_bot:
        y_top, y_bot = y_bot, y_top

    # Fill with alpha onto overlay
    draw.rectangle([(x_start, y_top), (x_end, y_bot)], fill=fill, outline=border, width=2)

    if label:
        # Label anchor: top-left of rectangle, inside or just above
        return (y_top - 4, x_end + 6, f"{label}")
    return None


def _draw_label(
    overlay: Image.Image,
    draw: ImageDraw.ImageDraw,
    text: str,
    x: float,
    y: float,
    color: tuple[int, int, int, int],
    font: ImageFont.FreeTypeFont,
    theme: dict,
    image_size: Optional[tuple[int, int]] = None,
) -> None:
    """Draw a text label with a contrasting outline + semi-transparent bg.

    If image_size is given, clamp the label box to stay fully inside the image
    (auto-flip from right to inside-right when overflowing the right edge).
    """
    # Measure text size first
    tmp_bbox = draw.textbbox((x, y), text, font=font, anchor="lm")
    text_w = tmp_bbox[2] - tmp_bbox[0]
    text_h = tmp_bbox[3] - tmp_bbox[1]
    pad_x, pad_y = 4, 2

    # Clamp to image bounds
    if image_size is not None:
        img_w, img_h = image_size
        # Horizontal: if overflows right, push inside; if overflows left, snap to left
        if x + text_w + pad_x > img_w - 2:
            x = img_w - text_w - pad_x - 2
        if x < pad_x + 2:
            x = pad_x + 2
        # Vertical: keep within image
        if y - text_h / 2 < pad_y + 2:
            y = text_h / 2 + pad_y + 2
        if y + text_h / 2 > img_h - pad_y - 2:
            y = img_h - text_h / 2 - pad_y - 2

    # Re-measure at final position
    bbox = draw.textbbox((x, y), text, font=font, anchor="lm")
    bg_box = (
        bbox[0] - pad_x, bbox[1] - pad_y,
        bbox[2] + pad_x, bbox[3] + pad_y,
    )
    outline_rgba = _parse_color(theme["label_outline"])
    bg_rgba = (outline_rgba[0], outline_rgba[1], outline_rgba[2], theme["label_bg_alpha"])
    draw.rectangle(bg_box, fill=bg_rgba)
    draw.text((x, y), text, fill=color[:3] + (255,), font=font, anchor="lm")


def _deconflict_labels(
    label_anchors: list[tuple[float, float, str, tuple]],
    min_gap: int = 16,
) -> list[tuple[float, float, str, tuple]]:
    """简单标签避让：按 y 排序，相邻太近的下移；保留 (y, x, text, color)。"""
    # sort by y
    sorted_anchors = sorted(label_anchors, key=lambda a: a[0])
    out = []
    last_y = -1000.0
    for y, x, text, color in sorted_anchors:
        if y - last_y < min_gap:
            y = last_y + min_gap
        out.append((y, x, text, color))
        last_y = y
    return out


# ============================================================================
# Main pipeline
# ============================================================================

def annotate_image(cfg: dict) -> Path:
    """Process the full annotation config and produce the output image."""
    input_path = Path(cfg["input_image"])
    output_path = Path(cfg["output_image"])
    if not input_path.is_file():
        raise FileNotFoundError(f"input_image not found: {input_path}")

    theme_name = (cfg.get("theme") or "dark").lower()
    theme = THEMES.get(theme_name, THEMES["dark"])
    font = _load_font(size=cfg.get("font_size", 14))

    base = Image.open(input_path).convert("RGBA")
    overlay = Image.new("RGBA", base.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    panels = cfg.get("panels") or []
    if not panels:
        log.warning("no panels in config; nothing to draw.")
    n_anns = 0
    for p_dict in panels:
        panel = Panel.from_dict(p_dict)
        # Sanity check
        if panel.bbox_w <= 0 or panel.bbox_h <= 0:
            log.warning("panel %r has invalid bbox; skipping", panel.panel_id)
            continue
        if panel.y_top == panel.y_bottom:
            log.warning("panel %r has degenerate y range; skipping", panel.panel_id)
            continue

        # Collect label anchors so we can deconflict per panel
        line_anchors: list[tuple[float, float, str, tuple]] = []
        rect_anchors: list[tuple[float, float, str, tuple]] = []

        for ann in panel.annotations:
            t = ann.get("type")
            try:
                if t == "horizontal_line":
                    y, lx, ltext = _draw_horizontal_line(overlay, draw, panel, ann, font, theme)
                    color = _parse_color(ann.get("color") or DEFAULT_COLORS["target"])
                    line_anchors.append((y, lx, ltext, color))
                    n_anns += 1
                elif t == "rectangle":
                    res = _draw_rectangle(overlay, draw, panel, ann, font, theme)
                    if res:
                        y, lx, ltext = res
                        color = _parse_color(ann.get("border_color") or "#ffffff")
                        rect_anchors.append((y, lx, ltext, color))
                    n_anns += 1
                else:
                    log.warning("unknown annotation type %r; skipping", t)
            except Exception as e:  # noqa: BLE001
                log.exception("failed to draw annotation %s: %s", ann, e)

        # Deconflict + render labels (with image-bounds clamping)
        img_size = base.size  # (width, height)
        for anchor_list in (line_anchors, rect_anchors):
            for y, x, text, color in _deconflict_labels(anchor_list):
                _draw_label(overlay, draw, text, x, y, color, font, theme, image_size=img_size)

    # Composite
    final = Image.alpha_composite(base, overlay).convert("RGB")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    # Use PNG if extension is png; else preserve source format
    final.save(output_path)
    log.info("Annotated image saved: %s (%d annotations)", output_path, n_anns)
    return output_path


# ============================================================================
# CLI
# ============================================================================

def _parse_bbox(s: str) -> dict:
    """'x,y,w,h' → dict"""
    parts = [int(p.strip()) for p in s.split(",")]
    if len(parts) != 4:
        raise ValueError(f"bbox must be 'x,y,w,h', got {s!r}")
    return {"x": parts[0], "y": parts[1], "width": parts[2], "height": parts[3]}


def _parse_y_range(s: str) -> dict:
    """'bottom,top' or 'top,bottom' — we sort so top > bottom semantically"""
    parts = [float(p.strip()) for p in s.split(",")]
    if len(parts) != 2:
        raise ValueError(f"y-range must be 'top,bottom', got {s!r}")
    top, bottom = max(parts), min(parts)
    return {"top": top, "bottom": bottom}


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)-5s %(message)s")

    p = argparse.ArgumentParser(description="Draw annotations on a chart image.")
    p.add_argument("--json", help="Path to annotation JSON file (full config)")

    # Inline (single panel) shortcut
    p.add_argument("--input", help="Input image path")
    p.add_argument("--output", help="Output image path")
    p.add_argument("--bbox", help="chart_bbox as 'x,y,w,h' (single panel mode)")
    p.add_argument("--y-range", help="y_axis_range as 'top,bottom' (single panel mode)")
    p.add_argument(
        "--annotations",
        help="JSON-encoded list of annotations (single panel mode)",
    )
    p.add_argument("--theme", default="dark", choices=["dark", "light"])
    p.add_argument("--font-size", type=int, default=14)
    args = p.parse_args()

    if args.json:
        cfg = json.loads(Path(args.json).read_text(encoding="utf-8"))
    else:
        # Build cfg from inline args
        if not (args.input and args.output and args.bbox and args.y_range and args.annotations):
            p.error("either --json, or all of --input/--output/--bbox/--y-range/--annotations")
        cfg = {
            "input_image": args.input,
            "output_image": args.output,
            "theme": args.theme,
            "font_size": args.font_size,
            "panels": [{
                "panel_id": "main",
                "chart_bbox": _parse_bbox(args.bbox),
                "y_axis_range": _parse_y_range(args.y_range),
                "annotations": json.loads(args.annotations),
            }],
        }

    try:
        out = annotate_image(cfg)
        print(str(out))
        return 0
    except Exception as e:  # noqa: BLE001
        log.exception("annotation failed: %s", e)
        return 1


if __name__ == "__main__":
    sys.exit(main())
