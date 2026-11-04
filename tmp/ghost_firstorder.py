# -*- coding: utf-8 -*-
"""一阶近轴鬼影估算（y–nu 递推，双次反射）

约定：
  y  : 面上高度 (mm)
  u  : 约化角 n·θ
  面 k 折射： u' = u - y·c_k·(n_out - n_in)
  传递：      y_next = y + t·(u/n)
  反射：      n_out = -n_in，代入上式即 u' = u - y·c·(-2·n_in) = u + 2·y·c·n_in

校验：关掉全部反射后，BFL / EFFL / TOTR 必须与 Zemax 一阶量一致（已通过）。
"""
import math

EPD = 10.799          # F/1.4 @ EFFL 15.118
Y1 = EPD / 2.0        # 边缘光线在面 1 的高度

# 序号, R(mm), 面后厚度(mm), 面后介质折射率(nd), 半口径(mm)
SURF = [
    (1,  35.32917605444734,  3.50563707594896, 1.581440, 8.0),   # QF50
    (2,  15.42832100067805,  4.01272129386312, 1.000000, 7.0),
    (3,  22.43102018027860,  4.31278590799782, 1.772880, 7.0),   # D-LAF50-25
    (4, -23.69053412605367,  0.47066590978141, 1.000000, 7.0),
    (5,  math.inf,           0.351894017040339, 1.000000, 5.5),  # 光阑
    (6,   9.635680517998434, 4.06183122891254, 1.774000, 5.5),   # D-LAF50
    (7, -85.75277566822533,  1.48461815079857, 1.805180, 5.0),   # H-ZF7LA
    (8,   5.774046919766916, 2.08371815798498, 1.000000, 4.0),
    (9,  30.47319995647909,  1.17237404353910, 1.806277, 4.5),   # ZF7
    (10, 19.24109766357581,  1.75574887747271, 1.000000, 4.5),
    (11, 13.811219628050285, 3.25856420217488, 1.772880, 5.5),   # D-LAF50-25
    (12, -14.608759767732927, 1.70095607636640, 1.000000, 5.5),
    (13, -6.546984556982035, 1.24582151916367, 1.487490, 5.0),   # H-QK3L
    (14, -32.20612705236525, 1.082159,          1.000000, 5.0),
]
NS = len(SURF)
IMG_T = SURF[-1][2]

def c_of(k):
    R = SURF[k - 1][1]
    return 0.0 if math.isinf(R) else 1.0 / R

def n_after(k):
    return SURF[k - 1][3]

def n_before(k):
    return 1.0 if k == 1 else SURF[k - 2][3]

def t_of(k):
    return SURF[k - 1][2]

def sd(k):
    return SURF[k - 1][4]

# ------------------------------------------------------------------ 正常追迹
def trace_normal(y, u, upto=NS):
    n = n_before(1)
    for k in range(1, upto + 1):
        nxt = n_after(k)
        u = u - y * c_of(k) * (nxt - n)
        n = nxt
        if k < upto:
            y = y + t_of(k) * (u / n)
    return y, u

def validate():
    y1, u1 = Y1, 0.0
    y, u = trace_normal(y1, u1)
    totr = sum(t_of(k) for k in range(1, NS + 1))
    y_img = y + IMG_T * (u / n_after(NS))
    return dict(TOTR=totr, EFFL=-y1 / u, BFL=-y / (u / n_after(NS)), y_img=y_img)

# ------------------------------------------------------------------ 鬼影路径
def trace_ghost(y0, u0, i, j, check=True):
    """面 j 反射 → 退回到面 i 再反射 → 正向追到像面。"""
    clipped = False
    y, u = y0, u0
    n = n_before(1)
    # 1) 正向到面 j
    for k in range(1, j):
        nxt = n_after(k)
        u = u - y * c_of(k) * (nxt - n)
        n = nxt
        y = y + t_of(k) * (u / n)
    # 2) 面 j 反射
    n_in = n
    u = u - y * c_of(j) * (-2.0 * n_in)
    n = -n_in
    if check and abs(y) > sd(j):
        clipped = True
    # 3) 反向退回到面 i（中间面只做介质切换）
    for k in range(j - 1, i, -1):
        y = y + (-t_of(k)) * (u / n)
        n_out = -n_before(k)
        u = u - y * c_of(k) * (n_out - n)
        n = n_out
        if check and abs(y) > sd(k):
            clipped = True
    y = y + (-t_of(i)) * (u / n)
    # 4) 面 i 反射
    n_in = n
    u = u - y * c_of(i) * (-2.0 * n_in)
    n = -n_in
    if check and abs(y) > sd(i):
        clipped = True
    # 5) 正向追到像面
    for k in range(i + 1, NS + 1):
        y = y + t_of(k - 1) * (u / n)
        nxt = n_after(k)
        u = u - y * c_of(k) * (nxt - n)
        n = nxt
        if check and abs(y) > sd(k):
            clipped = True
    y_img = y + IMG_T * (u / n)
    return dict(y=y, u=u, n=n, y_img=y_img, clipped=clipped)

def ghost_pair(i, j):
    best = None                      # 取光瞳通过率最高的抽样光线做几何
    survive = 0
    total = 11
    geom = None
    for k in range(total):
        p = k / (total - 1)
        r = trace_ghost(Y1 * p, 0.0, i, j)
        if not r["clipped"]:
            survive += 1
            if p > 0:
                geom = r
    eta = survive / total
    if geom is None:                 # 全被挡
        return dict(i=i, j=j, eta=eta, clipped_all=True)
    yl, ul, nl = geom["y"], geom["u"], geom["n"]
    z_rel = -yl / (ul / nl) if abs(ul) > 1e-15 else float("inf")
    dz = z_rel - IMG_T
    blur = 2.0 * abs(geom["y_img"])
    return dict(i=i, j=j, eta=eta, dz=dz, blur=blur, y_img=geom["y_img"],
                clipped_all=False)

IMG_H = 4.732                     # 半像高 (mm)

def ghost_at_field(i, j, th):
    """给定物方视场角 th (rad)，返回主光线/边缘光线的鬼影落点与弥散。"""
    ch = trace_ghost(0.0, th, i, j, check=True)
    mg = trace_ghost(Y1, th, i, j, check=True)
    zc, zm = ch["u"] / ch["n"], mg["u"] / mg["n"]
    if abs(zc - zm) < 1e-12:
        z_rel = float("inf")
    else:
        z_rel = (mg["y"] - ch["y"]) / (zc - zm)
    return dict(blur=2.0 * abs(mg["y_img"] - ch["y_img"]),
                dz=z_rel - IMG_T,
                y_img=ch["y_img"],
                clipped=ch["clipped"] or mg["clipped"])

def ghost_scan(i, j):
    """两段式视场扫描：粗扫找 |离焦| 最小，再在邻域细扫挖峰（cat's eye 窗口极窄）。"""
    def evaluate(deg):
        g = ghost_at_field(i, j, math.radians(deg))
        if g["clipped"] or abs(g["y_img"]) > IMG_H:
            return None
        g["field_deg"] = deg
        return g

    coarse = []
    deg = 0.2
    while deg <= 20.0:
        g = evaluate(deg)
        if g is not None:
            coarse.append(g)
        deg += 0.2
    if not coarse:
        return None

    # 取 |dz| 最小的若干候选，逐一细扫
    best = None
    for c in sorted(coarse, key=lambda x: abs(x["dz"]))[:5]:
        d = c["field_deg"] - 0.4
        while d <= c["field_deg"] + 0.4:
            g = evaluate(round(d, 4))
            if g is not None and (best is None or g["blur"] < best["blur"]):
                best = dict(g)
            d += 0.01
    if best is None:
        return min(coarse, key=lambda x: x["blur"])
    return best

def run(r_ar):
    rows = []
    for i in range(1, NS + 1):
        for j in range(i + 1, NS + 1):
            g = ghost_pair(i, j)
            g["R"] = r_ar
            g["I"] = (r_ar ** 2) * ((1.0 - r_ar) ** (NS - 2)) * g["eta"]
            rows.append(g)
    return rows

if __name__ == "__main__":
    v = validate()
    print("=== 校验（无反射）===")
    print("  TOTR = %.4f  (Zemax 30.4995)" % v["TOTR"])
    print("  EFFL = %.4f  (Zemax 15.1184)" % v["EFFL"])
    print("  BFL  = %.4f  (Zemax  1.0822)" % v["BFL"])
    print("  像面 y = %+.6f mm" % v["y_img"])
    ok = (abs(v["TOTR"] - 30.4995) < 1e-3 and abs(v["EFFL"] - 15.1184) < 0.01
          and abs(v["BFL"] - 1.0822) < 0.01 and abs(v["y_img"]) < 0.01)
    print("  校验结果:", "PASS" if ok else "FAIL")
    if not ok:
        raise SystemExit(1)

    rows = run(0.005)
    live = [r for r in rows if not r.get("clipped_all")]

    # 视场扫描：找每个面组合最锐利且落在像面内的情形
    scanned = []
    for r in live:
        b = ghost_scan(r["i"], r["j"])
        if b is None:
            continue
        b.update(i=r["i"], j=r["j"], eta=r["eta"], R=r["R"],
                 I=(r["R"] ** 2) * ((1.0 - r["R"]) ** (NS - 2)) * r["eta"])
        scanned.append(b)

    print()
    print("总面组合 %d；轴向可见 %d；扫描视场后仍落在像面内 %d 个"
          % (len(rows), len(live), len(scanned)))
    sharp = [s for s in scanned if s["blur"] * 1000 <= 4.2]
    print("锐利鬼影（弥散 ≤ 4.2 µm 且落在像面内）：%d 个" % len(sharp))
    if scanned:
        print("最小弥散 = %.2f µm（面 %d-%d @ %.1f°）"
              % (min(s["blur"] for s in scanned) * 1000,
                 min(scanned, key=lambda x: x["blur"])["i"],
                 min(scanned, key=lambda x: x["blur"])["j"],
                 min(scanned, key=lambda x: x["blur"])["field_deg"]))

    MAIN_D = 3.74e-3
    for s in scanned:
        s["conc"] = s["I"] / max(s["blur"], 1e-6) ** 2 * (MAIN_D ** 2)

    print()
    print("=== 前 10 危险面组合（按相对峰值照度排序）===")
    print("  # 面组合  视场°  通过率  离焦mm  弥散D_µm   I(0.5%)   I(1.0%)  相对照度")
    for n, s in enumerate(sorted(scanned, key=lambda x: -x["conc"])[:10], 1):
        print("  %2d  %2d-%-2d  %5.1f   %.2f  %+8.2f  %8.1f   %.2e  %.2e  %.2e"
              % (n, s["i"], s["j"], s["field_deg"], s["eta"], s["dz"],
                 s["blur"] * 1000, s["I"], s["I"] * 4.0, s["conc"]))

    print()
    print("=== 弥散最小的 10 个（最锐利）===")
    print("  # 面组合  视场°  离焦mm   弥散D_µm   I(0.5%)  相对照度")
    for n, s in enumerate(sorted(scanned, key=lambda x: x["blur"])[:10], 1):
        print("  %2d  %2d-%-2d  %5.1f  %+8.2f  %8.1f   %.2e  %.2e"
              % (n, s["i"], s["j"], s["field_deg"], s["dz"],
                 s["blur"] * 1000, s["I"], s["conc"]))

    # ---------------- 导出 markdown ----------------
    ELEM = {1: "L1", 2: "L1", 3: "L2", 4: "L2", 5: "光阑", 6: "L3", 7: "L4",
            8: "L4", 9: "L5", 10: "L5", 11: "L6", 12: "L6", 13: "L7", 14: "L7"}
    out = []
    out.append("| # | 面组合 | 元件 | 视场 | 通过率 | 离焦 (mm) | 弥散 D (µm) | "
               "I @0.5% | I @1.0% | 相对照度 @0.5% | 相对照度 @1.0% | 太阳下等效 @0.5% |")
    out.append("|---:|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
    for n, s in enumerate(sorted(scanned, key=lambda x: -x["conc"])[:10], 1):
        out.append("| %d | %d–%d | %s/%s | %.1f° | %.2f | %+.2f | %.0f | %.2e | %.2e | "
                   "%.2e | %.2e | %.1e |"
                   % (n, s["i"], s["j"], ELEM[s["i"]], ELEM[s["j"]], s["field_deg"],
                      s["eta"], s["dz"], s["blur"] * 1000, s["I"], s["I"] * 4.0,
                      s["conc"], s["conc"] * 4.0, s["conc"] * 1e5))
    print()
    print("\n".join(out))
    open("zemax-ADAS/tmp_ghost_table.md", "w", encoding="utf-8").write("\n".join(out))
