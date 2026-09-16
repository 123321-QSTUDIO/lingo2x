"""LINGO 词法分析：源码 → token 流。

token = (kind, value, pos)，kind ∈ AT / NUM / ID / STR / OP / EOF。
注释：! 到下一个分号（与 LINGO 一致）。
比较/逻辑运算符 #LE# 等归一为 OP，值保留大写原形（如 '#LE#'）。
"""
import re


class LexError(Exception):
    pass


_RE_AT = re.compile(r'@[A-Za-z_][A-Za-z0-9_]*')
_RE_NUM = re.compile(r'\d+(?:\.\d+)?(?:[eE][+-]?\d+)?|\.\d+(?:[eE][+-]?\d+)?')
_RE_ID = re.compile(r'[A-Za-z_][A-Za-z0-9_]*')
_RE_HASH = re.compile(r'#[A-Za-z]+#')

_OPS2 = ('<=', '>=', '..')
_OPS1 = '=<>+-*/(),;:|[]&'


def tokenize(text):
    toks = []
    i, n = 0, len(text)
    while i < n:
        c = text[i]
        if c.isspace():
            i += 1
            continue
        if c == '!':                        # 注释：! ... ;
            # 兼容教学文件的写法：注释结束于本行的分号；若本行没有分号则到行尾
            j = text.find(';', i)
            nl = text.find('\n', i)
            if j >= 0 and (nl < 0 or j < nl):
                i = j + 1
            else:
                i = n if nl < 0 else nl + 1
            continue
        if c in '\'"':
            j = text.find(c, i + 1)
            if j < 0:
                raise LexError(f"字符串缺少结束引号（位置 {i}）")
            toks.append(('STR', text[i + 1:j], i))
            i = j + 1
            continue
        m = _RE_HASH.match(text, i)
        if m:
            toks.append(('OP', m.group(0).upper(), i))
            i = m.end()
            continue
        for kind, rx in (('AT', _RE_AT), ('NUM', _RE_NUM), ('ID', _RE_ID)):
            m = rx.match(text, i)
            if m:
                toks.append((kind, m.group(0), i))
                i = m.end()
                break
        else:
            two = text[i:i + 2]
            if two in _OPS2:
                toks.append(('OP', two, i))
                i += 2
            elif c in _OPS1:
                toks.append(('OP', c, i))
                i += 1
            else:
                raise LexError(f"无法识别的字符 {c!r}（位置 {i}）")
    toks.append(('EOF', '', n))
    return toks
