# -*- coding: utf-8 -*-
"""解析 Zemax 公差报告里的蒙特卡洛段落，输出分位数与良率。

用法:  python tmp/tol_stats.py [门限1 门限2 ...]
共享口径：DiffMTFAverage（子午+弧矢平均）@120 lp/mm, 复色。
"""
import os
import re
import sys
import statistics as st

sys.path.insert(0, r"D:\Zemax-mcp")
from tools import _read_text_any  # noqa: E402

P = os.path.join(os.environ["TEMP"], "zos_tolerance_report.txt")
text = _read_text_any(P)

seg = text[text.find("蒙特卡罗分析"):]
vals = []
for line in seg.splitlines():
    m = re.match(r"^\s*(\d{1,4})\s+([0-9.]+)\s+(-?[0-9.]+)\s*$", line.strip())
    if m and int(m.group(1)) <= 2000:
        vals.append(float(m.group(2)))
vals.sort()

nom = None
m = re.search(r"名义标准\s*:\s*([0-9.]+)", text)
if m:
    nom = float(m.group(1))

print("样本数 %d  名义 %.4f" % (len(vals), nom if nom else -1))
print("均值 %.4f  标准差 %.4f  最小 %.4f  最大 %.4f"
      % (st.mean(vals), st.stdev(vals), vals[0], vals[-1]))


def pct(q):
    k = (len(vals) - 1) * q
    f = int(k)
    c = min(f + 1, len(vals) - 1)
    return vals[f] + (vals[c] - vals[f]) * (k - f)


for q in (0.02, 0.05, 0.10, 0.50, 0.90, 0.95, 0.98):
    print("  P%02d = %.4f" % (q * 100, pct(q)))

th_list = [float(x) for x in sys.argv[1:]] or [0.30, 0.32, 0.35, 0.38, 0.40]
print()
print("良率（MTF@120 复色 T/S 平均 > 门限）:")
for th in th_list:
    y = sum(1 for v in vals if v > th) / len(vals) * 100
    print("  > %.2f : %5.1f%%   (失败 %d 个)"
          % (th, y, sum(1 for v in vals if v <= th)))

fail = [round(v, 3) for v in vals if v <= 0.35]
print()
print("低于 0.35 的样本:", fail[:15], ("...共 %d 个" % len(fail)) if len(fail) > 15 else "")

# 二项分布 95% 置信区间（Wilson）
n = len(vals)
p = sum(1 for v in vals if v > 0.35) / n
z = 1.96
den = 1 + z * z / n
ctr = (p + z * z / (2 * n)) / den
half = z * ((p * (1 - p) / n + z * z / (4 * n * n)) ** 0.5) / den
print("良率(>0.35) %.1f%%  95%%CI [%.1f%%, %.1f%%]"
      % (p * 100, (ctr - half) * 100, (ctr + half) * 100))
