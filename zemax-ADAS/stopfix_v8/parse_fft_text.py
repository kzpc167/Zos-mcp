import sys
from math import isnan

def dec(raw):
    for enc in ('utf-16', 'utf-16-le', 'utf-8-sig', 'utf-8', 'latin-1'):
        try:
            return raw.decode(enc)
        except Exception:
            continue
    return raw.decode('latin-1', 'ignore')

p = sys.argv[1]
txt = dec(open(p, 'rb').read())
lines = [l.rstrip() for l in txt.splitlines()]

FIELD = '视场'           # 视场
idx = [i for i, l in enumerate(lines) if l.strip().startswith(FIELD)]
print('field_blocks=%d' % len(idx))

for k, i in enumerate(idx):
    hdr = lines[i].strip()
    print('--- block %d  %s' % (k + 1, hdr.encode('ascii', 'replace').decode()))
    rows = []
    j = i + 1
    blanks = 0
    while j < len(lines):
        s = lines[j].strip()
        if s.startswith(FIELD):
            break
        if not s:
            blanks += 1
            if blanks > 6 and rows:
                break
            j += 1
            continue
        blanks = 0
        parts = s.split()
        try:
            vals = [float(x) for x in parts]
        except Exception:
            j += 1
            continue
        if len(vals) == 3:
            rows.append(vals)
        j += 1
    if not rows:
        print('  (no 3-col rows)')
        continue
    freq = [r[0] for r in rows]
    print('  N=%d  fmax=%.1f' % (len(rows), freq[-1]))
    best = min(range(len(rows)), key=lambda a: abs(freq[a] - 120.0))
    print('  nearest120: f=%.1f  T=%.4f  S=%.4f' % tuple(rows[best]))
    worst = min(min(r[1], r[2]) for r in rows if abs(r[0] - 120.0) < 0.6)
    print('  min_t_s_at120=%.4f' % worst)
