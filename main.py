# -*- coding: utf-8 -*-
"""GoldAgent 启动入口（PyCharm 直接运行本文件即可）。

默认: live 模式（.env 中 TRADE_MODE=live）真实下单，无限轮次。
命令行可选:
    python main.py --dry        # 演练模式，不真实下单
    python main.py --rounds 10  # 跑 10 轮后退出
"""
from gold_agent.runner import main

if __name__ == "__main__":
    main()
