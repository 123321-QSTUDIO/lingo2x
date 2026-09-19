"""LINGO 词法分析：源码 → token 流。

token = (kind, value, pos)，kind ∈ AT / NUM / ID / STR / OP / EOF。
注释：`!` 行内有分号则到分号；否则看下一条非空行——像散文则按真 LINGO
多行注释延续到分号，像代码则到行尾（兼容教学文件的单行写法）。
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
_OPS1 = '=<>+-*/(),;:|[]&^'

# 判断一行是否"像代码"（用于多行注释边界的启发式）：
# 关键字/@函数/约束标签开头，或"标识符紧跟 = ( / : ]"，或数字开头
_RE_KW_LINE = re.compile(
    r'^\s*(?:@|\[|(?:MODEL|SETS|ENDSETS|DATA|ENDDATA|CALC|ENDCALC'
    r'|PROCEDURE|ENDPROCEDURE|END|MAX|MIN)\b|[^\S\n]*\d)', re.I)
_RE_STMT_LINE = re.compile(r'^\s*[A-Za-z_][A-Za-z0-9_]*[=(/:\]]')


def _looks_like_code(line):
    return bool(_RE_KW_LINE.search(line) or _RE_STMT_LINE.search(line))


def tokenize(text):
    toks = []
    i, n = 0, len(text)
    while i < n:
        c = text[i]
        if c.isspace():
            i += 1
            continue
        if c == '!':                        # 注释：! ... ;
            j = text.find(';', i)
            nl = text.find('\n', i)
            if j >= 0 and (nl < 0 or j < nl):
                i = j + 1                    # 本行有分号 → 注释到分号
                continue
            # 本行无分号：看下一条非空行。
            # 像散文 → 真 LINGO 多行注释，延续到分号；
            # 像代码 → 兼容教学文件的单行写法，注释到行尾
            k = nl + 1 if nl >= 0 else n
            probe = k
            line = ''
            while probe < n:
                eol = text.find('\n', probe)
                line = text[probe:eol if eol >= 0 else n]
                if line.strip():
                    break
                probe = eol + 1 if eol >= 0 else n
            if probe >= n or not _looks_like_code(line):
                i = j + 1 if j >= 0 else n   # 多行注释 → 到分号
            else:
                i = k                        # 单行注释 → 到行尾
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
