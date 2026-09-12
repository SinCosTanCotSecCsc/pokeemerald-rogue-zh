#!/usr/bin/env python3
"""补齐译文中用到、但 charmap 尚未收录的字符。

处理分两类：

1. **可等价映射**：全角字母 Ａ-Ｚ 映射到对应半角字母的码位，
   日文中点 ・(U+30FB) 映射到已有的中点 ·(U+00B7, AF)。
   这与上游 charmap 对全角数字的处理一致（'０' 与 '0' 同码位 A1），
   不需要新字形。

2. **需要新字形**：既无等价字符、也无法映射的（如 椪）。
   分配新码位并绘制到字库图。绘制范围落在已有字库之后，
   现有字形保持不变。

用法：
    python3 tools/add_glyphs.py --dry-run   # 只报告
    python3 tools/add_glyphs.py             # 写入 charmap 与字库图
"""
import pathlib
import re
import sys
import unicodedata

from PIL import Image, ImageDraw, ImageFont

REPO = pathlib.Path(__file__).resolve().parent.parent

FONT_SIZE = 12
SMALL_SIZE = 10
Y_OFFSET_SMALL = 3

FG, SHADOW, WHITE = 1, 2, 3
PALETTE = [0x90, 0xC8, 0xFF, 0x38, 0x38, 0x38, 0xD8, 0xD8, 0xD8, 0xFF, 0xFF, 0xFF]

FONTS = [
    '/usr/share/fonts/TTF/odosung.ttc',
    '/usr/share/fonts/adobe-source-han-sans/SourceHanSansCN-Regular.otf',
    '/usr/share/fonts/wenquanyi/wqy-microhei/wqy-microhei.ttc',
]

# 可等价映射：目标字符 -> 源字符（源必须已在 charmap 中）
EQUIV = {'・': '·'}
# 全角 Ａ-Ｚ 映射到半角 A-Z
for i in range(26):
    EQUIV[chr(0xFF21 + i)] = chr(ord('A') + i)


def cell_xy(code):
    hi, lo = code >> 8, code & 0xFF
    off = 1 if hi < 0x06 else (2 if hi < 0x1B else 3)
    return (lo & 0x0F) * 16, (hi - off) * 0x100 + (lo >> 4) * 0x10


def load_charmap():
    """返回 (路径, 行, 已收录字符 -> 码位, 中文区最大码位)。"""
    path = REPO / 'charmap.txt'
    lines = path.read_text(encoding='utf-8').splitlines()
    start = next(i for i, l in enumerate(lines) if l.startswith('@Chinese char'))

    known, max_code = {}, 0
    for i, line in enumerate(lines):
        body = line.split('@')[0].strip()
        if not body or '=' not in body:
            continue
        k, v = body.rsplit('=', 1)
        k, v = k.strip(), v.strip().replace(' ', '')
        if not (k.startswith("'") and k.endswith("'")):
            continue
        ch = k[1:-1]
        if len(ch) != 1:
            continue
        try:
            code = int(v, 16)
        except ValueError:
            continue
        known.setdefault(ch, code)
        if i >= start and len(v) == 4:
            max_code = max(max_code, code)
    return path, lines, known, max_code


def scan_texts():
    """译文里用到的所有字符（按出现顺序）。"""
    out = []
    for name in ('zh_CN_names.txt', 'zh_CN.txt'):
        p = REPO / 'translations' / name
        if not p.exists():
            continue
        for line in p.read_text(encoding='utf-8').splitlines():
            m = re.match(r'^"((?:[^"\\]|\\.)*)"\s*=\s*"((?:[^"\\]|\\.)*)"', line.strip())
            if m:
                out += list(m.group(2))
    return out


def draw_glyph(image, code, char, size, y_offset, font):
    x, y = cell_xy(code)
    ImageDraw.Draw(image).rectangle((x, y + y_offset, x + 15, y + 15 + y_offset), fill=WHITE)

    tile = Image.new('RGBA', (size, size + 2), (0, 0, 0, 0))
    td = ImageDraw.Draw(tile)
    for dy in (1, 0):
        for dx in (1, 0):
            td.text((dx, dy), char, '#383838' if (dx + dy) == 0 else '#d8d8d8', font)

    px, ip = tile.load(), image.load()
    for ty in range(tile.height):
        for tx in range(tile.width):
            r, g, b, a = px[tx, ty]
            if a == 0:
                continue
            gx, gy = x + tx, y + y_offset + ty
            if 0 <= gx < image.width and 0 <= gy < image.height:
                ip[gx, gy] = FG if r < 0x80 else SHADOW


def main():
    dry = '--dry-run' in sys.argv
    cmap_path, lines, known, max_code = load_charmap()

    missing, seen = [], set()
    for c in scan_texts():
        if ord(c) >= 0x7F and c not in known and c not in seen:
            seen.add(c)
            missing.append(c)

    if not missing:
        print('字库与 charmap 已覆盖译文中的全部字符。')
        return 0

    equiv, new = {}, []
    for c in missing:
        tgt = EQUIV.get(c)
        if tgt and tgt in known:
            equiv[c] = known[tgt]
        else:
            new.append(c)

    print(f'需要处理 {len(missing)} 个字符：')
    if equiv:
        print(f'\n可等价映射 {len(equiv)} 个（复用已有码位与字形）：')
        for c, code in sorted(equiv.items()):
            print(f'  {c} U+{ord(c):04X} -> {code:#04x} (同 {EQUIV[c]})')
    if new:
        print(f'\n需要新字形 {len(new)} 个：')
        print('  ' + ' '.join(new))
        code = max(max_code, 0x1E6A)
        for c in new:
            code += 1
            print(f'  {c!r} U+{ord(c):04X} -> {code:#06x}')

    if dry:
        return 0

    # 写入 charmap
    add = []
    if equiv:
        add += ['', '@ 等价映射（全角字母等，复用半角字形；由 tools/add_glyphs.py 追加）']
        add += [f"'{c}' = {code:02X}" if code <= 0xFF else f"'{c}' = {code:04X}"
                for c, code in sorted(equiv.items(), key=lambda kv: kv[1])]
    if new:
        code = max(max_code, 0x1E6A)
        add += ['', '@ 补充符号与生僻字（由 tools/add_glyphs.py 追加）']
        for c in new:
            code += 1
            add.append(f"'{c}' = {code:04X}")
    cmap_path.write_text('\n'.join(lines + add) + '\n', encoding='utf-8')
    print(f'\n已更新 {cmap_path}')

    if new:
        fpath = next((f for f in FONTS if pathlib.Path(f).exists()), None)
        if not fpath:
            print('错误：找不到可用的中文字体')
            return 1
        print(f'使用字体: {fpath}')

        code = max(max_code, 0x1E6A)
        codes = []
        for c in new:
            code += 1
            codes.append((c, code))

        need_h = cell_xy(codes[-1][1])[1] + 16
        if need_h % 16:
            need_h += 16 - (need_h % 16)

        for png, size, yoff in [('chinese_normal.png', FONT_SIZE, 0),
                                ('chinese_small.png', SMALL_SIZE, Y_OFFSET_SMALL)]:
            path = REPO / 'graphics/fonts' / png
            img = Image.open(path)
            if img.height < need_h:
                grown = Image.new('P', (img.width, need_h), 0)
                grown.putpalette(PALETTE)
                grown.paste(img, (0, 0))
                img = grown
                print(f'  {png}: 高度扩展至 {need_h}')
            img.putpalette(PALETTE)
            font = ImageFont.truetype(fpath, size)
            for c, cd in codes:
                draw_glyph(img, cd, c, size, yoff, font)
            img.save(path)
            print(f'已更新 {path}')

    return 0


if __name__ == '__main__':
    sys.exit(main())
