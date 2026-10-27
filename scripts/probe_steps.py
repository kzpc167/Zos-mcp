"""一次性探针：逐步打点，定位连接后第一个 COM 调用是否阻塞。"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from zemax_connection import ZemaxConnection


def step(msg):
    print(msg, flush=True)


step("1 connect")
conn = ZemaxConnection()
conn.connect(mode="extension", instance=0)
step("2 connected")

sys_data = conn.system_data
step("3 system_data ok")

ape = sys_data.Aperture
step(f"4 aperture obj ok, type={ape.ApertureType} value={ape.ApertureValue}")

n_wl = sys_data.Wavelengths.NumberOfWavelengths
step(f"5 wavelengths n={n_wl}")

n_f = sys_data.Fields.NumberOfFields
step(f"6 fields n={n_f}")

lde = conn.lde
n_s = lde.NumberOfSurfaces
step(f"7 surfaces n={n_s}")

s0 = lde.GetSurfaceAt(0)
step(f"8 surf0 R={s0.Radius} T={s0.Thickness}")

step("9 first order")
fo = conn.system.FirstOrderData  # 若属性名不同会抛异常而非阻塞
step(f"10 first order effl={getattr(fo, 'EffectiveFocalLength', None)}")
step("done")
