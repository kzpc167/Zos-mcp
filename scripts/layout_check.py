import math, sys, json

def check(R, T, n, stop, EPD, field_deg, label=""):
    """R: {surf:radius}, T: {surf:thickness_after}, n: {surf:index_after}; stop: stop surface no."""
    def trace(y,u):
        ys={}
        for i in sorted(R.keys()):
            ys[i]=y
            nb,na=n[i-1],n[i]
            c=0.0 if abs(R[i])>1e8 else 1.0/R[i]
            u=(nb*u-y*c*(na-nb))/na
            y=y+T.get(i,0.0)*u
        return ys,u
    surfs=sorted(R.keys())
    last=max(surfs)
    ym,um=trace(EPD/2,0.0)
    efl=-EPD/2/um if abs(um)>1e-12 else float('nan')
    th=math.radians(field_deg)
    ya,_=trace(0.0,-math.tan(th)); yb,_=trace(1.0,-math.tan(th))
    den=(yb[stop]-ya[stop])
    y1=-(ya[stop])/den if abs(den)>1e-12 else 0
    yc,uc=trace(y1,-math.tan(th))
    # petzval
    P=0.0
    for i in surfs:
        nb,na=n[i-1],n[i]
        if abs(na-nb)>1e-9:
            c=0.0 if abs(R[i])>1e8 else 1.0/R[i]
            P+=(na-nb)*c/(na*nb)
    tot=sum(T.get(i,0) for i in surfs)
    print(f"--- {label}: EFFL={efl:.3f}  TOTR={tot:.3f}  imgH={yc[last]:.3f}  CRA={math.degrees(math.atan(uc)):.2f}deg  Petzval={P:.5f} (Rp={1/P if abs(P)>1e-9 else float('inf'):.1f}mm)")
    bad=[]
    print(f"{'s':>3}{'ymarg':>8}{'ychief':>8}{'foot':>8}{'R':>9}{'foot/|R|':>9}{'ok?':>5}")
    for i in surfs:
        f=abs(ym[i])+abs(yc[i]); r=abs(R[i]) if abs(R[i])<1e8 else 1e9
        ratio=f/r
        ok = 'OK' if ratio<=0.9 else 'BAD'
        if ok=='BAD': bad.append((i,round(f,2),round(R[i],2)))
        print(f"{i:>3}{ym[i]:8.2f}{yc[i]:8.2f}{f:8.2f}{R[i]:9.2f}{ratio:9.2f}{ok:>5}")
    if bad: print("  !! 足迹超过 0.9|R|:", bad)
    return efl, bad

if __name__=='__main__':
    R={1:13.0,2:9.0,3:8.5,4:20.0,5:-14.0,6:7.0,7:-11.0,8:15.0,9:-50.0,10:8.5,11:6.5}
    T={1:4.5,2:1.0,3:4.0,4:3.0,5:1.4,6:4.2,7:0.3,8:3.5,9:0.3,10:3.0,11:4.8}
    n={0:1.0,1:1.65,2:1.0,3:1.75,4:1.0,5:1.74,6:1.68,7:1.0,8:1.75,9:1.0,10:1.75,11:1.0}
    check(R,T,n,5,10.7142857,17.5,"candidate A")
