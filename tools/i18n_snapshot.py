#!/usr/bin/env python3
"""翻译表与批次文件的完整性快照，防止误操作造成批量数据丢失。

事故背景
--------
`translations/_work/b*.out.tsv` 是手工（agent）产出的中间结果，不在 git 里，
一旦被脚本重复执行就可能被清空。曾发生：把「编号为键」转成「内容为键」的转换
脚本被跑了两遍，第二遍按编号查内容时全部落空，120 个文件被写成空文件 —— 数小时
的翻译工作全部丢失。

用法
----
    python3 tools/i18n_snapshot.py save    # 存快照（每次回收前/大规模操作前跑）
    python3 tools/i18n_snapshot.py check   # 对比当前与最近快照，报告丢失
    python3 tools/i18n_snapshot.py list    # 列出快照

快照写在 translations/_work/.snapshots/，只记录每个文件的条目数与内容校验和，
体积很小；条目数减少或校验和变化即视为异常。
"""

import hashlib
import json
import pathlib
import sys
import time

REPO = pathlib.Path(__file__).resolve().parent.parent
WORK = REPO / 'translations' / '_work'
SNAP_DIR = WORK / '.snapshots'
TABLES = ['zh_CN.txt', 'zh_CN_names.txt', 'zh_CN_manual.txt', 'zh_CN_text.txt']


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()[:16]


def snapshot():
    out = {'when': time.strftime('%Y-%m-%d %H:%M:%S'), 'files': {}}
    for p in sorted(WORK.glob('b*.out.tsv')):
        data = p.read_bytes()
        out['files'][p.name] = [data.count(b'\n'), digest(data)]
    for name in TABLES:
        p = REPO / 'translations' / name
        if p.exists():
            out['files']['tables/' + name] = [p.read_bytes().count(b'\n'), digest(p.read_bytes())]
    return out


def cmd_save(argv):
    SNAP_DIR.mkdir(parents=True, exist_ok=True)
    snap = snapshot()
    path = SNAP_DIR / f'{int(time.time())}.json'
    path.write_text(json.dumps(snap, ensure_ascii=False), encoding='utf-8')
    total = sum(v[0] for k, v in snap['files'].items() if k.startswith('b'))
    print(f'快照 {path.name}: {len([k for k in snap["files"] if k.startswith("b")])} 个批次文件，'
          f'共 {total} 行')
    return 0


def latest():
    snaps = sorted(SNAP_DIR.glob('*.json'))
    if not snaps:
        return None, None
    p = snaps[-1]
    return p, json.loads(p.read_text(encoding='utf-8'))


def cmd_check(argv):
    path, snap = latest()
    if snap is None:
        print('没有可用快照')
        return 1
    cur = snapshot()
    lost = []
    for name, (lines, dig) in snap['files'].items():
        now = cur['files'].get(name)
        if now is None:
            lost.append((name, lines, '文件消失'))
        elif now[0] < lines:
            lost.append((name, lines, f'行数 {lines} -> {now[0]}'))
        elif name.startswith('b') and now[1] != dig:
            lost.append((name, lines, '内容变化'))
    print(f'对比快照 {path.name}（{snap["when"]}）')
    if not lost:
        print('无异常。')
        return 0
    print(f'发现 {len(lost)} 处异常：')
    for name, lines, why in lost[:40]:
        print(f'  {name}: {why}')
    if len(lost) > 40:
        print(f'  ...另有 {len(lost)-40} 处')
    return 1


def cmd_list(argv):
    for p in sorted(SNAP_DIR.glob('*.json')):
        d = json.loads(p.read_text(encoding='utf-8'))
        n = len([k for k in d['files'] if k.startswith('b')])
        total = sum(v[0] for k, v in d['files'].items() if k.startswith('b'))
        print(f'{p.name}  {d["when"]}  {n} 文件 / {total} 行')
    return 0


def main():
    if len(sys.argv) < 2 or sys.argv[1] not in {'save', 'check', 'list'}:
        print(__doc__)
        return 1
    return {'save': cmd_save, 'check': cmd_check, 'list': cmd_list}[sys.argv[1]](sys.argv[2:])


if __name__ == '__main__':
    sys.exit(main())
