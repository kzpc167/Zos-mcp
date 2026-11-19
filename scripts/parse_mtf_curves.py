# -*- coding: utf-8 -*-
"""把 OpticStudio 导出的 MTF 文本（复色衍射 / FFT MTF vs 频率）解析成宽表 CSV，供 MATLAB 出图。

自动识别：第一块视为衍射极限，其余块按顺序视为各视场；频率范围与视场数量都不写死。

用法：
    python scripts/parse_mtf_curves.py --txt "D:\\...\\layouts\\analysis\\fft_mtf.txt" \
                                       --csv "D:\\...\\matlab\\data\\mtf_curves.csv"
    python scripts/parse_mtf_curves.py --txt ... --csv ... --max-freq 120 --report-freq 120

参数：
    --txt          源文本（UTF-16 / UTF-8 / GBK 自动识别）
    --csv          输出宽表 CSV；省略则只打印摘要
    --max-freq     截断上限 lp/mm；默认取文件里的最大频率
    --report-freq  摘要里打印的读数频率，默认 120（超出范围则取最大频率）
    --no-diff      文件里没有衍射极限块（第一块就是视场）
"""
import argparse
import io
import os
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")


def read_text_any(path):
    raw = open(path, "rb").read()
    for enc in ("utf-16", "utf-8", "gbk"):
        try:
            return raw.decode(enc)
        except Exception:
            continue
    return raw.decode("utf-8", errors="replace")


def parse_blocks(text):
    blocks, name, data = [], None, {}
    for ln in text.splitlines():
        s = ln.strip()
        if s.startswith("视场") or s.lower().startswith("field"):
            if name is not None:
                blocks.append((name, data))
            name, data = s.replace("：", ":").strip(), {}
            continue
        if name is None:
            continue
        p = s.split()
        if len(p) == 3:
            try:
                data[round(float(p[0]), 6)] = (float(p[1]), float(p[2]))
            except ValueError:
                pass
    if name is not None:
        blocks.append((name, data))
    return blocks


def main():
    ap = argparse.ArgumentParser(description="Parse Zemax MTF text export to CSV")
    ap.add_argument("--txt", required=True)
    ap.add_argument("--csv", default=None)
    ap.add_argument("--max-freq", type=float, default=None)
    ap.add_argument("--report-freq", type=float, default=120.0)
    ap.add_argument("--no-diff", action="store_true")
    a = ap.parse_args()

    if not os.path.isfile(a.txt):
        sys.exit("找不到文件: %s" % a.txt)

    blocks = parse_blocks(read_text_any(a.txt))
    if not blocks:
        sys.exit("没有解析到任何数据块，检查是否为 MTF 文本导出")

    diff = None
    fields = blocks
    if not a.no_diff:
        diff, fields = blocks[0], blocks[1:]
    if not fields:
        sys.exit("只解析到衍射极限块，没有视场数据")

    allf = sorted(set().union(*[set(d) for _, d in blocks]))
    fmax = a.max_freq if a.max_freq is not None else allf[-1]
    freqs = [f for f in allf if 0.0 <= f <= fmax + 1e-9]

    print("数据块 %d 个（衍射极限 %s + 视场 %d 个）"
          % (len(blocks), "有" if diff else "无", len(fields)))
    print("频率范围 %.1f -> %.1f lp/mm，%d 点" % (freqs[0], freqs[-1], len(freqs)))
    for i, (nm, d) in enumerate(fields, 1):
        print("  F%d %s" % (i, nm))

    if a.csv:
        os.makedirs(os.path.dirname(os.path.abspath(a.csv)), exist_ok=True)
        hdr = ["freq"]
        if diff:
            hdr += ["diff_T", "diff_S"]
        for i in range(1, len(fields) + 1):
            hdr += ["F%d_T" % i, "F%d_S" % i]
        with open(a.csv, "w", encoding="utf-8") as fh:
            fh.write(",".join(hdr) + "\n")
            for f in freqs:
                row = [f]
                if diff:
                    row += list(diff[1].get(f, ("", "")))
                for _, d in fields:
                    row += list(d.get(f, ("", "")))
                fh.write(",".join(
                    ("%.6g" % v) if isinstance(v, float) else str(v) for v in row) + "\n")
        print("CSV: %s（%d 行 × %d 列）" % (os.path.abspath(a.csv), len(freqs), len(hdr)))

    rf = a.report_freq if a.report_freq in freqs else freqs[-1]
    print("\n@%.0f lp/mm  T / S" % rf)
    for i, (nm, d) in enumerate(fields, 1):
        t, s = d.get(rf, (float("nan"), float("nan")))
        print("  F%d %-34s %.4f / %.4f" % (i, nm, t, s))
    if diff:
        t, s = diff[1].get(rf, (float("nan"), float("nan")))
        print("  衍射极限%-30s %.4f / %.4f" % ("", t, s))
    vals = [v for _, d in fields for pair in [d.get(rf)] if pair for v in pair if v == v]
    if vals:
        print("  最差 %.4f   平均 %.4f" % (min(vals), sum(vals) / len(vals)))


if __name__ == "__main__":
    main()
