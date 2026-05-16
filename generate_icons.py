#!/usr/bin/env python3
"""Генерирует иконки PWA (192x192 и 512x512)."""
import struct, zlib, base64

def create_png(size):
    """Создаёт минимальный PNG с градиентным фоном и буквой V."""
    # Используем SVG → PNG через cairosvg если доступен, иначе простой PNG
    try:
        import cairosvg
        svg = f"""<svg xmlns='http://www.w3.org/2000/svg' width='{size}' height='{size}'>
          <defs><linearGradient id='g' x1='0' y1='0' x2='1' y2='1'>
            <stop offset='0%' stop-color='#4f7fff'/>
            <stop offset='100%' stop-color='#a78bfa'/>
          </linearGradient></defs>
          <rect width='{size}' height='{size}' rx='{size//5}' fill='url(#g)'/>
          <text x='50%' y='58%' dominant-baseline='middle' text-anchor='middle'
            font-family='sans-serif' font-weight='700' font-size='{size//2}'
            fill='white'>V</text>
        </svg>"""
        return cairosvg.svg2png(bytestring=svg.encode(), output_width=size, output_height=size)
    except ImportError:
        pass

    # Fallback: одноцветный PNG
    img = []
    for y in range(size):
        row = []
        for x in range(size):
            r = int(79  + (167-79) * x/size)
            g = int(127 + (139-127) * y/size)
            b = int(255 + (250-255) * x/size)
            row += [r, g, b, 255]
        img.append(bytes([0] + row))
    raw = b''.join(img)

    def chunk(tag, data):
        c = zlib.crc32(tag + data) & 0xffffffff
        return struct.pack('>I', len(data)) + tag + data + struct.pack('>I', c)

    ihdr = struct.pack('>IIBBBBB', size, size, 8, 2, 0, 0, 0)
    idat = zlib.compress(raw)
    return (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', ihdr) +
            chunk(b'IDAT', idat) + chunk(b'IEND', b''))


if __name__ == '__main__':
    from pathlib import Path
    static = Path('static')
    static.mkdir(exist_ok=True)
    for size, name in [(192, 'icon-192.png'), (512, 'icon-512.png')]:
        data = create_png(size)
        (static / name).write_bytes(data)
        print(f'✅ Создан {name} ({len(data)} байт)')
