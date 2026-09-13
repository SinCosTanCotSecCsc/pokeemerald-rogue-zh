#!/usr/bin/env python3
"""扫描源码里可翻译的字符串字面量。供 i18n_batch.py / translation_status.py /
translation_check.py / add_glyphs.py 共用，避免各自维护一份正则而出现漏扫。

为什么不用正则
--------------
游戏里的长文本写成多个相邻字面量，由编译器拼接：

    static const u8 sPokeBallDesc[] = _(
        "A device for catching wild\\n"
        "Pokémon. It is thrown like a\\n"
        "ball.");
    .string "Short text.$"

preproc 是**逐字面量**查表的，所以每个字面量都要单独翻译。
只匹配紧跟 `_(` 的第一个字面量的正则会漏掉后面所有续行
（实测漏 2869 条，占道具/招式说明的大部分）。
故此处按括号配平扫描 `_( ... )`，取该括号层内全部字面量。
"""

import pathlib
import re

_ASM_STRING = re.compile(r'^\s*\.string\s+"((?:[^"\\]|\\.)*)"', re.M)


def _scan_paren_block(text, open_idx):
    """open_idx 指向 '('。返回 (该层内的字面量内容列表, ')' 的下标)。

    内部遇到嵌套括号会整体跳过（如 _("a" + PREFIX("b")) 里的内层调用），
    字符串里的括号/引号按字面处理，不参与配平。
    """
    depth = 0
    lits = []
    i = open_idx
    n = len(text)

    while i < n:
        c = text[i]

        if c == '"':
            j = i + 1
            while j < n:
                if text[j] == '\\':
                    j += 2
                    continue
                if text[j] == '"':
                    break
                j += 1
            if depth == 1:
                lits.append(text[i + 1:j])
            i = j + 1
            continue

        # 字符字面量：可能含 '\\'' 之类，整体跳过
        if c == "'":
            j = i + 1
            while j < n:
                if text[j] == '\\':
                    j += 2
                    continue
                if text[j] == "'":
                    break
                j += 1
            i = j + 1
            continue

        if c == '/' and i + 1 < n and text[i + 1] == '/':
            j = text.find('\n', i)
            i = n if j < 0 else j + 1
            continue

        if c == '/' and i + 1 < n and text[i + 1] == '*':
            j = text.find('*/', i + 2)
            i = n if j < 0 else j + 2
            continue

        if c == '(':
            depth += 1
        elif c == ')':
            depth -= 1
            if depth == 0:
                # 初始化列表的每个 #if / #else 分支都可能各带一个 `)`：
                #
                #     static const u8 sDesc[] = _(
                #     #if COND
                #         "A\n" "B\n");
                #     #else
                #         "C\n" "D\n");
                #     #endif
                #
                # 第一个 `)` 并非括号块的终点，后面还有同级字面量。不继续扫的话，
                # #else 分支的文案既进不了批次（永远翻不到），也会被校验器当成
                # 「源码里不存在」而误报为陈旧条目。
                branch = _next_preprocessor_branch(text, i + 1)
                if branch is None:
                    return lits, i
                i = branch
                depth = 1
                continue

        i += 1

    return lits, n


def _next_preprocessor_branch(text, i):
    """i 处起跳过一个分号与空白；若紧接着是 #else / #elif，返回该指令名后的下标。

    只用于识别上面那种「同一初始化列表按分支各写一个 `)`」的写法；
    遇到 #endif、标识符或其它内容一律返回 None，表示括号块确实结束了。
    """
    n = len(text)
    while i < n and text[i] in ' \t\r\n':
        i += 1
    if i < n and text[i] == ';':
        i += 1
        while i < n and text[i] in ' \t\r\n':
            i += 1
    if i < n and text[i] == '#':
        j = i + 1
        while j < n and text[j] in ' \t':
            j += 1
        if text[j:j + 4] in ('else', 'elif'):
            return j
    return None


def iter_literals(text):
    """产出源代码文本里所有可翻译字面量的内容，按出现顺序。"""
    out = []

    for m in re.finditer(r'\b_\(', text):
        # 跳过 __( 这类以 _ 结尾的标识符（如 make_() ）
        if m.start() > 0 and (text[m.start() - 1].isalnum() or text[m.start() - 1] == '_'):
            continue
        lits, _ = _scan_paren_block(text, m.end() - 1)
        out.extend(lits)

    for m in _ASM_STRING.finditer(text):
        out.append(m.group(1))

    return out


def scan_file(path):
    """扫描单个文件，返回其全部可翻译字面量；读取失败时返回空列表。"""
    try:
        text = pathlib.Path(path).read_text(encoding='utf-8')
    except (UnicodeDecodeError, OSError):
        return []
    return iter_literals(text)
