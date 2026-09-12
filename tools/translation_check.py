#!/usr/bin/env python3
"""翻译表校验器。

用法:
    python3 tools/translation_check.py [翻译表路径] [--impact]

不带参数时校验 translations/zh_CN.txt，检查：
  1. 字符集   —— 译文中每个非 ASCII 字符都能被 charmap.txt 编码（否则构建期报
                 unknown character U+XXXX）。
  2. 占位符   —— {PLAYER} {STR_VAR_1} 等花括号占位符与 \\n \\l \\p 转义，
                 在译文与原文中数量一致（顺序可因语序调整而不同）。
  3. 字节预算 —— 有硬性长度上限的名称类字符串（道具名/招式名/宝可梦名等）
                 译文字节数不得超过上限。
  4. 陈旧条目 —— 表中「原文」在源码树里已找不到。合并上游更新后用它确认
                 哪些译文失去了对应源文本。

加 --impact 时另外列出每个条目除 src/strings.c 之外还会影响哪些文件
——因为查表是按原文精确匹配、全局生效，短串可能误伤其他语境。
"""

import collections
import pathlib
import re
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent

# 有硬性字节上限的名称类别：常量前缀 -> (上限, 说明)
BYTE_BUDGETS = [
    ('ITEM_NAME_LENGTH', 16, '道具名'),
    ('MOVE_NAME_LENGTH', 12, '招式名'),
    ('POKEMON_NAME_LENGTH', 10, '宝可梦/昵称'),
    ('PLAYER_NAME_LENGTH', 7, '玩家名'),
    ('BOX_NAME_LENGTH', 8, '盒子名'),
    ('BERRY_NAME_LENGTH', 6, '树果名'),
    ('ABILITY_NAME_LENGTH', 12, '特性名'),
    ('POKEMON_HUB_NAME_LENGTH', 15, '枢纽名'),
]

STRING_LITERAL = re.compile(r'(?:_\(\s*"((?:[^"\\]|\\.)*)"|\.string\s+"((?:[^"\\]|\\.)*)")')
BRACE_OR_ESCAPE = re.compile(r'\{[^}]*\}|\\[nlp]')
TABLE_ENTRY = re.compile(r'^"((?:[^"\\]|\\.)*)"\s*=\s*"((?:[^"\\]|\\.)*)"')


def load_charmap():
    """返回 (单字节可编码字符集, 中文区可编码字符集)。"""
    text = (REPO / 'charmap.txt').read_text(encoding='utf-8').splitlines()
    chinese_start = next(i for i, l in enumerate(text) if l.startswith('@Chinese char'))

    single, chinese = set(), set()
    for i, line in enumerate(text):
        line = line.split('@')[0].strip()
        if not line or '=' not in line:
            continue
        key, value = line.rsplit('=', 1)
        key, value = key.strip(), value.strip().replace(' ', '')
        if not (key.startswith("'") and key.endswith("'")):
            continue
        if i < chinese_start and len(value) == 2:
            single.add(key[1:-1])
        elif i >= chinese_start and len(value) == 4:
            chinese.add(key[1:-1])
    return single, chinese


def byte_len(s):
    """按 charmap 计算字面量编码后的字节数（中文区字符 2 字节）。"""
    return sum(2 if (ord(c) > 0x2E80 or c in '：；？！，．、。《》—～“”‘’…') else 1 for c in s)


def load_table(path):
    entries, problems = [], []
    seen = {}
    for num, line in enumerate(path.read_text(encoding='utf-8').splitlines(), 1):
        stripped = line.split('@')[0].strip()
        if not stripped or line.lstrip().startswith('#'):
            continue
        m = TABLE_ENTRY.match(line.strip())
        if not m:
            problems.append(f'{path}:{num}: 无法解析: {line.strip()[:60]}')
            continue
        key, value = m.group(1), m.group(2)
        if key in seen:
            problems.append(f'{path}:{num}: 原文重复（首次见于第 {seen[key]} 行）: {key[:50]}')
        seen[key] = num
        entries.append((num, key, value))
    return entries, problems


def scan_sources():
    """收集源码树中所有字符串字面量 -> 出现位置。"""
    hits = collections.defaultdict(set)
    suffixes = {'.c', '.h', '.inc', '.s', '.pory'}
    for path in REPO.rglob('*'):
        if path.suffix not in suffixes:
            continue
        parts = path.parts
        if '.git' in parts or 'build' in parts or 'tools' in parts:
            continue
        try:
            text = path.read_text(encoding='utf-8')
        except (UnicodeDecodeError, OSError):
            continue
        rel = str(path.relative_to(REPO))
        for m in STRING_LITERAL.finditer(text):
            s = m.group(1) if m.group(1) is not None else m.group(2)
            hits[s].add(rel)
    return hits


def main():
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    show_impact = '--impact' in sys.argv
    table = pathlib.Path(args[0]) if args else REPO / 'translations/zh_CN.txt'

    if not table.exists():
        print(f'找不到翻译表: {table}')
        return 1

    single, chinese = load_charmap()
    allowed = single | chinese
    entries, problems = load_table(table)
    print(f'翻译表 {table}: {len(entries)} 条')

    # 1. 字符集
    for num, key, value in entries:
        bad = sorted({c for c in value if ord(c) >= 0x7F and c not in allowed})
        if bad:
            problems.append(f'{table}:{num}: 译文含 charmap 之外的字符 {"".join(bad)} '
                            f'(U+{", U+".join(f"{ord(c):04X}" for c in bad)})')

    # 2. 占位符 / 转义
    for num, key, value in entries:
        want, got = BRACE_OR_ESCAPE.findall(key), BRACE_OR_ESCAPE.findall(value)
        if collections.Counter(want) != collections.Counter(got):
            problems.append(f'{table}:{num}: 占位符不一致\n      原文 {want}\n      译文 {got}')

    # 3. 字节预算
    sources = scan_sources()
    for num, key, value in entries:
        for path in sources.get(key, ()):
            text = (REPO / path).read_text(encoding='utf-8')
            for const, limit, label in BYTE_BUDGETS:
                for m in re.finditer(rf'const u8 \w+\[{const}\] = _\("{re.escape(key)}"\)', text):
                    if byte_len(value) > limit:
                        problems.append(f'{table}:{num}: {label} 超字节上限 '
                                        f'({byte_len(value)} > {limit}): {key[:40]} @ {path}')

    # 4. 陈旧条目
    stale = [(n, k) for n, k, _ in entries if k not in sources]
    if stale:
        print(f'\n陈旧条目 {len(stale)} 条（原文本在源码中已不存在）:')
        for n, k in stale[:40]:
            print(f'   {table}:{n}: {k[:70]}')
        if len(stale) > 40:
            print(f'   ...另有 {len(stale) - 40} 条')
        print('\n上游若改写了这些文案，对应译文已静默回退为英文（构建不会报错）。')
        print('处理方式：按新文案补一条表项，再删掉陈旧那条。')

    # 5. 跨文件影响
    if show_impact:
        outside = {k: sorted(f for f in sources.get(k, ()) if f != 'src/strings.c')
                   for _, k, _ in entries}
        outside = {k: v for k, v in outside.items() if v}
        print(f'\n除 src/strings.c 外还会被翻译的条目: {len(outside)}')
        for k in sorted(outside, key=lambda s: len(s)):
            print(f'   {k!r:44s} -> {outside[k][:4]}')

    print()
    if stale:
        problems.append(f'{len(stale)} 条陈旧条目：上游已改写或删除对应文案，'
                        f'这些译文不再生效（详见上方列表）')

    if problems:
        print(f'发现 {len(problems)} 个问题:')
        for p in problems[:60]:
            print(f'  {p}')
        if len(problems) > 60:
            print(f'  ...另有 {len(problems) - 60} 个')
        return 1

    print('校验通过。')
    return 0


if __name__ == '__main__':
    sys.exit(main())
