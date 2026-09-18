#!/usr/bin/env python3
"""Convert Phase B analysis JSON → Phase C annotation JSON (and optionally draw).

Phase B (kb-analyze-chart) outputs structured analysis with `patterns` + `trade_setup`.
Phase C needs `panels` with `chart_bbox` + `y_axis_range` + `annotations`.

This glue script:
- reads Phase B output
- accepts chart_bbox + y_axis_range from CLI (LLM-calibrated)
- maps Phase B fields to Phase C annotations using a fixed semantic color palette
- optionally invokes kb_draw_annotation.py to render the image

Usage:
    # Just convert JSON
    python scripts/kb_phase_b_to_c.py \\
        --input analysis.json \\
        --chart-bbox "50,30,800,400" \\
        --y-range "70000,96000" \\
        --output annotation.json

    # One-shot: convert + draw
    python scripts/kb_phase_b_to_c.py \\
        --input analysis.json \\
        --chart-bbox "50,30,800,400" \\
        --y-range "70000,96000" \\
        --image chart.png \\
        --output chart_annotated.png \\
        --theme dark
"""

from __future__ import annotations

import argparse
import json
import logging
import subprocess
import sys
from pathlib import Path
from typing import Any, Optional


log = logging.getLogger("kb_phase_b_to_c")

THIS_DIR = Path(__file__).resolve().parent

# Mapping from Phase B pattern.type → annotation color preset
PATTERN_STYLES = {
    # FVG family
    "fvg":          {"fill": "#00ff8830", "border": "#00ff88", "kind": "rectangle"},
    "fair value gap": {"fill": "#00ff8830", "border": "#00ff88", "kind": "rectangle"},
    "ifvg":         {"fill": "#ff884430", "border": "#ff8844", "kind": "rectangle"},
    "inversion fvg":{"fill": "#ff884430", "border": "#ff8844", "kind": "rectangle"},
    # Order block family
    "order block":  {"fill": "#aa55ff30", "border": "#aa55ff", "kind": "rectangle"},
    "ob":           {"fill": "#aa55ff30", "border": "#aa55ff", "kind": "rectangle"},
    "breaker block":{"fill": "#aa55ff30", "border": "#aa55ff", "kind": "rectangle"},
    "breaker":      {"fill": "#aa55ff30", "border": "#aa55ff", "kind": "rectangle"},
    "mitigation block": {"fill": "#5599ff30", "border": "#5599ff", "kind": "rectangle"},
    # Liquidity
    "liquidity sweep": {"color": "#ffaa00", "style": "dashed", "kind": "line"},
    "sell-side liquidity sweep": {"color": "#ffaa00", "style": "dashed", "kind": "line"},
    "buy-side liquidity sweep":  {"color": "#ffaa00", "style": "dashed", "kind": "line"},
    "sell-side liquidity": {"color": "#ffaa00", "style": "dashed", "kind": "line"},
    "buy-side liquidity":  {"color": "#ffaa00", "style": "dashed", "kind": "line"},
    # Zones
    "discount zone": {"fill": "#00ff8820", "border": "#00ff88", "kind": "rectangle"},
    "premium zone":  {"fill": "#ff444420", "border": "#ff4444", "kind": "rectangle"},
    # Reversal patterns (not directly drawable; we'll skip or use line)
    "v-shaped reversal": {"color": "#ffffff", "style": "dashed", "kind": "line"},
}

# Default for unknown pattern types
PATTERN_DEFAULT = {"fill": "#88888830", "border": "#888888", "kind": "rectangle"}

# Setup fields
ENTRY_COLOR_LONG = "#00ff88"
ENTRY_COLOR_SHORT = "#ff4444"
SL_COLOR = "#ff4444"
TARGET_COLOR = "#4488ff"


def _pattern_style(p_type: str, bias: str = "neutral") -> dict:
    """Find a style by pattern type (case-insensitive substring match)."""
    if not p_type:
        return PATTERN_DEFAULT
    key = p_type.lower().strip()
    # Direct match
    if key in PATTERN_STYLES:
        return PATTERN_STYLES[key]
    # Substring match
    for k, v in PATTERN_STYLES.items():
        if k in key:
            return v
    return PATTERN_DEFAULT


def _pattern_to_annotation(p: dict, bias: str = "neutral") -> Optional[dict]:
    """Convert a Phase B pattern entry → an annotation dict, or None if not drawable."""
    p_type = p.get("type", "")
    style = _pattern_style(p_type, bias=bias)
    label = p.get("label") or p_type
    rng = p.get("range")

    if style["kind"] == "rectangle":
        if not rng or len(rng) != 2:
            log.info("skip pattern %r: no usable range for rectangle", p_type)
            return None
        p_top, p_bot = max(rng), min(rng)
        return {
            "type": "rectangle",
            "price_top": p_top,
            "price_bottom": p_bot,
            "x_pct_start": 0.0,
            "x_pct_end": 1.0,
            "label": label,
            "fill_color": style["fill"],
            "border_color": style["border"],
        }
    elif style["kind"] == "line":
        if not rng:
            log.info("skip pattern %r: no level for line", p_type)
            return None
        # Use first value of range (or single level)
        price = rng[0] if isinstance(rng, list) else float(rng)
        return {
            "type": "horizontal_line",
            "price": price,
            "label": label,
            "color": style["color"],
            "style": style.get("style", "solid"),
        }
    return None


def _setup_to_annotations(setup: dict, bias: str = "neutral") -> list[dict]:
    """Convert Phase B trade_setup → list of horizontal_line annotations."""
    out: list[dict] = []
    # Entry
    entry = setup.get("entry")
    if entry and entry.get("price") is not None:
        color = ENTRY_COLOR_LONG if bias == "long" else (
            ENTRY_COLOR_SHORT if bias == "short" else ENTRY_COLOR_LONG
        )
        out.append({
            "type": "horizontal_line",
            "price": float(entry["price"]),
            "label": entry.get("label", "Entry"),
            "color": color,
            "style": "solid",
            "label_position": "right",
        })
    # Stop loss
    sl = setup.get("stop_loss")
    if sl and sl.get("price") is not None:
        out.append({
            "type": "horizontal_line",
            "price": float(sl["price"]),
            "label": sl.get("label", "SL"),
            "color": SL_COLOR,
            "style": "dashed",
            "label_position": "right",
        })
    # Targets
    for i, t in enumerate(setup.get("targets") or [], start=1):
        if t.get("price") is None:
            continue
        out.append({
            "type": "horizontal_line",
            "price": float(t["price"]),
            "label": t.get("label", f"T{i}"),
            "color": TARGET_COLOR,
            "style": "solid",
            "label_position": "right",
        })
    return out


def convert(
    phase_b: dict,
    chart_bbox: dict,
    y_axis_range: dict,
    input_image: str,
    output_image: str,
    theme: str = "dark",
    panel_id: str = "main",
) -> dict:
    """Build a Phase C annotation config from Phase B JSON + calibration."""
    bias = phase_b.get("bias", "neutral")

    annotations: list[dict] = []
    # Patterns first (so lines draw on top)
    for p in phase_b.get("patterns") or []:
        ann = _pattern_to_annotation(p, bias=bias)
        if ann:
            annotations.append(ann)
    # Trade setup
    setup = phase_b.get("trade_setup") or {}
    annotations.extend(_setup_to_annotations(setup, bias=bias))

    return {
        "input_image": input_image,
        "output_image": output_image,
        "theme": theme,
        "panels": [{
            "panel_id": panel_id,
            "chart_bbox": chart_bbox,
            "y_axis_range": y_axis_range,
            "annotations": annotations,
        }],
    }


def _parse_bbox(s: str) -> dict:
    parts = [int(p.strip()) for p in s.split(",")]
    if len(parts) != 4:
        raise ValueError(f"bbox must be 'x,y,w,h', got {s!r}")
    return {"x": parts[0], "y": parts[1], "width": parts[2], "height": parts[3]}


def _parse_y_range(s: str) -> dict:
    parts = [float(p.strip()) for p in s.split(",")]
    if len(parts) != 2:
        raise ValueError(f"y-range must be 'top,bottom', got {s!r}")
    return {"top": max(parts), "bottom": min(parts)}


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)-5s %(message)s")

    p = argparse.ArgumentParser(
        description="Phase B analysis JSON → Phase C annotation JSON (or directly draw)."
    )
    p.add_argument("--input", required=True, help="Phase B analysis JSON path")
    p.add_argument("--chart-bbox", default=None,
                   help="chart_bbox as 'x,y,w,h' (LLM-calibrated). "
                        "Optional if JSON contains a 'chart_bbox' field; CLI value overrides.")
    p.add_argument("--y-range", default=None,
                   help="y_axis_range as 'top,bottom'. "
                        "Optional if JSON contains 'y_axis_range'; CLI overrides.")
    p.add_argument("--image", help="Input chart image path (required for direct draw mode)")
    p.add_argument("--output", required=True,
                   help="Output path. If ends with .json → just convert. If .png/.jpg → convert + draw.")
    p.add_argument("--theme", default=None, choices=["dark", "light"],
                   help="Override theme (default reads from JSON or falls back to 'dark')")
    p.add_argument("--panel-id", default="main")
    args = p.parse_args()

    # Load Phase B JSON
    in_path = Path(args.input)
    if not in_path.is_file():
        log.error("Phase B JSON not found: %s", in_path)
        return 1
    phase_b = json.loads(in_path.read_text(encoding="utf-8"))

    # Determine mode by output extension
    out_path = Path(args.output)
    is_image_mode = out_path.suffix.lower() in (".png", ".jpg", ".jpeg")

    if is_image_mode and not args.image:
        log.error("--image required when --output is an image file")
        return 1

    # Resolve chart_bbox: CLI > JSON > error
    if args.chart_bbox:
        chart_bbox = _parse_bbox(args.chart_bbox)
    elif phase_b.get("chart_bbox"):
        chart_bbox = phase_b["chart_bbox"]
        log.info("chart_bbox loaded from JSON: %s", chart_bbox)
    else:
        log.error("chart_bbox not provided (--chart-bbox missing AND JSON has no 'chart_bbox')")
        return 1

    # Resolve y_axis_range: CLI > JSON > error
    if args.y_range:
        y_axis_range = _parse_y_range(args.y_range)
    elif phase_b.get("y_axis_range"):
        y_axis_range = phase_b["y_axis_range"]
        log.info("y_axis_range loaded from JSON: %s", y_axis_range)
    else:
        log.error("y_axis_range not provided (--y-range missing AND JSON has no 'y_axis_range')")
        return 1

    # Resolve theme: CLI > JSON > default 'dark'
    theme = args.theme or phase_b.get("theme") or "dark"

    cfg = convert(
        phase_b=phase_b,
        chart_bbox=chart_bbox,
        y_axis_range=y_axis_range,
        input_image=args.image or phase_b.get("input_image", ""),
        output_image=str(out_path) if is_image_mode else "",
        theme=theme,
        panel_id=args.panel_id,
    )

    if not is_image_mode:
        # JSON conversion mode
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(
            json.dumps(cfg, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        log.info("Phase C annotation JSON written: %s", out_path)
        print(str(out_path))
        return 0

    # Image draw mode: persist a tmp JSON, then call kb_draw_annotation.py
    import tempfile  # noqa: PLC0415
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", delete=False, encoding="utf-8",
    ) as tmp:
        json.dump(cfg, tmp, indent=2, ensure_ascii=False)
        tmp_json = tmp.name

    draw_script = THIS_DIR / "kb_draw_annotation.py"
    cmd = [sys.executable, str(draw_script), "--json", tmp_json]
    log.info("Running: %s", " ".join(cmd))
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        log.error("draw failed:\n%s", r.stderr)
        return r.returncode
    print(r.stdout.strip())
    return 0


if __name__ == "__main__":
    sys.exit(main())
