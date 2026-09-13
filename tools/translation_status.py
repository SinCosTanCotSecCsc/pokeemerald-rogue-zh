#!/usr/bin/env python3
"""统计汉化覆盖率：源码里还有多少可翻译字符串没有对应译文。

扫描 src/ 等目录下的 _("...") 与 .string "..." 字面量，与 translations/ 下的
表项（含 @include、@file 限定）比对，按文件给出未翻译条目数与样例。

用法:
    python3 tools/translation_status.py             # 汇总 + 按目录分组
    python3 tools/translation_status.py --top 40    # 列出未翻译最多的 40 个文件
    python3 tools/translation_status.py --file src/strings.c   # 单个文件的明细
"""

import collections
import pathlib
import re
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import i18n_scan  # noqa: E402
TABLE_ENTRY = re.compile(r'^"((?:[^"\\]|\\.)*)"\s*=\s*"')
INCLUDE = re.compile(r'^@include\s+"([^"]+)"')
FILE_SCOPE = re.compile(r'^@file\s*(?:"([^"]*)")?\s*$')

SCAN_SUFFIXES = {'.c', '.h', '.inc', '.s'}
SKIP_DIRS = {'.git', 'build', 'tools', 'translations'}

# 纯 ASCII 空串、单字符、纯转义等不必翻译
TRIVIAL = re.compile(r'^(?:|\\[nlp]|[\x20-\x7E]{0,1})$')


def load_table(path, glob, scoped, stack=None):
    path = pathlib.Path(path).resolve()
    if stack is None:
        stack = []
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
            load_table(path.parent / m.group(1), glob, scoped, stack)
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


def is_translated(key, rel, glob, scoped):
    return key in glob or f'{rel}\n{key}' in scoped


def main():
    args = sys.argv[1:]
    top = 40
    if '--top' in args:
        top = int(args[args.index('--top') + 1])
    only = None
    if '--file' in args:
        only = args[args.index('--file') + 1]

    glob, scoped = set(), set()
    load_table(REPO / 'translations' / 'zh_CN.txt', glob, scoped)

    # 每个文件的未翻译集合；同一字符串在一个文件里出现多次只算一条
    per_file = collections.defaultdict(set)
    for path in REPO.rglob('*'):
        if path.suffix not in SCAN_SUFFIXES:
            continue
        if any(p in SKIP_DIRS for p in path.parts):
            continue
        rel = str(path.relative_to(REPO))
        try:
            text = path.read_text(encoding='utf-8')
        except (UnicodeDecodeError, OSError):
            continue
        for key in i18n_scan.scan_file(path):
            if TRIVIAL.match(key):
                continue
            if not is_translated(key, rel, glob, scoped):
                per_file[rel].add(key)

    total_missing = sum(len(v) for v in per_file.values())
    files_with_missing = len(per_file)
    print(f'已翻译表项: 全局 {len(glob)} 条 + @file 限定 {len(scoped)} 条')
    print(f'未翻译字符串: {total_missing} 处（分布在 {files_with_missing} 个文件）')

    if only:
        keys = per_file.get(only, set())
        print(f'\n{only}: {len(keys)} 条未翻译')
        for k in sorted(keys):
            print('   ', repr(k))
        return 0

    # 按目录分组
    by_dir = collections.Counter()
    for rel, keys in per_file.items():
        by_dir[str(pathlib.Path(rel).parent)] += len(keys)
    print('\n按目录（未翻译条数）:')
    for d, n in by_dir.most_common(25):
        print(f'  {n:6d}  {d}')

    print(f'\n未翻译最多的 {top} 个文件:')
    for rel, keys in sorted(per_file.items(), key=lambda kv: -len(kv[1]))[:top]:
        print(f'  {len(keys):6d}  {rel}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
