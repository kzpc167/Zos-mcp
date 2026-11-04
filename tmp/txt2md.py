# -*- coding: utf-8 -*-
"""把 Zemax 导出的公差报告（UTF-16 定宽文本）转成可读的 Markdown。

原则：
1. 数值一个不改，原始文本整体保留在 <details> 折叠块里，可逐位复核。
2. 顶部给结论表格，正文给设置与最坏偏离，避免一打开就是 500 行原始数据。
"""
import os
import re
import sys
import statistics as st

sys.path.insert(0, r"D:\Zemax-mcp")
from tools import _read_text_any  # noqa: E402

BASE = r"D:\Zemax-mcp\zemax-ADAS"


def parse_head(t):
    """抓报告头部的元信息。"""
    out = {}
    for key, pat in (
        ("pdf", r"判据\s*:\s*(.+)"),
        ("nominal", r"名义标准\s*:\s*([0-9.]+)"),
        ("wave", r"测试波长\s*:\s*([0-9.]+)"),
        ("mode", r"模式\s*:\s*(\S+)"),
        ("src", r"文件\s*:\s*(.+)"),
        ("runs", r"测试数:\s*(\d+)"),
        ("sample", r"采样\s*:\s*(\d+)"),
    ):
        m = re.search(pat, t)
        out[key] = m.group(1).strip() if m else None
    return out


def mc_samples(t):
    seg = t[t.find("蒙特卡罗分析"):]
    vals = []
    for line in seg.splitlines():
        m = re.match(r"^\s*(\d{1,4})\s+([0-9.]+)\s+(-?[0-9.eE+-]+)\s*$", line.strip())
        if m and int(m.group(1)) <= 2000:
            vals.append(float(m.group(2)))
    return sorted(vals)


def worst_deviations(t, top=10):
    i = t.find("最坏偏离")
    if i < 0:
        return []
    rows = []
    for line in t[i:].splitlines()[1:]:
        m = re.match(r"^(T[A-Z]{3,4})\s+(\d+)\s*(?:(\d+))?\s+(-?[0-9.]+)\s+([0-9.]+)\s+(-?[0-9.eE+-]+)\s*$",
                     line.strip())
        if m:
            rows.append((m.group(1), int(m.group(2)),
                         int(m.group(3)) if m.group(3) else None,
                         float(m.group(4)), float(m.group(5)), float(m.group(6))))
    return rows[:top]


def pct(v, q):
    k = (len(v) - 1) * q
    f = int(k)
    c = min(f + 1, len(v) - 1)
    return v[f] + (v[c] - v[f]) * (k - f)


def yld(v, th, ge):
    n = len(v)
    k = sum(1 for x in v if (x > th if ge else x <= th))
    return k, n, k / n * 100


def fmt_ci(k, n):
    if n == 0:
        return "—"
    p = k / n
    z = 1.96
    den = 1 + z * z / n
    ctr = (p + z * z / (2 * n)) / den
    half = z * ((p * (1 - p) / n + z * z / (4 * n * n)) ** 0.5) / den
    return "[%.1f%%, %.1f%%]" % ((ctr - half) * 100, (ctr + half) * 100)


def convert(fname, title, judge_scale, th, ge, note):
    src = os.path.join(BASE, fname + ".txt")
    t = _read_text_any(src)
    h = parse_head(t)
    v = mc_samples(t)

    L = []
    L.append("# %s" % title)
    L.append("")
    L.append("**源文件**：`%s`  " % os.path.basename((h["src"] or "").strip()))
    L.append("**判据**：%s  " % (h["pdf"] or "—"))
    L.append("**名义标准**：%s  " % (h["nominal"] or "—"))
    L.append("**测试波长**：%s µm（主波长显示值；实际按复色计算）  " % (h["wave"] or "—"))
    L.append("**抽样**：%s 次  " % (h["runs"] or "—"))
    L.append("**生成**：2026-11-04（由 Zemax 原生导出文本转换，数值未作任何改动）")
    L.append("")
    L.append("---")
    L.append("")

    if v:
        scaled = [x * judge_scale for x in v]
        unit = "µm" if judge_scale != 1 else ""
        # 最差样本要按判据方向取：MTF 越高越好 → 最差是最小值；RMS 越低越好 → 最差是最大值
        worst = scaled[0] if ge else scaled[-1]
        L.append("## 1. 结果摘要")
        L.append("")
        L.append("| 指标 | 值 |")
        L.append("|---|---:|")
        L.append("| 样本数 | %d |" % len(v))
        L.append("| 均值 | %.3f%s |" % (st.mean(scaled), unit and " " + unit or ""))
        L.append("| 标准差 σ | %.3f%s |" % (st.stdev(scaled), unit and " " + unit or ""))
        L.append("| P05 / P50 / P95 | %.3f / %.3f / %.3f |"
                 % (pct(scaled, .05), pct(scaled, .50), pct(scaled, .95)))
        L.append("| 最差样本（%s） | %.3f%s |"
                 % ("最低" if ge else "最高", worst, unit and " " + unit or ""))
        k, n, y = yld(scaled, th, ge)
        L.append("| **合格判定** | %s %.2f%s → **%.1f%%**（%d/%d） |"
                 % ("＞" if ge else "≤", th, (" " + unit) if unit else "", y, k, n))
        L.append("| 95 %% 置信区间 | %s |" % fmt_ci(k, n))
        L.append("")
        L.append("> %s" % note)
        L.append("")
        # 分位数补充
        L.append("**分位数**：" + " · ".join(
            ["P%02d = %.3f" % (q * 100, pct(scaled, q)) for q in (.02, .10, .50, .90, .98)]))
        L.append("")

    sec = 1
    wd = worst_deviations(t)
    if wd:
        sec += 1
        L.append("## %d. 最坏偏离（单项公差单独作用）" % sec)
        L.append("")
        L.append("| 排名 | 类型 | 面 | 取值 | 该点判据值 | 相对名义变化 |")
        L.append("|---:|---|---:|---:|---:|---:|")
        for i, (typ, s1, s2, val, crit, chg) in enumerate(wd, 1):
            L.append("| %d | %s | %s | %+.4f | %.4f | %+.4f |"
                     % (i, typ,
                        ("%d–%d" % (s1, s2)) if (s2 and s2 != s1) else str(s1),
                        val, crit, chg))
        L.append("")

    sec += 1
    L.append("## %d. 原始报告全文" % sec)
    L.append("")
    L.append("<details>")
    L.append("<summary>展开 Zemax 原生导出文本（%d 字符）</summary>" % len(t))
    L.append("")
    L.append("```text")
    L.append(t.replace("\r\n", "\n").rstrip())
    L.append("```")
    L.append("")
    L.append("</details>")
    L.append("")
    L.append("---")
    L.append("")
    L.append("## 口径说明")
    L.append("")
    L.append("1. **复色判据**：报告头「测试波长 0.5880」只是主波长显示，实际按 0.486~0.656 µm 复色计算"
             "（已交叉验证：复色加权平均 0.5754 / 单色 0.6306 / 公差名义 0.5705）。")
    L.append("2. **视场口径**：`DiffMTFAverage` 为 9 视场、子午/弧矢平均。若按最差视场最差方向验收，"
             "常温全视场仅 0.447，余量会显著变小。")
    L.append("3. **补偿器**：后焦（S14 厚度），漂移范围见原始报告「补偿器统计」。")
    L.append("")

    dst = os.path.join(BASE, fname + ".md")
    with open(dst, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(L))
    print("  -> %s  (%d 行, %d 样本)" % (os.path.basename(dst), len(L), len(v)))


JOBS = [
    ("公差报告_MTF_胶合01875_500次", "公差分析报告 —— 定稿规格（胶合组 ±0.01875）· MTF 判据", 1, 0.35, True,
     "规格要求：复色 MTF@120 ＞ 0.35。定稿口径为 500 次抽样。"),
    ("公差报告_MTF_胶合Q4_500次", "公差分析报告 —— 胶合组放宽到 Q4（±0.025）对比 · MTF 判据", 1, 0.35, True,
     "用于量化「放宽一档省成本 vs 良率」的取舍。良率 96.2 % 的 95 % 置信下界 94.1 %，已跌破 95 %。"),
    ("公差报告_RMS_定稿500次", "公差分析报告 —— 定稿规格 · RMS 光斑判据", 1000, 5.0, False,
     "规格要求：RMS 光斑 ≤ 5 µm。原始单位为 mm，本文已换算为 µm。"),
    ("公差报告_灵敏度_胶合Q4", "公差分析报告 —— 灵敏度明细（胶合组 Q4 规格）", 1, 0.35, True,
     "含 78 项逐项劣化、RSS 预算预测与补偿器统计；报告内附带的蒙特卡罗段落亦为 500 次。"),
]

if __name__ == "__main__":
    print("转换:")
    for j in JOBS:
        convert(*j)
