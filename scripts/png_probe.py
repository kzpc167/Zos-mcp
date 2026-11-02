"""纯 Python PNG 解码 + 点列图黑圈测量（无第三方依赖）"""
import zlib, struct, sys

def read_png(path):
    data = open(path, 'rb').read()
    assert data[:8] == b'\x89PNG\r\n\x1a\n', 'not png'
    pos = 8
    idat = b''
    w = h = bitdepth = colortype = None
    palette = None
    while pos < len(data):
        ln = struct.unpack('>I', data[pos:pos+4])[0]
        typ = data[pos+4:pos+8]
        body = data[pos+8:pos+8+ln]
        if typ == b'IHDR':
            w, h, bitdepth, colortype, comp, filt, inter = struct.unpack('>IIBBBBB', body)
        elif typ == b'PLTE':
            palette = body
        elif typ == b'IDAT':
            idat += body
        elif typ == b'IEND':
            break
        pos += 12 + ln
    raw = zlib.decompress(idat)
    channels = {0:1, 2:3, 3:1, 4:2, 6:4}[colortype]
    assert bitdepth == 8, f'bitdepth {bitdepth} unsupported'
    bpp = channels
    stride = w * channels
    out = bytearray(h * stride)
    prev = bytearray(stride)
    p = 0
    for y in range(h):
        ft = raw[p]; p += 1
        line = bytearray(raw[p:p+stride]); p += stride
        if ft == 1:
            for i in range(bpp, stride):
                line[i] = (line[i] + line[i-bpp]) & 0xFF
        elif ft == 2:
            for i in range(stride):
                line[i] = (line[i] + prev[i]) & 0xFF
        elif ft == 3:
            for i in range(stride):
                a = line[i-bpp] if i >= bpp else 0
                line[i] = (line[i] + ((a + prev[i]) >> 1)) & 0xFF
        elif ft == 4:
            for i in range(stride):
                a = line[i-bpp] if i >= bpp else 0
                b = prev[i]
                c = prev[i-bpp] if i >= bpp else 0
                pa, pb, pc = abs(b-c), abs(a-c), abs(a+b-2*c)
                pr = a if (pa <= pb and pa <= pc) else (b if pb <= pc else c)
                line[i] = (line[i] + pr) & 0xFF
        out[y*stride:(y+1)*stride] = line
        prev = line
    if colortype == 3:
        rgb = bytearray(w*h*3)
        for i in range(w*h):
            idx = out[i]*3
            rgb[i*3:i*3+3] = palette[idx:idx+3]
        return w, h, rgb, 3
    return w, h, bytes(out), channels

def is_black(r, g, b, thr=100):
    return r < thr and g < thr and b < thr

def main(path):
    w, h, px, ch = read_png(path)
    print(f'图像 {w} x {h}, channels={ch}')
    def get(x, y):
        i = (y*w + x)*ch
        return px[i], px[i+1], px[i+2]
    # 列黑像素统计
    colblack = [0]*w
    for x in range(w):
        c = 0
        for y in range(h):
            r, g, b = get(x, y)
            if is_black(r, g, b): c += 1
        colblack[x] = c
    # 找长竖线（子图边框）
    runs, inrun, st = [], False, 0
    for x in range(w):
        if colblack[x] >= 80:
            if not inrun: st = x; inrun = True
        else:
            if inrun: runs.append((st, x-1)); inrun = False
    if inrun: runs.append((st, w-1))
    print('竖线列（黑像素>=80）:', runs)
    return w, h, get, colblack

if __name__ == '__main__':
    main(sys.argv[1] if len(sys.argv) > 1 else 'zemax-ADAS/layouts/spot_diagram.png')
