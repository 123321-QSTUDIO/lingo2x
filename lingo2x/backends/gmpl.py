"""GMPL (GNU MathProg) 后端：保持符号形式输出 .mod，用 glpsol 求解。"""
from ..model import (Num, Ref, Bin, Neg, Sum, IVar, QCmp, QAnd, QOr, QNot,
                     analyze, ModelError)

_CMP = {'<=': '<=', '>=': '>=', '=': '=', '!=': '<>', '<': '<', '>': '>'}


def _fmt(v):
    return f"{v:g}"


def _dom_str(domain):
    return ', '.join(f"{i} in {s}" for i, s in domain)


class _Emitter:
    def __init__(self, model):
        self.m = model
        self.sy = analyze(model)

    @staticmethod
    def _idx(dom):
        return '{' + ', '.join(dom) + '}' if dom else ''

    # 下标表达式
    def idx(self, e):
        if isinstance(e, IVar):
            return e.name
        if isinstance(e, Num):
            return e.text or _fmt(e.value)
        if isinstance(e, Neg):
            return f"(- {self.idx(e.x)})"
        if isinstance(e, Bin):
            return f"({self.idx(e.l)} {e.op} {self.idx(e.r)})"
        raise TypeError(type(e).__name__)

    # 条件过滤式
    def qual(self, q):
        if isinstance(q, QCmp):
            return f"({self.idx(q.l)} {_CMP[q.op]} {self.idx(q.r)})"
        if isinstance(q, QAnd):
            return f"({self.qual(q.a)} and {self.qual(q.b)})"
        if isinstance(q, QOr):
            return f"({self.qual(q.a)} or {self.qual(q.b)})"
        if isinstance(q, QNot):
            return f"(not {self.qual(q.a)})"
        raise TypeError(type(q).__name__)

    def _iter(self, domain, qual):
        s = _dom_str(domain)
        if qual is not None:
            s += f": {self.qual(qual)}"
        return s

    def expr(self, e):
        if isinstance(e, Num):
            return e.text or _fmt(e.value)
        if isinstance(e, Ref):
            if not e.indices:
                return e.name
            return f"{e.name}[{','.join(self.idx(x) for x in e.indices)}]"
        if isinstance(e, Neg):
            return f"(- {self.expr(e.x)})"
        if isinstance(e, Bin):
            return f"({self.expr(e.l)} {e.op} {self.expr(e.r)})"
        if isinstance(e, Sum):
            return f"sum{{{self._iter(e.domain, e.qual)}}} ({self.expr(e.body)})"
        raise TypeError(type(e).__name__)

    def emit(self):
        m, sy = self.m, self.sy
        L = [f"/* 由 lingo2x 从 {m.source or 'stdin'} 生成 */", ""]
        for name, sd in m.sets.items():
            if not sd.parents:
                L.append(f"set {name};")
        for name, (dom, _) in sy.params.items():
            L.append(f"param {name}{self._idx(dom)};")
        for name, dom in sy.vars.items():
            kd = m.varkind.get(name)
            if kd == 'bin':
                L.append(f"var {name}{self._idx(dom)}, binary;")
            elif kd == 'gin':
                L.append(f"var {name}{self._idx(dom)}, integer, >= 0;")
            elif kd == 'free':
                L.append(f"var {name}{self._idx(dom)};")
            else:
                L.append(f"var {name}{self._idx(dom)}, >= 0;")
        L.append("")
        kw = 'maximize' if m.sense == 'max' else 'minimize'
        L.append(f"{kw} obj: {self.expr(m.objective)};")
        L.append("")
        for i, c in enumerate(m.constraints, 1):
            nm = c.name or f'c{i}'
            dom = f"{{{self._iter(c.domain, c.qual)}}}" if c.domain else ''
            L.append(f"s.t. {nm}{dom}: {self.expr(c.lhs)} {c.op} {self.expr(c.rhs)};")
        L += ["", "data;"]
        for name, sd in m.sets.items():
            if not sd.parents:
                L.append(f"set {name} := {' '.join(sd.members)};")
        for name, (dom, vals) in sy.params.items():
            if not dom:
                L.append(f"param {name} := {_fmt(vals[0])};")
            elif len(dom) == 1:
                pairs = ' '.join(f"{mb} {_fmt(v)}" for mb, v in zip(m.sets[dom[0]].members, vals))
                L.append(f"param {name} := {pairs};")
            elif len(dom) == 2:
                rows = m.sets[dom[0]].members
                cols = m.sets[dom[1]].members
                L.append(f"param {name} : {' '.join(cols)} :=")
                for ri, r in enumerate(rows):
                    vs = ' '.join(_fmt(v) for v in vals[ri * len(cols):(ri + 1) * len(cols)])
                    tail = ' ;' if ri == len(rows) - 1 else ''
                    L.append(f"    {r} {vs}{tail}")
            else:
                # 3 维及以上：方括号元组逐条列出（未经 glpsol 实测，语法待验证）
                from itertools import product
                pools = [m.sets[s].members for s in dom]
                recs = [f"[{','.join(inst)}] {_fmt(v)}"
                        for inst, v in zip(product(*pools), vals)]
                L.append(f"param {name} := {' '.join(recs)};")
        L.append("end;")
        return '\n'.join(L) + '\n'


def emit(model):
    return _Emitter(model).emit()
