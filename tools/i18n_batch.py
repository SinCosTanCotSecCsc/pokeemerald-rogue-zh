#!/usr/bin/env python3
"""批量汉化流水线：导出未译条目 → 交给翻译 → 回收到翻译表。

翻译以数据文件形式存在，本工具负责在「源码字面量」与「译者可读的清单」之间
来回转换，并把结果汇总成一个可直接被 preproc 使用的表文件。

子命令:
    export [--only 子串] [--first bNNNN]   扫描源码，产出 translations/_work/bNNNN.tsv
    status                                显示各批次完成情况
    import                                回收 b*.out.tsv，校验后写 translations/zh_CN_text.txt

条目以**原文内容**为键，不用序号
--------------------------------
preproc 是按字面量内容查表的，所以一条译文的身份就是它的英文原文。
早期版本用「文件内序号」做键，结果一改扫描逻辑（补上续行字面量）序号全体错位，
已完成的译文全部作废；序号相同的两条来自不同文件时还会互相覆盖。
改用内容为键后，批次顺序、编号、分批方式怎么变都不影响已完成的结果。

批次按「来源文件」划分，同一段对话的连续片段留在同一批，便于保持语境。
"""

import collections
import json
import pathlib
import re
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent
WORK = REPO / 'translations' / '_work'
OUT_TABLE = REPO / 'translations' / 'zh_CN_text.txt'
FIXUPS = REPO / 'translations' / 'fixups.txt'

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import i18n_scan  # noqa: E402

TABLE_ENTRY = re.compile(r'^"((?:[^"\\]|\\.)*)"\s*=\s*"')
INCLUDE = re.compile(r'^@include\s+"([^"]+)"')
FILE_SCOPE = re.compile(r'^@file\s*(?:"([^"]*)")?\s*$')

SCAN_SUFFIXES = {'.c', '.h', '.inc', '.s'}
SKIP_DIRS = {'.git', 'build', 'tools', 'translations'}

# 转义 / 终止符：译文里必须与原文数量一致
TOKEN = re.compile(r'\\[nlp]|\$')

# 调试用文本（正式版不可见），优先级最低
DEBUG_FILE = re.compile(r'(^|/)[^/]*debug[^/]*\.(c|h)$')

MAX_PER_BATCH = 260


def is_meaningful(s):
    """过滤无需翻译的条目：空串、纯符号、纯控制序列。"""
    return bool(re.search(r'[A-Za-z]', s))


def load_table_keys(path, glob, scoped, stack=None):
    path = pathlib.Path(path).resolve()
    stack = stack if stack is not None else []
    if path in stack:
        return
    stack.append(path)
    scope = None
    for line in path.read_text(encoding='utf-8').splitlines():
        s = line.strip()
        if not s or s.startswith('#'):
            continue
        m = INCLUDE.match(s)
        if m:
            load_table_keys(path.parent / m.group(1), glob, scoped, stack)
            continue
        m = FILE_SCOPE.match(s)
        if m:
            scope = m.group(1) or None
            continue
        if s.startswith('@'):
            continue
        m = TABLE_ENTRY.match(s)
        if m:
            (scoped if scope else glob).add(m.group(1))
    stack.pop()


def known_keys():
    glob, scoped = set(), set()
    load_table_keys(REPO / 'translations' / 'zh_CN.txt', glob, scoped)
    return glob, scoped


def scan_all():
    """返回 {相对路径: [原文, ...]}（去重、保序，只含可翻译条目）。"""
    out = {}
    for path in sorted(REPO.rglob('*')):
        if path.suffix not in SCAN_SUFFIXES or any(p in SKIP_DIRS for p in path.parts):
            continue
        rel = str(path.relative_to(REPO))
        seen, items = set(), []
        for key in i18n_scan.scan_file(path):
            if not is_meaningful(key) or key in seen:
                continue
            seen.add(key)
            items.append(key)
        if items:
            out[rel] = items
    return out


def scan_untranslated():
    """{相对路径: [尚未翻译的原文, ...]}。"""
    glob, scoped = known_keys()
    result = {}
    for rel, items in scan_all().items():
        missing = [k for k in items if k not in glob and f'{rel}\n{k}' not in scoped]
        if missing:
            result[rel] = missing
    return result


def sort_key(item):
    """批次先后顺序：玩家最常看到的先翻。"""
    rel, items = item
    if re.match(r'(src/data/rogue|data/scripts/Rogue|data/maps/Rogue)', rel):
        tier = 0
    elif rel in ('src/battle_message.c', 'src/strings.c', 'src/berry.c') or \
            re.match(r'src/data/text/(move_descriptions|item_descriptions|abilities|trainer_class_names)', rel):
        tier = 1
    elif rel == 'src/data/rogue/pokemon_nicknames.h':
        tier = 4
    elif DEBUG_FILE.search(rel):
        tier = 5
    else:
        tier = 3
    return (tier, -len(items), rel)


TASK_HEADER = [
    '# 任务: 把下面每一条英文原文翻译成简体中文。',
    '# 输出格式: 每条一行「原文<TAB>译文」，原文必须与下面完全一致（原样复制），不要增删条目。',
    '# 硬性要求:',
    '#   1. \\n \\l \\p 与 $ 在译文中数量必须与原文完全一致，位置可随语序调整。',
    '#   2. {PLAYER} {STR_VAR_1} {COLOR RED} 等 {…} 控制码原样保留，不要翻译、不要改大小写。',
    '#   3. 宝可梦/招式/道具/特性/人名必须用官方中文译名（表见下方参考）。',
    '#   4. 分隔符必须是真正的制表符 TAB（不是空格）。',
    '#   5. 不要写注释、标题或 Markdown 代码块，只输出「原文<TAB>译文」。',
    '#   6. 只用 charmap.txt 里已有的字符：全角标点限 ，。！？：；…，括号用半角 ( )。',
    '# 翻译规范与术语表: 见仓库 translations/GLOSSARY.md（务必先读）。',
    '# 注意: 相邻条目常是同一句话被换行拆开的片段，要连起来读、保证拼接后通顺；',
    '#       短片段可能在源码里被多处复用，译文必须能接上所有出现位置（详见 GLOSSARY.md）。',
]


def ref_lines(sources):
    """挑出这批原文里出现的官方名词，作为译名参考。"""
    blob = '\n'.join(sources)
    names = []
    for line in (REPO / 'translations' / 'zh_CN_names.txt').read_text(encoding='utf-8').splitlines():
        m = re.match(r'^"((?:[^"\\]|\\.)*)"\s*=\s*"((?:[^"\\]|\\.)*)"', line.strip())
        if not m:
            continue
        en, zh = m.group(1), m.group(2)
        if en == zh or '{' in en or '\\' in en:
            continue
        if re.search(r'(?<![A-Za-z])' + re.escape(en) + r'(?![A-Za-z])', blob):
            names.append(f'{en}={zh}')
    if not names:
        return []
    out = ['# 参考译名（官方，出现于本批时必须使用）:']
    for i in range(0, len(names), 6):
        out.append('#   ' + '  '.join(names[i:i + 6]))
    return out


def cmd_export(argv):
    only = argv[argv.index('--only') + 1] if '--only' in argv else None
    first = argv[argv.index('--first') + 1] if '--first' in argv else 'b0000'

    untranslated = scan_untranslated()
    rels = [(r, v) for r, v in untranslated.items() if only is None or only in r]
    rels.sort(key=sort_key)

    WORK.mkdir(parents=True, exist_ok=True)
    start_n = int(first[1:])

    manifest, n = {}, start_n
    for rel, items in rels:
        for off in range(0, len(items), MAX_PER_BATCH):
            chunk = items[off:off + MAX_PER_BATCH]
            bid = f'b{n:04d}'
            n += 1
            manifest[bid] = {'file': rel, 'count': len(chunk)}
            lines = [f'# 批次 {bid}', f'# 来源: {rel}'] + TASK_HEADER + ref_lines(chunk) + chunk
            (WORK / f'{bid}.tsv').write_text('\n'.join(lines) + '\n', encoding='utf-8')

    (WORK / 'manifest.json').write_text(
        json.dumps(manifest, ensure_ascii=False, indent=1), encoding='utf-8')

    total = sum(v['count'] for v in manifest.values())
    print(f'导出 {len(manifest)} 批（{first} 起），共 {total} 条 -> {WORK}')
    return 0


def cmd_status(argv):
    manifest = json.loads((WORK / 'manifest.json').read_text(encoding='utf-8'))
    done = {f.name[:-len('.out.tsv')] for f in WORK.glob('b*.out.tsv')}
    groups = collections.defaultdict(lambda: [0, 0, 0])
    for bid, info in manifest.items():
        g = groups[info['file']]
        g[0] += 1
        g[1] += info['count']
        if bid in done:
            g[2] += info['count']
    n_bid = sum(1 for b in manifest if b in done)
    print(f'批次 {len(manifest)}，已完成 {n_bid}')
    print(f'{"文件":62s} {"批":>4s} {"条目":>6s} {"已译":>6s}')
    for rel, (nb, nt, nd) in sorted(groups.items()):
        flag = '' if nd == nt else '  <- 未完成'
        print(f'{rel:62s} {nb:4d} {nt:6d} {nd:6d}{flag}')
    return 0


def normalize_translation(en, zh):
    """修正常见的机械性偏差。返回修正后的译文；无法安全修正时返回 None。

    `$` 是字符串结束符、位置固定（原文以 $ 结尾则译文也必然以 $ 结尾），
    因此首尾的 $ 差异可以安全地机械补正，不必丢弃整条译文。
    其余转义（\\n \\l \\p）的位置受语序影响，不作自动调整，交给校验丢弃。
    """
    zh = zh.replace('＄', '$').replace('￥', '$').replace('\\$', '$')

    if en.endswith('$'):
        zh = zh.rstrip()
        if not zh.endswith('$'):
            zh += '$'
    else:
        zh = zh.rstrip('$').rstrip()

    # 去掉终止符后为空，说明这条根本没翻译
    if not zh.rstrip('$').strip():
        return None

    return zh


def load_fixups():
    """手工修正表：EN<TAB>ZH，覆盖批次产出。

    用途：
      * 修正批次译文里的错误（控制码增减、超长、译名不当）
      * 跨文件共用的片段只能有一个译法，冲突时在此裁决
    必须能在每次 import 后自动生效 —— 直接改 zh_CN_text.txt 会在下次回收时丢失。
    """
    if not FIXUPS.exists():
        return {}
    out = {}
    for line in FIXUPS.read_text(encoding='utf-8').splitlines():
        if not line.strip() or line.lstrip().startswith('#') or '\t' not in line:
            continue
        en, _, zh = line.partition('\t')
        out[en] = zh.rstrip('\r')
    return out


def load_file_sets():
    """{相对路径: set(该文件的全部原文)}，用于校验回收条目的归属。"""
    return {rel: set(items) for rel, items in scan_all().items()}


def cmd_import(argv):
    manifest = json.loads((WORK / 'manifest.json').read_text(encoding='utf-8'))
    file_sets = load_file_sets()

    entries, rejects = {}, []
    stray = collections.Counter()

    for f in sorted(WORK.glob('b*.out.tsv')):
        bid = f.name[:-len('.out.tsv')]
        info = manifest.get(bid)
        if info is None:
            rejects.append(f'{f.name}: 不在 manifest 中')
            continue
        rel = info['file']
        known = file_sets.get(rel, set())

        for line in f.read_text(encoding='utf-8').splitlines():
            line = line.rstrip('\n')
            if not line.strip() or line.lstrip().startswith('#'):
                continue
            if '\t' not in line:
                continue
            # 原文是查表键，必须与源码逐字节一致 —— 首尾空格也是内容
            # （如 "sharply "、" and"），不能 strip。
            en, _, zh = line.partition('\t')
            zh = zh.rstrip('\r')
            if not en.endswith(' '):
                zh = zh.rstrip(' ')
            if en not in known:
                stray[bid] += 1
                continue
            zh = normalize_translation(en, zh)
            if not zh:
                continue
            if collections.Counter(TOKEN.findall(en)) != collections.Counter(TOKEN.findall(zh)):
                rejects.append(f'{bid} 原文 {en!r}\n    译文 {zh!r}')
                continue
            if en == zh:
                continue
            entries[(rel, en)] = zh

    # 手工修正优先于批次产出
    for en, zh in load_fixups().items():
        hit = [(k, v) for k, v in entries.items() if k[1] == en]
        if not hit:
            continue
        for k, _ in hit:
            entries[k] = zh

    # 同一原文在不同文件里译法不同 -> 用 @file 限定；否则写成全局条目
    by_en = collections.defaultdict(set)
    for (rel, en), zh in entries.items():
        by_en[en].add(zh)

    globals_, scoped_ = {}, {}
    for (rel, en), zh in sorted(entries.items()):
        if len(by_en[en]) > 1:
            scoped_[(rel, en)] = zh
        else:
            globals_[en] = zh

    lines = [
        '# 游戏内文本译文（由 tools/i18n_batch.py 生成，请勿手工编辑）',
        '#',
        '# 覆盖对话、战斗消息、说明文字等；名称类官方译名见 zh_CN_names.txt。',
        '# 同一原文在不同文件里含义不同时，用 @file 限定到具体文件。',
        '',
    ]
    for en, zh in sorted(globals_.items()):
        lines.append(f'"{en}" = "{zh}"')

    if scoped_:
        lines += ['', '# ---- 以下条目限定到具体来源文件 ----',
                  '# 同一英文在不同文件里含义不同时使用。']
        by_file = collections.defaultdict(list)
        for (rel, en), zh in sorted(scoped_.items()):
            by_file[rel].append((en, zh))
        for i, (rel, items) in enumerate(sorted(by_file.items())):
            if i:
                lines.append('')
            lines.append(f'@file "{rel}"')
            for en, zh in items:
                lines.append(f'"{en}" = "{zh}"')
            lines.append('@file')

    OUT_TABLE.write_text('\n'.join(lines) + '\n', encoding='utf-8')

    print(f'写入 {OUT_TABLE.relative_to(REPO)}: 全局 {len(globals_)} 条，'
          f'@file 限定 {len(scoped_)} 条')
    if stray:
        print('\n警告：以下批次含不属于本批来源的原文（很可能写错了文件）:')
        for bid, n in sorted(stray.items()):
            print(f'  {bid}: {n} 条')
    if rejects:
        print(f'丢弃 {len(rejects)} 条（转义数量与原文不符）:')
        for r in rejects[:15]:
            print('  ' + r)
        if len(rejects) > 15:
            print(f'  ...另有 {len(rejects)-15} 条')
    return 0


def main():
    if len(sys.argv) < 2 or sys.argv[1] not in {'export', 'import', 'status'}:
        print(__doc__)
        return 1
    return {'export': cmd_export, 'import': cmd_import, 'status': cmd_status}[sys.argv[1]](sys.argv[2:])


if __name__ == '__main__':
    sys.exit(main())
