#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""重启 MATLAB MCP：清掉挂死的 MATLAB 会话 → 修损坏的工具箱缓存 → 重新拉起共享引擎。

背景（2026-11-18 实测）：
    matlab-mcp-server 启动时会做一次 eager 初始化。这一步失败后，server 会一直握着
    那个死会话不再重试，于是每次工具调用都返回 `timeout waiting for worker to start`，
    而客户端仍然显示 connected（connected 只代表 stdio 握手成功，不代表 MATLAB 挂上了）。
    常见诱因有两个：
      ① 初始化时拉起两个 MATLAB 互相争用，两个都卡在启动阶段；
      ② %LOCALAPPDATA%\\MathWorks\\MATLAB\\R20xx\\toolbox_cache-*.xml 被写成 0 字节，
         桌面模式启动时报"文件格式不正确"并卡住。

本脚本做的事（默认全做，可用开关关掉）：
    1) 结束 matlab-mcp-server 进程（客户端需要重连才会重新拉起）
    2) 结束挂死的 MATLAB 进程
    3) 把 0 字节的 toolbox_cache 改名备份，让 MATLAB 下次重建
    4) 用 matlab.engine.shareEngine 起一个共享引擎，让 --matlab-session-mode=auto 走 attach
    5) 自检共享引擎（命令行含 shareEngine、进程存活、有 CPU 消耗）

用法：
    python scripts/restart_matlab_mcp.py                 # 交互确认后全做
    python scripts/restart_matlab_mcp.py --yes           # 不询问
    python scripts/restart_matlab_mcp.py --dry-run       # 只打印将要做什么，不动任何东西
    python scripts/restart_matlab_mcp.py --keep-matlab   # 保留 MATLAB 进程，只重启 server
    python scripts/restart_matlab_mcp.py --no-server     # 不杀 server（客户端连接不受影响）
    python scripts/restart_matlab_mcp.py --no-start      # 不重新拉起 MATLAB
    python scripts/restart_matlab_mcp.py --wait 90       # 等 MATLAB 就绪的时间（秒，默认 60）

注意：
    * 结束 server 进程后，客户端（Claude Code / VS Code）里的 matlab MCP 会短暂断开，
      需要在客户端执行一次重连（Claude Code：/mcp；VS Code：MCP: Restart Server），
      脚本无法代替这一步。
    * 同一个 MATLAB MCP 只应由一个客户端持有；两个客户端各拉一个 server 时，
      它们共享同一个 MATLAB 会话，同时调用会互相插队。
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SERVER_PREFIX = "matlab-mcp-server"


# --------------------------------------------------------------------------- 输出

def log(tag: str, msg: str) -> None:
    print(f"[{tag:4s}] {msg}", flush=True)


def hr() -> None:
    print("-" * 74, flush=True)


# --------------------------------------------------------------------------- psutil

def require_psutil():
    try:
        import psutil  # noqa: F401
        return psutil
    except ImportError:
        log("ERR", "缺少 psutil。请用项目虚拟环境运行：")
        print("        .venv\\Scripts\\python.exe scripts\\restart_matlab_mcp.py", flush=True)
        raise SystemExit(2)


# --------------------------------------------------------------------------- 定位

def find_matlab_exe(explicit: str | None = None) -> Path | None:
    """按 --matlab-root（.vscode/mcp.json）→ 常见安装路径 的顺序找 matlab.exe。"""
    candidates: list[Path] = []

    if explicit:
        candidates.append(Path(explicit) / "bin" / "matlab.exe")

    cfg = REPO_ROOT / ".vscode" / "mcp.json"
    if cfg.exists():
        try:
            data = json.loads(cfg.read_text(encoding="utf-8-sig"))
            args = data.get("servers", {}).get("matlab", {}).get("args", [])
            for a in args:
                if isinstance(a, str) and a.startswith("--matlab-root="):
                    candidates.append(Path(a.split("=", 1)[1]) / "bin" / "matlab.exe")
        except Exception as e:  # 配置坏了不该阻塞重启
            log("WARN", f"读取 .vscode/mcp.json 失败：{e}")

    for pat in ("C:/Program Files/MATLAB/R*/bin/matlab.exe",
                "D:/Program Files/MATLAB/R*/bin/matlab.exe",
                "C:/Program Files/MATLAB/*/bin/matlab.exe",
                "D:/Program Files/MATLAB/*/bin/matlab.exe"):
        candidates.extend(Path(p) for p in sorted(glob.glob(pat), reverse=True))

    seen = set()
    for c in candidates:
        if c in seen:
            continue
        seen.add(c)
        if c.is_file():
            return c
    return None


def list_processes(psutil):
    servers, matlabs = [], []
    for p in psutil.process_iter(["pid", "name", "create_time", "cmdline"]):
        try:
            name = (p.info.get("name") or "").lower()
            if name.startswith(SERVER_PREFIX):
                servers.append(p)
            elif name in ("matlab.exe", "matlab"):
                matlabs.append(p)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return servers, matlabs


def cache_files() -> list[Path]:
    base = os.environ.get("LOCALAPPDATA")
    if not base:
        return []
    return sorted(Path(p) for p in glob.glob(
        os.path.join(base, "MathWorks", "MATLAB", "*", "toolbox_cache-*.xml*")))


# --------------------------------------------------------------------------- 动作

def kill(p, psutil, timeout: float = 8.0) -> bool:
    try:
        p.terminate()
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return not p.is_running()
    try:
        p.wait(timeout=timeout)
        return True
    except psutil.TimeoutExpired:
        try:
            p.kill()
            p.wait(timeout=timeout)
            return True
        except Exception:
            return False


def repair_cache(dry: bool) -> int:
    """把 0 字节的 toolbox_cache 改名备份（MATLAB 会自己重建）。返回处理个数。"""
    fixed = 0
    for f in cache_files():
        try:
            size = f.stat().st_size
        except OSError:
            continue
        if size == 0 and not f.name.endswith(".bak"):
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            target = f.with_name(f"{f.name}.empty-{stamp}.bak")
            if dry:
                log("DRY", f"将把 0 字节缓存改名：{f.name} → {target.name}")
            else:
                try:
                    f.rename(target)
                    log("OK", f"0 字节缓存已改名备份：{f.name} → {target.name}")
                except OSError as e:
                    log("WARN", f"缓存改名失败（可能被占用，MATLAB 全关后再试）：{e}")
                    continue
            fixed += 1
    return fixed


def start_shared_matlab(exe: Path, dry: bool) -> bool:
    if dry:
        log("DRY", f'将启动："{exe}" -r matlab.engine.shareEngine')
        return True
    flags = 0
    if os.name == "nt":
        flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    try:
        subprocess.Popen([str(exe), "-r", "matlab.engine.shareEngine"],
                         creationflags=flags, close_fds=True)
    except OSError as e:
        log("ERR", f"启动 MATLAB 失败：{e}")
        return False
    log("OK", f"已启动 MATLAB（共享引擎）：{exe}")
    return True


def wait_for_matlab(psutil, timeout_s: int) -> bool:
    """等 MATLAB 主进程出现并稳定一段时间。真正的就绪由 verify 判定。"""
    deadline = time.time() + timeout_s
    last = None
    while time.time() < deadline:
        _, matlabs = list_processes(psutil)
        if matlabs:
            last = max(m.create_time() for m in matlabs)
        time.sleep(2)
        if last and time.time() - last > 8:
            break
    return bool(last)


def verify_shared(psutil) -> bool:
    """确认 MATLAB 是用 shareEngine 起来的，且在正常响应。

    说明：`matlab.engine.find_matlab()` 是 **Python 侧** API，MATLAB 会话里没有这个函数，
    所以不能用 `matlab -batch` 去"发现"别的会话（`isEngineShared` 只能报告自己）。
    真正能不能被 attach，只有 MCP 自己知道 —— 最终判据是客户端跑通一次工具调用。
    这里只做进程级自检：命令行里有没有 shareEngine、进程是否还在跑、有没有在吃 CPU。
    """
    _, matlabs = list_processes(psutil)
    if not matlabs:
        log("WARN", "没有 MATLAB 进程在跑")
        return False

    shared = []
    for p in matlabs:
        try:
            cmd = " ".join(p.info.get("cmdline") or [])
        except Exception:
            cmd = ""
        if "shareEngine" in cmd:
            shared.append((p, cmd))

    if not shared:
        log("WARN", "MATLAB 在跑，但命令行里没有 shareEngine："
                    "当前的实例不会被 MCP attach，它可能会再启动一个")
        for p in matlabs:
            cmd = " ".join(p.info.get("cmdline") or []) or "<无命令行>"
            print(f"        pid {p.pid}: {cmd[:120]}", flush=True)
        return False

    for p, cmd in shared:
        try:
            cpu = p.cpu_times().user + p.cpu_times().system
            alive = p.is_running() and p.status() != psutil.STATUS_ZOMBIE
        except Exception:
            cpu, alive = -1, False
        log("OK", f"pid {p.pid} 以 shareEngine 启动（{'存活' if alive else '已退出'}，"
                  f"累计 CPU {cpu:.1f}s）")
        print(f"        {cmd[:120]}", flush=True)
    return True


# --------------------------------------------------------------------------- 主流程

def main() -> int:
    ap = argparse.ArgumentParser(
        description="重启 MATLAB MCP（清挂死会话 + 修缓存 + 重建共享引擎）",
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--yes", "-y", action="store_true", help="不询问，直接执行")
    ap.add_argument("--dry-run", action="store_true", help="只打印计划，不动任何进程/文件")
    ap.add_argument("--keep-matlab", action="store_true", help="保留 MATLAB 进程，只重启 server")
    ap.add_argument("--no-server", action="store_true", help="不结束 matlab-mcp-server 进程")
    ap.add_argument("--no-start", action="store_true", help="不重新拉起 MATLAB")
    ap.add_argument("--no-cache", action="store_true", help="不检查工具箱缓存")
    ap.add_argument("--no-verify", action="store_true", help="跳过共享引擎自检")
    ap.add_argument("--wait", type=int, default=60, help="等 MATLAB 就绪的秒数（默认 60）")
    ap.add_argument("--matlab-root", help="MATLAB 安装根目录（默认从 .vscode/mcp.json 读）")
    args = ap.parse_args()

    psutil = require_psutil()
    dry = args.dry_run

    log("INFO", f"仓库：{REPO_ROOT}")
    exe = find_matlab_exe(args.matlab_root)
    log("INFO", f"MATLAB：{exe if exe else '未找到'}")
    if exe is None and not args.no_start:
        log("ERR", "找不到 matlab.exe，请用 --matlab-root 指定（如 \"D:/Program Files/MATLAB/R2025b\"）")
        return 2

    servers, matlabs = list_processes(psutil)
    hr()
    log("INFO", f"matlab-mcp-server 进程：{len(servers)} 个")
    for p in servers:
        log("INFO", f"    pid {p.pid:>6}  启动 {datetime.fromtimestamp(p.create_time()):%m-%d %H:%M:%S}")
    log("INFO", f"MATLAB 进程：{len(matlabs)} 个")
    for p in matlabs:
        up = (time.time() - p.create_time()) / 3600
        log("INFO", f"    pid {p.pid:>6}  启动 {datetime.fromtimestamp(p.create_time()):%m-%d %H:%M:%S}"
                    f"  已运行 {up:.1f} h")
    if len(servers) > 1:
        log("WARN", "有多个 server 进程：通常是两个客户端各拉了一个，"
                    "它们共享同一个 MATLAB 会话，同时调用会互相插队")
    hr()

    plan = []
    if not args.no_server:
        plan.append(f"结束 {len(servers)} 个 matlab-mcp-server 进程")
    if not args.keep_matlab:
        plan.append(f"结束 {len(matlabs)} 个 MATLAB 进程")
    if not args.no_cache:
        plan.append("检查并备份 0 字节的 toolbox_cache")
    if not args.no_start:
        plan.append("启动 MATLAB 共享引擎")
    if not args.no_verify:
        plan.append("校验共享引擎可被发现")
    if not plan:
        log("WARN", "所有步骤都被开关关掉了，什么也不做")
        return 0
    for i, s in enumerate(plan, 1):
        log("PLAN", f"{i}. {s}")
    hr()

    if dry:
        repair_cache(dry=True)
        if not args.no_start:
            start_shared_matlab(exe, dry=True)
        log("DRY", "演练结束，未改动任何东西")
        return 0

    if not args.yes:
        try:
            ans = input("确认执行？[y/N] ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            ans = ""
        if ans not in ("y", "yes"):
            log("INFO", "已取消")
            return 1

    # 1) server
    if not args.no_server and servers:
        for p in servers:
            ok = kill(p, psutil)
            log("OK" if ok else "WARN", f"server pid {p.pid} " + ("已结束" if ok else "结束失败"))

    # 2) MATLAB
    if not args.keep_matlab and matlabs:
        for p in matlabs:
            ok = kill(p, psutil, timeout=10)
            log("OK" if ok else "WARN", f"MATLAB pid {p.pid} " + ("已结束" if ok else "结束失败"))
        time.sleep(2)

    # 3) 缓存
    if not args.no_cache:
        n = repair_cache(dry=False)
        if n == 0:
            log("OK", "工具箱缓存无 0 字节文件，无需处理")

    # 4) 共享引擎
    if not args.no_start:
        if not start_shared_matlab(exe, dry=False):
            return 3
        log("INFO", f"等待 MATLAB 就绪（最多 {args.wait}s）…")
        wait_for_matlab(psutil, args.wait)
        _, now = list_processes(psutil)
        if not now:
            log("ERR", "MATLAB 仍未起来，请手动打开一次 MATLAB 看是否报错")
            return 3
        log("OK", f"MATLAB 进程已就绪：pids {[p.pid for p in now]}")

    # 5) 校验
    ok = False
    if not args.no_verify:
        ok = verify_shared(psutil)

    hr()
    log("DONE", "脚本部分完成。还需要在客户端做一步：")
    print("        Claude Code 扩展：执行 /mcp → 重连 matlab（或重启会话）", flush=True)
    print("        VS Code MCP 面板：MCP: Restart Server → matlab", flush=True)
    print("        判据：能跑通一次 detect_matlab_toolboxes；"
          "客户端显示 connected 不代表 MATLAB 已挂上", flush=True)
    return 0 if ok or args.no_verify else 4


if __name__ == "__main__":
    sys.exit(main())
