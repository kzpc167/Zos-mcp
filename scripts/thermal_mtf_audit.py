# -*- coding: utf-8 -*-
"""逐组态实测原生 FFT MTF，输出全温像质表（通用版）。

取代早期的 thermal_mtf_per_config.py / thermal_mtf_corrected.py（两个只差一个偏移量）。

为什么必须逐组态跑原生 FFT MTF：
  120 lp/mm 处的 MTF 随焦面 1 um 级变动会跳变，用 3 点抛物线扫焦拟合出的"最佳焦面"
  不可靠（本项目实测 25 C 低估 0.10，结论方向都反了）。焦点扫描只适合用点列图 RMS 判据。

依赖仓库 venv（系统 python 缺 concurrent_log_handler / win32com）：
    .venv\\Scripts\\python.exe scripts\\thermal_mtf_audit.py --zos "...\\xxx_无热化.zos"
    .venv\\Scripts\\python.exe scripts\\thermal_mtf_audit.py --zos ... --freq 100
    .venv\\Scripts\\python.exe scripts\\thermal_mtf_audit.py --zos ... --shift-um 2.758 --csv tmp\\audit.csv
    .venv\\Scripts\\python.exe scripts\\thermal_mtf_audit.py --zos ... --mode extension

参数：
    --zos       .zos 路径（必填）
    --freq      空间频率 lp/mm，默认 120
    --shift-um  给像面 THIC 的所有组态加同一偏移（um），默认 0；只改内存，不存盘
    --ref       参考温度 C，用来算跌幅；默认取最接近 25 C 的组态
    --mode      standalone（默认，独立实例，不动 GUI）| extension（复用 GUI，需激活 Interactive Extension）
    --instance  ZOS-API 实例号，默认 0
    --csv       可选，结果另存 CSV
    --save      存盘（默认不存，避免污染交付文件）
"""
import argparse
import io
import json
import os
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from zemax_connection import ZemaxConnection   # noqa: E402
    from tools import ZemaxToolkit                 # noqa: E402
except ModuleNotFoundError as e:
    sys.exit("缺少依赖 %s —— 请用仓库 venv 运行：\n"
             "  .venv\\Scripts\\python.exe scripts\\thermal_mtf_audit.py --zos <文件>" % e.name)


def read_text_any(path):
    raw = open(path, "rb").read()
    for enc in ("utf-16", "utf-8", "gbk"):
        try:
            return raw.decode(enc)
        except Exception:
            continue
    return raw.decode("utf-8", errors="replace")


def parse_mtf_blocks(text):
    """返回 [(块名, {freq: (T, S)})]；块按文件顺序，第一块通常是衍射极限。"""
    blocks, name, data = [], None, {}
    for ln in text.splitlines():
        s = ln.strip()
        if s.startswith("视场") or s.lower().startswith("field"):
            if name is not None:
                blocks.append((name, data))
            name, data = s, {}
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


def value_at(data, freq):
    if freq in data:
        return data[freq]
    if not data:
        return (float("nan"), float("nan"))
    k = min(data, key=lambda x: abs(x - freq))
    return data[k]


def is_diffraction(name):
    return ("衍射" in name) or ("limit" in name.lower())


def find_operand(mce, type_name, param1=None):
    for r in range(1, int(mce.NumberOfOperands) + 1):
        o = mce.GetOperandAt(r)
        if str(o.typeName).split(":")[-1].strip() != type_name:
            continue
        if param1 is None or int(o.Param1) == int(param1):
            return o
    return None


def main():
    ap = argparse.ArgumentParser(description="Per-config native FFT MTF audit")
    ap.add_argument("--zos", required=True)
    ap.add_argument("--freq", type=float, default=120.0)
    ap.add_argument("--shift-um", type=float, default=0.0)
    ap.add_argument("--ref", type=float, default=None)
    ap.add_argument("--mode", choices=["standalone", "extension"], default="standalone")
    ap.add_argument("--instance", type=int, default=0)
    ap.add_argument("--csv", default=None)
    ap.add_argument("--save", action="store_true")
    a = ap.parse_args()

    zos = os.path.abspath(a.zos)
    if not os.path.isfile(zos):
        sys.exit("找不到文件: %s" % zos)

    conn = ZemaxConnection()
    conn.connect(mode=a.mode, instance=a.instance)
    try:
        s = conn.system
        s.LoadFile(zos, False)
        tk = ZemaxToolkit(conn)

        lde = s.LDE
        image_surf = int(lde.NumberOfSurfaces) - 1
        mce = s.MCE
        n_cfg = int(mce.NumberOfConfigurations) if mce is not None else 1
        print("文件: %s" % zos)
        print("像面: 面 %d    组态数: %d    频率: %.1f lp/mm" % (image_surf, n_cfg, a.freq))

        # ---- 可选：像面间隔整体平移（热模型基准与设计终版不一致时用）----
        if abs(a.shift_um) > 0:
            delta = a.shift_um / 1000.0
            if n_cfg > 1 and find_operand(mce, "THIC", image_surf) is not None:
                row = find_operand(mce, "THIC", image_surf)
                base = float(row.GetOperandCell(1).DoubleValue)
                for c in range(1, n_cfg + 1):
                    cell = row.GetOperandCell(c)
                    cell.DoubleValue = float(cell.DoubleValue) + delta
                print("像面 THIC 平移 %+0.3f um（组态1: %.6f -> %.6f，仅内存）"
                      % (a.shift_um, base, base + delta))
            else:
                surf = lde.GetSurfaceAt(image_surf)
                old = float(surf.Thickness)
                surf.Thickness = old + delta
                print("像面厚度平移 %+0.3f um（%.6f -> %.6f，仅内存）"
                      % (a.shift_um, old, old + delta))

        temp_row = find_operand(mce, "TEMP") if n_cfg > 1 else None

        rows = []
        for cfg in range(1, n_cfg + 1):
            if n_cfg > 1:
                mce.SetCurrentConfiguration(cfg)
            temp = float("nan")
            if temp_row is not None:
                try:
                    temp = float(temp_row.GetOperandCell(cfg).DoubleValue)
                except Exception:
                    temp = float("nan")

            payload = json.loads(tk.export_analysis_data(
                "fft_mtf", settings={"max_frequency": a.freq},
                export_image=False, export_text=True, keep_window=False))
            text_path = (payload.get("exports") or {}).get("text_path")
            if not text_path or not os.path.isfile(text_path):
                sys.exit("组态 %d: MTF 文本导出失败 (%s)" % (cfg, payload.get("warnings")))
            blocks = parse_mtf_blocks(read_text_any(text_path))
            diff = [b for b in blocks if is_diffraction(b[0])]
            fields = [b for b in blocks if not is_diffraction(b[0])]
            vals = [value_at(d, a.freq) for _, d in fields]
            flat = [v for pair in vals for v in pair if v == v]
            mn = min(flat) if flat else float("nan")
            rows.append({"cfg": cfg, "temp": temp, "vals": vals, "min": mn,
                         "limit": value_at(diff[0][1], a.freq)[0] if diff else float("nan")})
            print("  cfg%-2d T=%7.2f C  最小 min(T,S)=%.4f" % (cfg, temp, mn))
            sys.stdout.flush()

        # ---- 参考组态 ----
        ref_idx = 0
        if a.ref is not None and any(r["temp"] == r["temp"] for r in rows):
            ref_idx = min(range(len(rows)),
                          key=lambda i: abs(rows[i]["temp"] - a.ref)
                          if rows[i]["temp"] == rows[i]["temp"] else 1e9)
        else:
            ref_idx = 0
            if any(r["temp"] == r["temp"] for r in rows):
                ref_idx = min(range(len(rows)),
                              key=lambda i: abs(rows[i]["temp"] - 25.0)
                              if rows[i]["temp"] == rows[i]["temp"] else 1e9)

        nf = max((len(r["vals"]) for r in rows), default=0)
        hdr = ["温度C"] + ["F%d_T/F%d_S" % (i + 1, i + 1) for i in range(nf)] + ["min", "相对参考%"]
        print("\n%-8s %s %8s %10s" % ("温度C", "  ".join("%-13s" % h for h in hdr[1:-2]),
                                      "min", "vs 参考"))
        for i, r in enumerate(rows):
            cells = ["%.3f/%.3f" % v for v in r["vals"]] + ["      "] * (nf - len(r["vals"]))
            rel = (r["min"] / rows[ref_idx]["min"] - 1.0) * 100 if rows[ref_idx]["min"] else float("nan")
            mark = "  <- 参考" if i == ref_idx else ""
            print("%8.1f %s %8.4f %+9.1f%%%s"
                  % (r["temp"], "  ".join("%-13s" % c for c in cells), r["min"], rel, mark))

        worst = min(rows, key=lambda r: r["min"])
        ref = rows[ref_idx]
        drop = (1 - worst["min"] / ref["min"]) * 100 if ref["min"] else float("nan")
        print("\n最差组态: %.1f C  min(T,S)=%.4f" % (worst["temp"], worst["min"]))
        print("相对参考(%.1f C, %.4f) 跌幅: %.1f%%   %s"
              % (ref["temp"], ref["min"], drop,
                 "OK（<=20%）" if drop <= 20 else "超 20% 判据"))
        if rows[0]["limit"] == rows[0]["limit"]:
            print("衍射极限 @%.0f lp/mm: %.4f" % (a.freq, rows[0]["limit"]))

        if a.csv:
            os.makedirs(os.path.dirname(os.path.abspath(a.csv)), exist_ok=True)
            with open(a.csv, "w", encoding="utf-8") as fh:
                fh.write("temp_C,cfg," + ",".join(
                    "F%d_T,F%d_S" % (i + 1, i + 1) for i in range(nf)) + ",min_T_S\n")
                for r in rows:
                    flat = []
                    for i in range(nf):
                        pair = r["vals"][i] if i < len(r["vals"]) else ("", "")
                        flat += ["%.6g" % pair[0] if pair[0] == pair[0] else "",
                                 "%.6g" % pair[1] if pair[1] == pair[1] else ""]
                    fh.write("%.1f,%d,%s,%.6g\n" % (r["temp"], r["cfg"], ",".join(flat), r["min"]))
            print("CSV: %s" % os.path.abspath(a.csv))

        if a.save:
            s.Save()
            print("已存盘: %s" % s.SystemFile)
        else:
            print("未存盘（内存改动随会话丢弃；需要固化作业加 --save）")
    finally:
        conn.disconnect()


if __name__ == "__main__":
    main()
