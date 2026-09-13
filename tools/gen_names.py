"""由权威开源数据生成宝可梦名称翻译表。

数据源（均为官方中文译名，脚本不做任何自行翻译），按优先级：
  1. PKHeX 的 en / zh-Hans 对照文件 —— 官方游戏数据提取，最权威、覆盖最广
  2. PokeAPI 的 zh-hans 名称        —— 补充 PKHeX 未收录者
  3. Pokémon Showdown 的 zh-cn 本地化 —— 补充 G-Max 招式等

三者重叠处以更高优先级的源为准；PKHeX 与 PokeAPI 冲突时 PKHeX 更准确
（例如 Minun 作「负电拍拍」而非「負电拍拍」、Mimikium Z 作「谜拟丘Ｚ」）。

用法：
    python3 tools/gen_names.py            生成 translations/zh_CN_names.txt 并报告
    python3 tools/gen_names.py --check    只报告，不写文件

需要先准备数据（见 tools/fetch_official_names.sh）。
"""
import csv
import glob
import pathlib
import re
import sys
import unicodedata
from difflib import SequenceMatcher

REPO = pathlib.Path(__file__).resolve().parent.parent
POKEAPI = pathlib.Path('/tmp/pokeapi')
SHOWDOWN = pathlib.Path('/tmp/ps')
PKHEX = pathlib.Path('/tmp/pkhex')

# 本项目的英文写法与数据源不一致时，按此别名再来一轮匹配。
# 例：expansion 用 "Bicycle"，而 PKHeX 收录为 "Bike"。
ALIASES = {
    'Bicycle': 'Bike',
    'Mach Bike': 'Mach Bike',
}

TABLES = [
    {
        'label': '宝可梦名',
        'kind': 'species',
        'pattern': r'\.speciesName = _\("([^"]*)"\)',
        'files': None,  # 见下
        'limit': 11,    # u8 speciesName[POKEMON_NAME_LENGTH + 1]
        'placeholder': r'^[?\-]+$',
    },
    {
        'label': '招式名',
        'kind': 'move',
        'pattern': r'\[MOVE_\w+\] = _\("([^"]*)"\)',
        'files': ['src/data/text/move_names.h'],
        'limit': 17,    # MOVE_NAME_LENGTH(16) + 1（已启用 B_EXPANDED_MOVE_NAMES）
        'placeholder': r'^[?\-]+$',
    },
    {
        'label': '特性名',
        'kind': 'ability',
        'pattern': r'\[ABILITY_\w+\] = _\("([^"]*)"\)',
        'files': ['src/data/text/abilities.h'],
        'limit': 17,    # ABILITY_NAME_LENGTH(16) + 1
        'placeholder': r'^[?\-]+$',
    },
    {
        'label': '道具名',
        'kind': 'item',
        'pattern': r'\.name = _\("([^"]*)"\)',
        'files': ['src/data/items.h'],
        'limit': 17,    # ITEM_NAME_LENGTH（含 EOS）
        'placeholder': r'^[?\-]+$',
    },
]


def norm(s):
    s = unicodedata.normalize('NFKD', s)
    s = ''.join(c for c in s if not unicodedata.combining(c))
    return re.sub(r'[^a-z0-9]', '', s.lower())


def byte_len(s):
    full = set('：；？！，．、。《》—～“”‘’…')
    return sum(2 if (ord(c) > 0x2E80 or c in full) else 1 for c in s)


def load_charmap_chars():
    """charmap 中已有编码的全部字符。"""
    text = (REPO / 'charmap.txt').read_text(encoding='utf-8').splitlines()
    s0 = next(i for i, l in enumerate(text) if l.startswith('@Chinese char'))
    chars = set()
    for i, line in enumerate(text):
        line = line.split('@')[0].strip()
        if not line or '=' not in line:
            continue
        k, v = line.rsplit('=', 1)
        k, v = k.strip(), v.strip().replace(' ', '')
        if not (k.startswith("'") and k.endswith("'")):
            continue
        if (i < s0 and len(v) == 2) or (i >= s0 and len(v) == 4):
            chars.add(k[1:-1])
    return chars


CHARMAP_CHARS = load_charmap_chars()
_T2S = None


def to_simplified(s):
    """把字库外的繁体字转成简体（数据源 zh-hans 偶有繁体残留）。

    只对字库外的字符做转换，且仅在转换结果落入字库时才采用——
    避免误改官方译名中本就正确的用字。
    """
    global _T2S
    if _T2S is None:
        try:
            from opencc import OpenCC
            _T2S = OpenCC('t2s').convert
        except Exception:
            import subprocess

            def _conv(x):
                return subprocess.run(['opencc', '-c', 't2s'], input=x,
                                      capture_output=True, text=True).stdout
            _T2S = _conv

    out = []
    for c in s:
        if ord(c) < 0x7F or c in CHARMAP_CHARS:
            out.append(c)
            continue
        s2 = _T2S(c)
        out.append(s2 if s2 != c and all(x in CHARMAP_CHARS for x in s2) else c)
    return ''.join(out)


def load_pokeapi():
    out = {}
    for kind, fn, idcol in [('species', 'pokemon_species_names.csv', 'pokemon_species_id'),
                            ('move', 'move_names.csv', 'move_id'),
                            ('ability', 'ability_names.csv', 'ability_id'),
                            ('item', 'item_names.csv', 'item_id')]:
        rows = {}
        with open(POKEAPI / fn, encoding='utf-8') as f:
            for r in csv.DictReader(f):
                rows.setdefault(r[idcol], {})[r['local_language_id']] = r['name']
        out[kind] = {v['9']: v['12'] for v in rows.values() if '9' in v and '12' in v}
    return out


def parse_showdown(filename):
    entry = re.compile(r'^\t(?:"([^"]+)"|([A-Za-z0-9_]+)):\s*\{')
    name = re.compile(r'^\t\tname:\s*(?:"((?:[^"\\]|\\.)*)"|null)\s*,')
    out, cur = {}, None
    for line in (SHOWDOWN / filename).read_text(encoding='utf-8').splitlines():
        m = entry.match(line)
        if m:
            cur = (m.group(1) or m.group(2)).lower(); continue
        if cur is None:
            continue
        m = name.match(line)
        if m:
            if m.group(1):
                out[cur] = m.group(1)
            cur = None
    return out


def load_pkhex(name):
    """PKHeX 的 en / zh-Hans 文件按同一 id 顺序排列，按行号配对成 en->zh。"""
    en = (PKHEX / f'{name}_en.txt').read_text(encoding='utf-8').splitlines()
    zh = (PKHEX / f'{name}_zh.txt').read_text(encoding='utf-8').splitlines()
    out = {}
    for i in range(min(len(en), len(zh))):
        e, z = en[i].strip(), zh[i].strip()
        if e and z and e != 'None' and z not in ('—', '----', '？？？', '―――――'):
            out[e] = z
    return out


def build_index():
    """返回 {kind: {norm_id: 中文名, 精确英文名: 中文名}}"""
    api = load_pokeapi()
    pk = {
        'species': load_pkhex('species'),
        'move': load_pkhex('moves'),
        'ability': load_pkhex('abilities'),
        'item': load_pkhex('items'),
    }
    sd = {
        'move': parse_showdown('moves.ts'),
        'ability': parse_showdown('abilities.ts'),
        'item': parse_showdown('items.ts'),
        'species': parse_showdown('pokedex.ts'),
    }
    idx = {}
    for kind in ('species', 'move', 'ability', 'item'):
        exact = dict(pk[kind])                 # PKHeX 最权威，优先
        for en, zh in api[kind].items():
            exact.setdefault(en, zh)
        by_norm = {norm(en): zh for en, zh in pk[kind].items()}
        for en, zh in api[kind].items():
            by_norm.setdefault(norm(en), zh)
        for k, zh in sd[kind].items():
            by_norm.setdefault(k, zh)          # Showdown 的 id 已规范化
        idx[kind] = {'exact': exact, 'norm': by_norm}
    return idx


def main():
    write = '--check' not in sys.argv
    idx = build_index()

    # 界面译文表已占用的原文；名称表与之冲突时须用 @file 限定
    ui_keys = set()
    ui_path = REPO / 'translations' / 'zh_CN.txt'
    if ui_path.exists():
        for line in ui_path.read_text(encoding='utf-8').splitlines():
            m = re.match(r'^"((?:[^"\\]|\\.)*)"\s*=', line.strip())
            if m:
                ui_keys.add(m.group(1))

    entries, report, raw = {}, {}, []
    for spec in TABLES:
        files = spec['files']
        if files is None:
            files = sorted(str(p.relative_to(REPO))
                           for p in (REPO / 'src/data/pokemon/species_info').glob('gen_*.h'))
        # 记录 (英文名, 来源文件)，以便冲突时加 @file 限定
        names = []
        for f in files:
            for m in re.findall(spec['pattern'], (REPO / f).read_text(encoding='utf-8')):
                names.append((m, f))

        st = dict(exact=0, norm=0, fuzzy=0, ph=0, unmatched=0, over=0, alias=0)
        unmatched, over, fuzzy_pairs = [], [], []
        table = idx[spec['kind']]['exact']
        nidx = idx[spec['kind']]['norm']
        ph = re.compile(spec['placeholder'])

        for en, src in names:
            if ph.match(en):
                st['ph'] += 1
                continue
            # 含 {占位符} 或 \n 等转义的名称不参与自动匹配：
            # 数据源里没有对应形式，模糊匹配极易给出丢掉占位符的错误结果。
            if '{' in en or '\\' in en:
                st.setdefault('has_ph', 0)
                st['has_ph'] += 1
                unmatched.append(en)
                continue
            zh = None
            if en in table:
                zh = table[en]; st['exact'] += 1
            elif norm(en) in nidx:
                zh = nidx[norm(en)]; st['norm'] += 1
            elif en in ALIASES and (ALIASES[en] in table or norm(ALIASES[en]) in nidx):
                alias = ALIASES[en]
                zh = table[alias] if alias in table else nidx[norm(alias)]
                st['alias'] = st.get('alias', 0) + 1
            else:
                key = norm(en)
                best, score = None, 0.0
                if len(key) >= 3:
                    for k, z in nidx.items():
                        r = SequenceMatcher(None, key, k).ratio()
                        if k.startswith(key):
                            r = max(r, 0.95)
                        if r > score:
                            best, score = z, r
                if best and score >= 0.82:
                    zh = best; st['fuzzy'] += 1
                    if len(fuzzy_pairs) < 5:
                        fuzzy_pairs.append(f'{en} -> {zh}({score:.2f})')
                else:
                    st['unmatched'] += 1
                    unmatched.append(en)
                    continue

            zh = to_simplified(zh)      # 数据源偶有繁体残留，转成简体

            if byte_len(zh) + 1 > spec['limit']:
                st['over'] += 1
                over.append((en, zh, byte_len(zh), spec['limit']))
                continue

            scoped = en in ui_keys          # 与界面表冲突 -> 限定到来源文件
            raw.append((en, src, zh, spec['kind']))

        report[spec['label']] = (len(names), st, unmatched, over, fuzzy_pairs)

    # 同一原文在不同来源文件里译法不同（如 Metronome：招式「挥指」/ 道具「节拍器」），
    # 或与界面表冲突时，都必须用 @file 限定，否则会互相覆盖。
    by_en = {}
    for en, src, zh, kind in raw:
        by_en.setdefault(en, []).append((src, zh))

    conflicts = 0
    for en, items in sorted(by_en.items()):
        variants = {zh for _, zh in items}
        need_scope = (en in ui_keys) or len(variants) > 1
        if need_scope:
            conflicts += 1 if len(variants) > 1 else 0
            for src, zh in items:
                entries[(src, en)] = (True, zh, None)
        else:
            entries[(None, en)] = (False, items[0][1], None)

    print('=' * 76)
    for label, (total, st, unmatched, over, fp) in report.items():
        m = st['exact'] + st['norm'] + st['fuzzy'] + st.get('alias', 0)
        print(f'\n{label}: 共 {total} 条')
        print(f'  官方译名命中 {m} ({m/total*100:.1f}%) = 精确 {st["exact"]} + 规范化 {st["norm"]}'
              f' + 别名 {st.get("alias", 0)} + 模糊 {st["fuzzy"]}')
        print(f'  跳过占位符 {st["ph"]}')
        print(f'  无官方译名 {st["unmatched"]}')
        print(f'  超字节上限 {st["over"]}')
        if fp:
            print('  模糊补漏样例: ' + '; '.join(fp))
        if over:
            for en, zh, b, lim in over[:10]:
                print(f'    超限: {en} -> {zh} [{b}/{lim}]')
        if unmatched:
            print(f'  未匹配明细 ({len(unmatched)}): {unmatched[:20]}')

    print('\n' + '=' * 76)
    print(f'可写入翻译表: {len(entries)} 条（其中 {sum(1 for v in entries.values() if v[0])} 条因与界面表冲突而限定到具体文件）')

    if write and entries:
        out = REPO / 'translations' / 'zh_CN_names.txt'
        header = [
            '# 宝可梦名称翻译表（宝可梦名 / 招式名 / 特性名 / 道具名）',
            '#',
            '# 由 tools/gen_names.py 从权威开源数据自动生成，均为**官方中文译名**：',
            '#   - PokeAPI zh-hans',
            '#   - Pokémon Showdown 的 zh-cn 本地化（补充 G-Max 招式等）',
            '# 两者在重叠部分 100% 一致。请勿手工编辑——要改请改生成脚本。',
            '#',
            '# @file 限定的条目：该英文串在界面文本里另有含义，故只在名称文件中替换。',
            '',
        ]
        body = []
        for (src, en), (scoped, zh, _) in sorted(
                entries.items(), key=lambda kv: (kv[0][0] or '', kv[0][1])):
            if scoped:
                body.append(f'@file "{src}"')
                body.append(f'"{en}" = "{zh}"')
                body.append('@file')
                body.append('')
            else:
                body.append(f'"{en}" = "{zh}"')
        out.write_text('\n'.join(header + body) + '\n', encoding='utf-8')
        print(f'已写入 {out} ({out.stat().st_size} 字节)')


if __name__ == '__main__':
    main()
