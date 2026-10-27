"""一次性探针：用 faulthandler 在卡住时打印栈，定位 get_system_info 的阻塞点。"""

import faulthandler
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

faulthandler.dump_traceback_later(20, repeat=True)

from zemax_connection import ZemaxConnection
import tools as T

conn = ZemaxConnection()
conn.connect(mode="extension", instance=0)
print("connected", flush=True)

tk = T.ZemaxToolkit(conn)
out = tk.get_system_info()
print("len", len(out), flush=True)
print(out[:400], flush=True)
faulthandler.cancel_dump_traceback_later()
