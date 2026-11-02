"""纯 Python：裁切 + 放大 PNG，用于目视核查点列图里的 Airy 圈"""
import zlib, struct, sys
from png_probe import read_png

def write_png(path, w, h, rgb):
    def chunk(typ, body):
        c = struct.pack('>I', len(body)) + typ + body
        return c + struct.pack('>I', zlib.crc32(typ + body) & 0xFFFFFFFF)
    raw = bytearray()
    stride = w*3
    for y in range(h):
        raw.append(0)
        raw += rgb[y*stride:(y+1)*stride]
    out = b'\x89PNG\r\n\x1a\n'
    out += chunk(b'IHDR', struct.pack('>IIBBBBB', w, h, 8, 2, 0, 0, 0))
    out += chunk(b'IDAT', zlib.compress(bytes(raw), 9))
    out += chunk(b'IEND', b'')
    open(path, 'wb').write(out)

def crop_zoom(src, dst, x0, y0, x1, y1, zoom):
    w, h, px, ch = read_png(src)
    cw, chh = x1-x0, y1-y0
    ow, oh = cw*zoom, chh*zoom
    out = bytearray(ow*oh*3)
    for oy in range(oh):
        sy = y0 + oy//zoom
        for ox in range(ow):
            sx = x0 + ox//zoom
            i = (sy*w + sx)*ch
            j = (oy*ow + ox)*3
            out[j:j+3] = px[i:i+3]
    write_png(dst, ow, oh, bytes(out))
    print(f'{dst}: {ow}x{oh}  (源区域 x{x0}-{x1}, y{y0}-{y1}, 放大 {zoom}x)')

if __name__ == '__main__':
    crop_zoom('zemax-ADAS/layouts/spot_diagram.png', 'zemax-ADAS/layouts/_probe_sub1.png',
              58, 66, 268, 276, 4)
