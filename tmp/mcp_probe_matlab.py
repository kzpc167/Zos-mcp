# -*- coding: utf-8 -*-
"""Probe the MATLAB MCP server over stdio: initialize -> tools/list -> evaluate_matlab_code."""
import json
import subprocess
import sys
import threading
import time

EXE = r"D:\Zemax-mcp\matlab-mcp\matlab-mcp-server-windows-x64.exe"
ARGS = [
    EXE,
    r"--matlab-root=D:\Program Files\MATLAB\R2025b",
    r"--log-folder=D:\Zemax-mcp\matlab-mcp\logs",
    "--matlab-session-mode=auto",
    "--matlab-display-mode=nodesktop",
    "--initialize-matlab-on-startup=true",
    "--disable-telemetry=true",
]

proc = subprocess.Popen(
    ARGS,
    stdin=subprocess.PIPE,
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE,
    text=True,
    encoding="utf-8",
    errors="replace",
    bufsize=1,
)

stderr_lines = []


def drain_stderr():
    for line in proc.stderr:
        stderr_lines.append(line.rstrip())


threading.Thread(target=drain_stderr, daemon=True).start()


def send(obj):
    proc.stdin.write(json.dumps(obj) + "\n")
    proc.stdin.flush()


def wait_for(req_id, timeout):
    deadline = time.time() + timeout
    while time.time() < deadline:
        line = proc.stdout.readline()
        if not line:
            return None
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue
        if msg.get("id") == req_id:
            return msg
    return None


try:
    t0 = time.time()
    send({
        "jsonrpc": "2.0", "id": 1, "method": "initialize",
        "params": {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "connectivity-probe", "version": "0.1"},
        },
    })
    r = wait_for(1, 120)
    print(f"[initialize] {round(time.time()-t0, 1)}s ->", "OK" if r else "NO RESPONSE")
    if r:
        info = r.get("result", {}).get("serverInfo", {})
        print("  server:", info)
    if not r:
        sys.exit(2)

    send({"jsonrpc": "2.0", "method": "notifications/initialized"})

    send({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
    r = wait_for(2, 30)
    names = [t["name"] for t in r["result"]["tools"]] if r else []
    print("[tools/list]", names)

    code = "disp(['MATLAB ' version]); disp(['pwd=' pwd]); disp(['root=' matlabroot])"
    send({
        "jsonrpc": "2.0", "id": 3, "method": "tools/call",
        "params": {
            "name": "evaluate_matlab_code",
            "arguments": {"code": code, "project_path": r"D:\Zemax-mcp"},
        },
    })
    t1 = time.time()
    r = wait_for(3, 180)
    print(f"[evaluate_matlab_code] {round(time.time()-t1, 1)}s")
    if r is None:
        print("  NO RESPONSE")
        sys.exit(3)
    if "error" in r:
        print("  ERROR:", json.dumps(r["error"], ensure_ascii=False))
        sys.exit(4)
    content = r.get("result", {}).get("content", [])
    for item in content:
        text = item.get("text", "")
        print("  output:", text.strip()[:800])
    print("  isError:", r.get("result", {}).get("isError"))
finally:
    try:
        proc.terminate()
        proc.wait(timeout=10)
    except Exception:
        proc.kill()
    if stderr_lines:
        print("--- server stderr (tail) ---")
        print("\n".join(stderr_lines[-15:]))
