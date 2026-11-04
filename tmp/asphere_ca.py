# -*- coding: utf-8 -*-
"""按「物理半口径」与「实际通光口径(clear aperture)」双口径复算"""
import math

SURF = [
    dict(tag="面1 / L1前", R=44.39296915683807, k=-1.0, A4=-9.76883737652111e-05,
         A6=-3.2049625404608993e-07, rphys=7.592485503227117, rca=6.443224149734212),
    dict(tag="面13 / L7前", R=-6.482159673955799, k=-1.0, A4=0.0004539716122787671,
         A6=1.0578287683169352e-06, rphys=4.849611410756276, rca=2.947574376643436),
]
def c(p): return 1.0/p["R"]
def s_(p,r): 
    t = 1.0-(1.0+p["k"])*c(p)**2*r*r
    return math.sqrt(t) if t>0 else float("nan")
def sag(p,r): return c(p)*r*r/(1.0+s_(p,r)) + p["A4"]*r**4 + p["A6"]*r**6
def d1(p,r):  return c(p)*r/s_(p,r) + 4*p["A4"]*r**3 + 6*p["A6"]*r**5
def d2(p,r):  return c(p)/s_(p,r)**3 + 12*p["A4"]*r**2 + 30*p["A6"]*r**4
def zsph(Rb,r):
    sg = 1.0 if Rb>0 else -1.0
    return Rb - sg*math.sqrt(Rb*Rb-r*r)

def stats(p, rmax, n=1500):
    rs=[rmax*i/(n-1) for i in range(n)]
    o={}
    sl=[abs(d1(p,r)) for r in rs]
    o["slope"]=math.degrees(math.atan(max(sl))); o["slope_r"]=rs[sl.index(max(sl))]
    # 反曲
    o["inf"]=[]
    for i in range(1,n-1):
        if d1(p,rs[i])*d1(p,rs[i+1])<0:
            a,b=rs[i],rs[i+1]; fa=d1(p,a)
            for _ in range(120):
                m=0.5*(a+b)
                if fa*d1(p,m)<=0: b=m
                else: a,fa=m,d1(p,m)
            o["inf"].append(0.5*(a+b))
    # BFS
    def rss(Rb):
        if abs(Rb)<=rmax: return 1e18,0
        fs=[zsph(Rb,r) for r in rs]; zz=[sag(p,r) for r in rs]
        zc=sum(z-f for z,f in zip(zz,fs))/n
        return sum((z-(zc+f))**2 for z,f in zip(zz,fs)), zc
    lo,hi=(rmax*1.0005, abs(p["R"])*8) if p["R"]>0 else (-abs(p["R"])*8,-rmax*1.0005)
    gr=(math.sqrt(5)-1)/2
    for _ in range(250):
        a=hi-gr*(hi-lo); b=lo+gr*(hi-lo)
        if rss(a)[0]<rss(b)[0]: hi=b
        else: lo=a
    Rb=0.5*(lo+hi); _,zc=rss(Rb)
    dv=[sag(p,r)-(zc+zsph(Rb,r)) for r in rs]
    o["bfsR"]=Rb; o["dev"]=max(abs(x) for x in dv)*1000; o["pv"]=(max(dv)-min(dv))*1000
    # 局部曲率
    rl=[(1+d1(p,r)**2)**1.5/abs(d2(p,r)) for r in rs]
    o["Rmin"]=min(rl); o["R0"]=rl[0]; o["Red"]=rl[-1]
    o["d2sign"]=d2(p,rs[0])*d2(p,rs[-1])<0
    return o

for p in SURF:
    print("="*70); print(p["tag"])
    for lab,rm in (("物理口径",p["rphys"]),("通光口径",p["rca"])):
        o=stats(p,rm)
        print("  [%s r=%.3f]" % (lab,rm))
        print("    最大斜率角 %.2f° @r=%.2f | BFS R=%.2f 最大偏离 %.1f µm (PV %.1f)" %
              (o["slope"],o["slope_r"],o["bfsR"],o["dev"],o["pv"]))
        print("    局部曲率 中心 %.2f / 最小 %.2f / 边缘 %.2f mm | 曲率变号(拐点)= %s | 反曲点 %s" %
              (o["R0"],o["Rmin"],o["Red"],o["d2sign"],
               ["%.3f"%x for x in o["inf"]] or "无"))
