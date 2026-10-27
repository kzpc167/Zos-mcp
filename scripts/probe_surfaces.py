"""一次性探针：逐个表面打点，定位 get_system_info 卡在哪一步。"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from zemax_connection import ZemaxConnection
from tools import _safe

conn = ZemaxConnection()
conn.connect(mode="extension", instance=0)
print("connected", flush=True)

sys_data = conn.system_data
print("aperture", sys_data.Aperture.ApertureType, sys_data.Aperture.ApertureValue, flush=True)

for i in range(1, sys_data.Fields.NumberOfFields + 1):
    f = sys_data.Fields.GetField(i)
    print("field", i, conn.get_field_data(f), flush=True)

for i in range(1, sys_data.Wavelengths.NumberOfWavelengths + 1):
    w = sys_data.Wavelengths.GetWavelength(i)
    print("wave", i, conn.get_wavelength_data(w), flush=True)

lde = conn.lde
n = lde.NumberOfSurfaces
print("surfaces", n, flush=True)
for i in range(n):
    surf = lde.GetSurfaceAt(i)
    print(f"surf {i} base", end=" ", flush=True)
    r = _safe(surf, "Radius", None)
    t = _safe(surf, "Thickness", None)
    m = _safe(surf, "Material", "")
    print(f"R={r} T={t} M={m}", end=" ", flush=True)
    try:
        mc = surf.MaterialCell
        print("cell ok", end=" ", flush=True)
        sd = mc.GetSolveData()
        print("solve ok", _safe(sd, "Type", None), flush=True)
    except Exception as e:
        print("cell ERR", type(e).__name__, flush=True)
print("done", flush=True)
