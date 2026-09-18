# -*- coding: utf-8 -*-
"""GoldAgent 启动入口（PyCharm 直接运行本文件即可）。

默认: live 模式（.env 中 TRADE_MODE=live）真实下单，无限轮次。
命令行可选:
    python main.py --dry        # 演练模式，不真实下单
    python main.py --rounds 10  # 跑 10 轮后退出
"""
import sys
from pathlib import Path

# 源码在 src/ 下：无配置直接可跑（无需在 PyCharm 里设 PYTHONPATH / Sources Root）
_SRC = Path(__file__).resolve().parent / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from gold_agent.runner import main

if __name__ == "__main__":
    main()
