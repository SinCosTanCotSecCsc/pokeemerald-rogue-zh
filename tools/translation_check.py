#!/usr/bin/env python3
"""翻译表校验器。

用法:
    python3 tools/translation_check.py [表文件] [--impact]

不带参数时校验 translations/zh_CN.txt（它通过 @include 引入名称表）。检查：
  1. 字符集   —— 译文中每个非 ASCII 字符都能被 charmap.txt 编码
                 （否则构建期报 unknown character U+XXXX）。
  2. 占位符   —— {PLAYER} {STR_VAR_1} 等占位符与 \\n \\l \\p 转义，
                 在译文与原文中数量一致（顺序可因语序调整而不同）。
  3. 字节预算 —— 名称类字符串有硬性长度上限，译文字节数不得超过。
  4. 陈旧条目 —— 表中「原文」在源码树里已找不到。合并上游更新后用它确认
                 哪些译文失去了对应源文本（译文会静默回退成英文，构建不报错）。

加 --impact 时列出每个条目除界面文本外还会影响哪些文件。
"""

import collections
import pathlib
import re
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent

# 名称类字符串的可用字节数（含 EOS）
BYTE_BUDGETS = [
    ('ITEM_NAME_LENGTH', 17, '道具名'),
    ('MOVE_NAME_LENGTH', 17, '招式名'),        # B_EXPANDED_MOVE_NAMES=TRUE -> 16+1
    ('ABILITY_NAME_LENGTH', 17, '特性名'),      # 16+1
    ('POKEMON_NAME_LENGTH', 11, '宝可梦名'),     # u8 speciesName[10+1]
    ('PLAYER_NAME_LENGTH', 7, '玩家名'),
    ('BOX_NAME_LENGTH', 8, '盒子名'),
    ('POKEMON_HUB_NAME_LENGTH', 15, '枢纽名'),
]

STRING_LITERAL = re.compile(r'(?:_\(\s*"((?:[^"\\]|\\.)*)"|\.string\s+"((?:[^"\\]|\\.)*)")')
BRACE_OR_ESCAPE = re.compile(r'\{[^}]*\}|\\[nlp]')
TABLE_ENTRY = re.compile(r'^"((?:[^"\\]|\\.)*)"\s*=\s*"((?:[^"\\]|\\.)*)"')
INCLUDE = re.compile(r'^@include\s+"([^"]+)"')
FILE_SCOPE = re.compile(r'^@file\s*(?:"([^"]*)")?\s*$')
NAME_CONST = re.compile(r'const u8 \w+\[(\w+)(?:\s*\+\s*1)?\] = _\("')


def load_charmap():
    chars = set()
    for line in (REPO / 'charmap.txt').read_text(encoding='utf-8').splitlines():
        body = line.split('@')[0].strip()
        if not body or '=' not in body:
            continue
        k, v = body.rsplit('=', 1)
        k, v = k.strip(), v.strip().replace(' ', '')
        if k.startswith("'") and k.endswith("'") and len(k) >= 3:
            chars.add(k[1:-1])
    return chars


def load_control_placeholders():
    """返回「运行期控制码」占位符集合，如 {PLAYER} {STR_VAR_1}。

    charmap 里的常量分两类：
      - 展开为控制码（含字节 0xFD，如 PLAYER = FD 01）：游戏在运行期替换成
        玩家名、变量值等，**必须**原样留在译文里，否则字符串会错乱。
      - 展开为可见字形（如 POKEBLOCK = 55 56 57 58 59，即 "POKéBLOCK"）：
        只是字面文本，翻译时可以整个换成中文。
    只有前者需要校验占位符一致性。
    """
    required = set()
    for line in (REPO / 'charmap.txt').read_text(encoding='utf-8').splitlines():
        body = line.split('@')[0].strip()
        if not body or '=' not in body:
            continue
        k, v = body.rsplit('=', 1)
        k, v = k.strip(), v.strip().split()
        if not k or k.startswith("'"):
            continue
        try:
            seq = [int(b, 16) for b in v]
        except ValueError:
            continue
        if 0xFD in seq:
            required.add('{' + k + '}')
    return required


def byte_len(s):
    full = set('：；？！，．、。《》—～“”‘’…')
    return sum(2 if (ord(c) > 0x2E80 or c in full) else 1 for c in s)


def load_table(path, entries=None, stack=None, problems=None):
    """递归加载；条目为 (原文, 译文, 行号, 相对路径, 作用域)。"""
    if entries is None:
        entries, stack, problems = [], [], []
    path = pathlib.Path(path).resolve()
    if path in stack:
        problems.append(f'{path}: 循环 @include')
        return entries, problems
    stack.append(path)

    scope = None
    for num, line in enumerate(path.read_text(encoding='utf-8').splitlines(), 1):
        s = line.strip()
        if not s or s.startswith('#'):
            continue
        m = INCLUDE.match(s)
        if m:
            load_table(path.parent / m.group(1), entries, stack, problems)
            continue
        m = FILE_SCOPE.match(s)
        if m:
            scope = m.group(1) or None
            continue
        if s.startswith('@'):
            continue
        m = TABLE_ENTRY.match(s)
        if not m:
            problems.append(f'{path}:{num}: 无法解析: {s[:60]}')
            continue
        entries.append((m.group(1), m.group(2), num, str(path.relative_to(REPO)), scope))

    stack.pop()
    return entries, problems


def scan_sources():
    hits = collections.defaultdict(set)
    for path in REPO.rglob('*'):
        if path.suffix not in {'.c', '.h', '.inc', '.s', '.pory'}:
            continue
        if '.git' in path.parts or 'build' in path.parts or 'tools' in path.parts:
            continue
        try:
            text = path.read_text(encoding='utf-8')
        except (UnicodeDecodeError, OSError):
            continue
        rel = str(path.relative_to(REPO))
        for m in STRING_LITERAL.finditer(text):
            hits[m.group(1) if m.group(1) is not None else m.group(2)].add(rel)
    return hits


def main():
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    table = pathlib.Path(args[0]) if args else REPO / 'translations/zh_CN.txt'
    show_impact = '--impact' in sys.argv

    if not table.exists():
        print(f'找不到翻译表: {table}')
        return 1

    allowed = load_charmap()
    control_placeholders = load_control_placeholders()
    entries, problems = load_table(table)
    scoped_n = sum(1 for e in entries if e[4])
    print(f'翻译表 {table}: {len(entries)} 条'
          f'（含 @include；其中 {scoped_n} 条为 @file 限定）')

    # 1. 字符集
    for key, value, num, src, scope in entries:
        bad = sorted({c for c in value if ord(c) >= 0x7F and c not in allowed})
        if bad:
            problems.append(f'{src}:{num}: 译文含 charmap 之外的字符 '
                            f'{"".join(bad)} (U+{", U+".join(f"{ord(c):04X}" for c in bad)})')

    # 2. 占位符 / 转义
    #    转义（\n \l \p）与运行期控制码占位符必须与原文一致；
    #    纯字形常量（如 {POKEBLOCK}）翻译时可换成中文，不作要求。
    for key, value, num, src, scope in entries:
        want = [t for t in BRACE_OR_ESCAPE.findall(key)
                if not t.startswith('{') or t in control_placeholders]
        got = [t for t in BRACE_OR_ESCAPE.findall(value)
               if not t.startswith('{') or t in control_placeholders]
        if collections.Counter(want) != collections.Counter(got):
            problems.append(f'{src}:{num}: 占位符不一致\n      原文 {want}\n      译文 {got}')

    # 3. 字节预算（按名称表实际声明所用常量判断）
    sources = scan_sources()
    budgets = dict((c, (lim, lab)) for c, lim, lab in BYTE_BUDGETS)
    for key, value, num, src, scope in entries:
        for f in sources.get(key, ()):
            try:
                text = (REPO / f).read_text(encoding='utf-8')
            except OSError:
                continue
            for m in re.finditer(r'const u8 \w+\[(\w+)(?:\s*\+\s*1)?\] = _\("'
                                 + re.escape(key) + r'"\)', text):
                const = m.group(1)
                if const in budgets:
                    lim, lab = budgets[const]
                    if byte_len(value) + 1 > lim:
                        problems.append(f'{src}:{num}: {lab} 超字节上限 '
                                        f'({byte_len(value)+1} > {lim}): {key[:40]} @ {f}')

    # 4. 陈旧条目
    stale = []
    for key, value, num, src, scope in entries:
        if key not in sources:
            stale.append((src, num, key))
        elif scope and scope not in sources[key]:
            stale.append((src, num, f'{key}（@file {scope} 中已不存在）'))
    if stale:
        print(f'\n陈旧条目 {len(stale)} 条（原文本在源码中已不存在）:')
        for src, num, key in stale[:40]:
            print(f'   {src}:{num}: {key[:70]}')
        if len(stale) > 40:
            print(f'   ...另有 {len(stale) - 40} 条')
        print('\n上游若改写了这些文案，对应译文已静默回退为英文（构建不会报错）。'
              '\n处理方式：按新文案补一条表项，再删掉陈旧那条。')

    # 5. 跨文件影响
    if show_impact:
        outside = {}
        for key, value, num, src, scope in entries:
            others = sorted(f for f in sources.get(key, ()) if f != 'src/strings.c')
            if others:
                outside[key] = others
        print(f'\n除 src/strings.c 外还会被翻译的条目: {len(outside)}')
        for k in sorted(outside, key=len):
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
