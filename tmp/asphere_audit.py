# -*- coding: utf-8 -*-
"""偶次非球面(Even Asphere)可制造性量化体检  —— 纯 Python，解析求导"""
import math, json

SURF = [
    dict(name="面 1 (S1, L1 前)", lens="L1", R=44.39296915683807, k=-1.0,
         A4=-9.76883737652111e-05, A6=-3.2049625404608993e-07,
         rmax=7.592485503227117, CT=3.5046046165655347, ET=4.8372),
    dict(name="面 13 (S12, L7 前)", lens="L7", R=-6.482159673955799, k=-1.0,
         A4=0.0004539716122787671, A6=1.0578287683169352e-06,
         rmax=4.849611410756276, CT=1.2906401020293348, ET=3.0332),
]

def c_of(p):   return 1.0 / p["R"]
def rad(p, r):                      # sqrt 项
    c = c_of(p); t = 1.0 - (1.0 + p["k"]) * c * c * r * r
    return math.sqrt(t) if t > 0 else float("nan")
def sag(p, r):
    c = c_of(p); s = rad(p, r)
    base = c * r * r / (1.0 + s) if s == s else float("nan")
    return base + p["A4"]*r**4 + p["A6"]*r**6
def d1(p, r):                       # dz/dr
    c = c_of(p); s = rad(p, r)
    return c*r/s + 4*p["A4"]*r**3 + 6*p["A6"]*r**5
def d2(p, r):                       # d2z/dr2
    c = c_of(p); s = rad(p, r)
    return c/(s**3) + 12*p["A4"]*r**2 + 30*p["A6"]*r**4
def zsph(Rb, r):
    s = 1.0 if Rb > 0 else -1.0
    return Rb - s*math.sqrt(Rb*Rb - r*r)

def bisect(f, a, b, it=200):
    fa = f(a)
    for _ in range(it):
        m = 0.5*(a+b); fm = f(m)
        if fa*fm <= 0: b = m
        else: a, fa = m, fm
    return 0.5*(a+b)

def audit(p, n=2001):
    rmax = p["rmax"]
    rs = [rmax*i/(n-1) for i in range(n)]
    out = {}
    # ---- 维度1a 最大斜率角
    best = max(range(n), key=lambda i: abs(d1(p, rs[i])))
    out["slope_max_deg"] = math.degrees(math.atan(abs(d1(p, rs[best]))))
    out["slope_max_at"]   = rs[best]
    out["slope_edge_deg"] = math.degrees(math.atan(abs(d1(p, rmax))))
    out["slope_sign_edge"]= "负(下翻)" if d1(p, rmax) < 0 else "正(上翘)"
    # ---- 维度1b 反曲: dz/dr 在 (0, rmax] 内变号
    roots = []
    for i in range(n-1):
        a, b = rs[i], rs[i+1]
        if a <= 1e-9: continue
        if d1(p, a) * d1(p, b) < 0:
            roots.append(bisect(lambda x: d1(p, x), a, b))
    out["inflection_r"] = roots
    out["inflection_inside"] = any(r < rmax for r in roots)
    # ---- 维度3 最佳拟合球
    def rss(Rb):
        if Rb > 0:
            if Rb <= rmax: return 1e18, 0
        else:
            if -Rb <= rmax: return 1e18, 0
        fs = [zsph(Rb, r) for r in rs]
        zs_ = [sag(p, r) for r in rs]
        zc = sum(z - f for z, f in zip(zs_, fs))/n
        return sum((z - (zc + f))**2 for z, f in zip(zs_, fs)), zc
    R0 = p["R"]
    lo, hi = (rmax*1.0005, abs(R0)*8) if R0 > 0 else (-abs(R0)*8, -rmax*1.0005)
    gr = (math.sqrt(5)-1)/2
    for _ in range(300):
        a = hi - gr*(hi-lo); b = lo + gr*(hi-lo)
        if rss(a)[0] < rss(b)[0]: hi = b
        else: lo = a
    Rb = 0.5*(lo+hi); _r, zc = rss(Rb)
    devs = [sag(p, r) - (zc + zsph(Rb, r)) for r in rs]
    out["bfs_R"] = Rb
    out["bfs_max_dev_um"] = max(abs(d) for d in devs)*1000
    out["bfs_pv_um"]  = (max(devs)-min(devs))*1000
    out["bfs_dev_at_edge_um"] = devs[-1]*1000
    # 顶点球(只用 R)偏离，作参考
    dv = [sag(p, r) - zsph(p["R"], r) for r in rs]
    out["vertex_sphere_dev_um"] = max(abs(d) for d in dv)*1000
    # ---- 维度4 局部曲率
    rl = []
    for r in rs:
        k_ = d2(p, r); s_ = d1(p, r)
        rl.append((1.0+s_*s_)**1.5/abs(k_) if k_ != 0 else float("inf"))
    out["Rloc_center"] = rl[0]
    out["Rloc_edge"]   = rl[-1]
    out["Rloc_min"]    = min(rl)
    out["Rloc_max"]    = max(rl)
    out["Rloc_min_at"] = rs[rl.index(min(rl))]
    # 曲率半径沿口径的单调性 / 突变
    dR = [(rl[i+1]-rl[i])/(rs[i+1]-rs[i]) for i in range(n-1)]
    out["dR_max_abs"] = max(abs(x) for x in dR)
    out["dR_max_at"]  = rs[dR.index(max(dR, key=abs))]
    out["Rloc_ratio"] = max(rl)/min(rl)
    # 二阶导变号(拐点)
    ip = []
    for i in range(n-1):
        if d2(p, rs[i]) * d2(p, rs[i+1]) < 0:
            ip.append(bisect(lambda x: d2(p, x), rs[i], rs[i+1]))
    out["curv_inflection_r"] = ip
    out["_rs"], out["_slope_deg"], out["_dev_um"], out["_Rloc"] = rs, \
        [math.degrees(math.atan(abs(d1(p, r)))) for r in rs], \
        [d*1000 for d in devs], rl
    return out

res = {}
for p in SURF:
    a = audit(p)
    res[p["name"]] = a
    print("="*78); print(p["name"])
    print("  透镜 %s  CT=%.3f mm  ET=%.3f mm  半口径=%.3f mm  R=%.3f  k=%.1f" %
          (p["lens"], p["CT"], p["ET"], p["rmax"], p["R"], p["k"]))
    print("  [维度1] 最大斜率角 %.2f°  (在 r=%.3f mm)   边缘斜率 %.2f° %s" %
          (a["slope_max_deg"], a["slope_max_at"], a["slope_edge_deg"], a["slope_sign_edge"]))
    if a["inflection_r"]:
        print("         ⚠ 反曲点 r = %s mm ; 口径 %.3f mm → %s" %
              (["%.3f"%x for x in a["inflection_r"]], p["rmax"],
               "在通光口径内" if a["inflection_inside"] else "在口径外"))
    else:
        print("         无反曲（dz/dr 在口径内不变号）")
    print("  [维度3] BFS R=%.3f mm  最大偏离=%.2f µm  PV=%.2f µm  边缘偏离=%.2f µm" %
          (a["bfs_R"], a["bfs_max_dev_um"], a["bfs_pv_um"], a["bfs_dev_at_edge_um"]))
    print("          (顶点球基准偏离 %.2f µm)" % a["vertex_sphere_dev_um"])
    print("  [维度4] 局部曲率半径: 中心 %.2f → 边缘 %.2f mm ; 最小 %.2f (r=%.2f) ; max/min=%.2f" %
          (a["Rloc_center"], a["Rloc_edge"], a["Rloc_min"], a["Rloc_min_at"], a["Rloc_ratio"]))
    print("          dR/dr 最大 |%.1f| mm/mm @ r=%.2f" % (a["dR_max_abs"], a["dR_max_at"]))
    if a["curv_inflection_r"]:
        print("          z'' 变号(拐点) r = %s" % (["%.3f"%x for x in a["curv_inflection_r"]]))

json.dump({k: {kk: vv for kk, vv in v.items() if not kk.startswith("_")} for k, v in res.items()},
          open("D:/Zemax-mcp/tmp/asphere_audit.json", "w", encoding="utf-8"),
          ensure_ascii=False, indent=2)

# 供画图导出的抽样数组
for p in SURF:
    a = res[p["name"]]; tag = "S1" if p["R"] > 0 else "S13"
    with open("D:/Zemax-mcp/tmp/curve_%s.csv" % tag, "w") as f:
        f.write("r,slope_deg,dev_um,Rloc\n")
        for i in range(0, len(a["_rs"]), 20):
            f.write("%.4f,%.3f,%.3f,%.3f\n" % (a["_rs"][i], a["_slope_deg"][i],
                                               a["_dev_um"][i], a["_Rloc"][i]))
print("\n[ok] 数据已写出")
