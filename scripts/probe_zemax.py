"""一次性探针：验证本仓库能否直接连上正在运行的 OpticStudio（不经过 MCP 层）。"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from zemax_connection import ZemaxConnection
import tools as T

print("connecting...", flush=True)
conn = ZemaxConnection()
conn.connect(mode="extension", instance=0)
print("connected ok", flush=True)

tk = T.ZemaxToolkit(conn)

info = json.loads(tk.get_system_info())
print(json.dumps(info.get("aperture"), ensure_ascii=False))
print("num_surfaces:", info.get("num_surfaces"))
print("fields:", [(f["x"], f["y"]) for f in info.get("fields", [])])
print("wavelengths:", [w.get("value_um") for w in info.get("wavelengths", [])])
for s in info.get("surfaces", [])[:6]:
    print(f"  surf {s['number']:>2} R={s['radius']} T={s['thickness']} mat={s['material']}")

print("--- project context ---")
print(tk.get_project_context()[:600])
