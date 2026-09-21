"""模型库冒烟测试：在小样本上跑通全部模型，检查无前视与数值健全性。"""
from __future__ import annotations

import io
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from gold_agent.common.config import CFG
from gold_agent.quant import models as M

df = pd.read_parquet(CFG.data_dir / "XAUUSDm_1m.parquet")
df["time"] = pd.to_datetime(df["time"], utc=True)
df = df.sort_values("time").reset_index(drop=True)
sub = df.iloc[:6000].reset_index(drop=True)     # 6000 根 1m ≈ 4 天
print(f"样本 {len(sub)} 根  {sub.time.iloc[0]} .. {sub.time.iloc[-1]}\n")

print(f"{'模型':<22}{'类别':<12}{'类型':<11}{'耗时s':>7}{'有效值':>9}"
      f"{'均值':>12}{'标准差':>12}{'min':>11}{'max':>11}  前视检查")
bad = []
for spec in M.REGISTRY:
    t0 = time.time()
    try:
        v = spec.fn(sub)
    except Exception as e:
        print(f"{spec.name:<22}{spec.category:<12}{spec.kind:<11}  ERROR "
              f"{type(e).__name__}: {str(e)[:60]}")
        bad.append((spec.name, f"{type(e).__name__}: {e}"))
        continue
    dt = time.time() - t0
    v = np.asarray(v, float)
    if len(v) != len(sub):
        print(f"{spec.name:<22} 长度不匹配 {len(v)} != {len(sub)}")
        bad.append((spec.name, "length mismatch"))
        continue
    fin = np.isfinite(v)
    # 前视检查：截断数据后，已计算部分应完全一致
    half = len(sub) // 2
    try:
        v2 = np.asarray(spec.fn(sub.iloc[:half].reset_index(drop=True)), float)
        n_cmp = min(len(v2), half)
        a, b = v[:n_cmp], v2[:n_cmp]
        m = np.isfinite(a) & np.isfinite(b)
        leak = 0.0
        if m.sum() > 10:
            leak = float(np.nanmax(np.abs(a[m] - b[m]) / (np.abs(b[m]) + 1e-9)))
        flag = "OK" if leak < 1e-6 else f"⚠ 泄漏 {leak:.2e}"
    except Exception as e:
        flag = f"? {type(e).__name__}"
    print(f"{spec.name:<22}{spec.category:<12}{spec.kind:<11}{dt:>7.2f}{fin.sum():>9}"
          f"{np.nanmean(v):>12.4f}{np.nanstd(v):>12.4f}"
          f"{np.nanmin(v):>11.4f}{np.nanmax(v):>11.4f}  {flag}")

print(f"\n共 {len(M.REGISTRY)} 个模型（方向 {len(M.DIRECTION_MODELS)} / 状态 {len(M.STATE_MODELS)}）")
if bad:
    print("\n失败模型:")
    for n, e in bad:
        print(f"  {n}: {e}")
