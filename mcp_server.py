"""Zemax OpticStudio MCP 服务器 (stdio 传输).

将所有 Zemax 工具封装为 MCP (Model Context Protocol) 服务，
可被任何 MCP 兼容的 Agent 客户端调用：
  - VS Code GitHub Copilot Agent Mode
  - Claude Desktop
  - 自定义 MCP 客户端

启动方式:
    python mcp_server.py [--zemax-mode extension|standalone] [--instance 0] [--clear-cache]

客户端通过 stdin/stdout 与本服务器通信，工具调用会路由到正在运行的
OpticStudio 实例（需先在 Zemax 中点击 Programming → Interactive Extension）。
"""

import asyncio
import json
import os
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
#  确保能找到同目录下的 zemax_connection / tools 模块
# ---------------------------------------------------------------------------
_HERE = Path(__file__).parent
sys.path.insert(0, str(_HERE))

import argparse

from dotenv import load_dotenv
from mcp.server import Server
from mcp.server.stdio import stdio_server
import mcp.types as types

from zemax_connection import ZemaxConnection
from tools import TOOL_DEFINITIONS, ZemaxToolkit
from logger import logger

# 加载 .env (API Key 对 MCP 服务器本身不需要，但 ZemaxConnection 可能用 ZEMAX_MODE 等)
load_dotenv(_HERE / ".env")

# ---------------------------------------------------------------------------
#  全局实例
# ---------------------------------------------------------------------------

_toolkit: ZemaxToolkit | None = None

server = Server("zemax-opticstudio")
server.version = "1.0.0"


# ---------------------------------------------------------------------------
#  工具注册
# ---------------------------------------------------------------------------

@server.list_tools()
async def list_tools() -> list[types.Tool]:
    """向 MCP 客户端声明所有可用的 Zemax 工具."""
    result = []
    for tool_def in TOOL_DEFINITIONS:
        fn = tool_def["function"]
        result.append(
            types.Tool(
                name=fn["name"],
                description=fn["description"],
                inputSchema=fn["parameters"],    # 直接复用现有 JSON Schema
            )
        )
    # 内置服务器管理工具
    result.append(
        types.Tool(
            name="reconnect_zemax",
            description=(
                "重新连接到 OpticStudio。当连接断开，或首次启动服务器时 OpticStudio 未就绪时使用。"
                "调用前请确保 OpticStudio 已运行并在 Programming → Interactive Extension 中激活。"
            ),
            inputSchema={"type": "object", "properties": {}, "required": []},
        )
    )
    return result


@server.call_tool()
async def call_tool(name: str, arguments: dict | None) -> list[types.TextContent]:
    """接收工具调用请求，路由到 ZemaxToolkit 执行."""
    if _toolkit is None:
        payload = json.dumps(
            {"error": "Zemax 连接尚未初始化。请确保以正确参数启动 MCP 服务器。"},
            ensure_ascii=False,
        )
        return [types.TextContent(type="text", text=payload)]

    # reconnect_zemax 是服务器内置工具，不走 ZemaxToolkit.dispatch
    if name == "reconnect_zemax":
        return _handle_reconnect()

    # 若连接断开，先自动尝试重连一次再报错
    if not _toolkit.conn.is_alive:
        logger.warning(f"MCP 工具 {name} 执行前检测到连接不活跃，尝试自动重连")
        _log("连接不活跃，尝试自动重连...")
        ok = _toolkit.conn.reconnect(max_retries=2, retry_delay=1.0)
        if not ok:
            payload = json.dumps(
                {
                    "error": (
                        "OpticStudio 连接已断开且自动重连失败。"
                        "请确保 OpticStudio 正在运行且已在 Programming → Interactive Extension 中激活，"
                        "然后调用 reconnect_zemax 工具重试。"
                    )
                },
                ensure_ascii=False,
            )
            return [types.TextContent(type="text", text=payload)]
        logger.info(f"MCP 服务器自动重连成功，继续执行工具 {name}")
        _log("自动重连成功，继续执行工具...")

    # COM 调用是同步的，直接在协程中执行。
    # (MCP stdio 服务器为单客户端模式，阻塞事件循环是可接受的)
    # win32com STA 线程模型要求在初始化线程上调用，不能用 run_in_executor。
    logger.info(f"MCP 工具调用: {name}")
    try:
        result_str = _toolkit.dispatch(name, arguments or {})
        logger.debug(f"MCP 工具结果: {result_str[:300]}")
    except Exception as e:
        logger.error(f"MCP 工具 {name} 异常: {e}", exc_info=True)
        result_str = json.dumps({"error": str(e)}, ensure_ascii=False)

    return [types.TextContent(type="text", text=result_str)]


def _handle_reconnect() -> list[types.TextContent]:
    """执行 reconnect_zemax 工具逻辑."""
    if _toolkit is None:
        return [types.TextContent(type="text", text=json.dumps({"error": "toolkit 未初始化"}))]
    logger.info("MCP 客户端触发手动重连")
    _log("手动重连请求...")
    ok = _toolkit.conn.reconnect(max_retries=3, retry_delay=2.0)
    if ok:
        logger.info("MCP 重连成功")
        _log("重连成功")
        payload = json.dumps({"ok": True, "message": "已成功重连到 OpticStudio"}, ensure_ascii=False)
    else:
        logger.warning("MCP 重连失败")
        payload = json.dumps(
            {"ok": False, "error": "重连失败。请确保 OpticStudio 正在运行且 Interactive Extension 已激活。"},
            ensure_ascii=False,
        )
    return [types.TextContent(type="text", text=payload)]


# ---------------------------------------------------------------------------
#  资源：提供当前系统文件路径（可选，方便客户端感知当前文件）
# ---------------------------------------------------------------------------

@server.list_resources()
async def list_resources() -> list[types.Resource]:
    if _toolkit is None or not _toolkit.conn.is_alive:
        return []
    try:
        file_path = _toolkit.conn.system.SystemFile  # 字符串路径
        if file_path:
            return [
                types.Resource(
                    uri=f"file:///{file_path.replace(chr(92), '/')}",
                    name=Path(file_path).name,
                    description="当前加载的 OpticStudio 光学系统文件 (.zmx)",
                    mimeType="application/octet-stream",
                )
            ]
    except Exception:
        pass
    return []


@server.read_resource()
async def read_resource(uri: types.AnyUrl) -> str:
    """读取资源内容（这里返回系统信息 JSON）."""
    if _toolkit is None or not _toolkit.conn.is_alive:
        return json.dumps({"error": "未连接"}, ensure_ascii=False)
    try:
        return _toolkit.dispatch("get_system_info", {})
    except Exception as e:
        return json.dumps({"error": str(e)}, ensure_ascii=False)


# ---------------------------------------------------------------------------
#  连接初始化
# ---------------------------------------------------------------------------

def _init_zemax_connection(zemax_mode: str, instance: int) -> ZemaxToolkit | None:
    """同步初始化 Zemax 连接，失败时返回 None（服务器继续运行）."""
    conn = ZemaxConnection()
    try:
        conn.connect(mode=zemax_mode, instance=instance)
        _log(f"已连接到 OpticStudio (序列号: {conn.app.SerialCode})")
        wl_cache = conn._prop_cache.get("IWavelength", {})
        fl_cache = conn._prop_cache.get("IField", {})
        _log(f"属性映射: IWavelength.value='{wl_cache.get('value')}', IField.x='{fl_cache.get('x')}'")
        return ZemaxToolkit(conn)
    except Exception as e:
        _log(f"警告: 连接 OpticStudio 失败: {e}")
        _log("服务器将继续运行，工具调用时将返回连接错误。")
        _log("修复后请重启 MCP 服务器。")
        # 仍然创建 toolkit（conn 处于未连接状态），dispatch 会返回友好错误
        return ZemaxToolkit(conn)


def _log(msg: str):
    """输出到 stderr（避免干扰 stdout 上的 MCP 协议通信）."""
    print(f"[zemax-mcp] {msg}", file=sys.stderr, flush=True)


# ---------------------------------------------------------------------------
#  主入口
# ---------------------------------------------------------------------------

async def async_main(zemax_mode: str, instance: int):
    global _toolkit
    _toolkit = _init_zemax_connection(zemax_mode, instance)
    logger.info(f"MCP 服务器启动: zemax_mode={zemax_mode}, instance={instance}")
    _log("Zemax OpticStudio MCP 服务器已启动 (stdio transport)")

    async with stdio_server() as (read_stream, write_stream):
        init_options = server.create_initialization_options()
        await server.run(read_stream, write_stream, init_options)


def main():
    parser = argparse.ArgumentParser(
        description="Zemax OpticStudio MCP Server — 将 OpticStudio 工具暴露为 MCP 协议服务"
    )
    parser.add_argument(
        "--zemax-mode",
        choices=["extension", "standalone"],
        default=os.getenv("ZEMAX_MODE", "extension"),
        help="连接模式: extension(连接运行中实例) / standalone(启动新实例)",
    )
    parser.add_argument(
        "--instance",
        type=int,
        default=int(os.getenv("ZEMAX_INSTANCE", "0")),
        help="Extension 实例编号 (默认 0)",
    )
    parser.add_argument(
        "--clear-cache",
        action="store_true",
        help="启动前清理 win32com gen_py ZOSAPI 缓存（解决属性映射异常）",
    )
    args = parser.parse_args()

    if args.clear_cache:
        try:
            ZemaxConnection.clear_gen_py_cache()
            _log("gen_py 缓存已清理")
        except Exception as e:
            _log(f"缓存清理失败 (非致命): {e}")

    asyncio.run(async_main(zemax_mode=args.zemax_mode, instance=args.instance))


if __name__ == "__main__":
    main()
