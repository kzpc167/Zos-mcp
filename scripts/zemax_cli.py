#!/usr/bin/env python3
"""不经过 MCP 的 Zemax 工具命令行 —— 直接驱动 ZOS-API 连接器。

用途：当客户端没有挂载 zemax MCP 服务器时（例如 DSH 会话），
仍可用同一个 ZemaxToolkit.dispatch 路径调用 53 个工具，从而保留
自动重连、高风险操作备份、写后 UI 刷新等行为。

用法：
    python scripts/zemax_cli.py get_system_info
    python scripts/zemax_cli.py get_project_context
    python scripts/zemax_cli.py set_aperture '{"aperture_type": "EntrancePupilDiameter", "value": 33.3}'

参数：
    --mode extension|standalone   连接模式（默认取 ZEMAX_MODE，再退回 extension）
    --instance N                  Extension 实例号（默认 0）
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from zemax_connection import ZemaxConnection
import tools as T


def main() -> int:
    ap = argparse.ArgumentParser(description="Zemax 工具命令行（直连 ZOS-API）")
    ap.add_argument("tool", help="工具名，如 get_system_info / get_operands")
    ap.add_argument("args", nargs="?", default="{}", help="工具参数 JSON，默认 {}")
    ap.add_argument("--mode", default=os.getenv("ZEMAX_MODE", "extension"))
    ap.add_argument("--instance", type=int, default=int(os.getenv("ZEMAX_INSTANCE", "0")))
    ns = ap.parse_args()

    try:
        arguments = json.loads(ns.args)
    except json.JSONDecodeError as e:
        print(f"[错误] 参数不是合法 JSON: {e}", file=sys.stderr)
        return 2
    if not isinstance(arguments, dict):
        print("[错误] 参数必须是 JSON 对象", file=sys.stderr)
        return 2

    conn = ZemaxConnection()
    try:
        conn.connect(mode=ns.mode, instance=ns.instance)
    except Exception as e:
        print(f"[连接失败] {e}", file=sys.stderr)
        return 3

    toolkit = T.ZemaxToolkit(conn)
    try:
        print(toolkit.dispatch(ns.tool, arguments))
    finally:
        conn.disconnect()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
