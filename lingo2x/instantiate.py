"""实例化器：把 IR 按集合成员展开成扁平线性规划（FlatLP）。

LP 文件后端和 scipy 后端都基于 FlatLP；GMPL 后端不需要它（保持符号形式）。
"""
from dataclasses import dataclass, field
from itertools import product

from .model import (Num, Ref, Bin, Neg, Sum, IVar, QCmp, QAnd, QOr, QNot,
                    Func, analyze, MAX_INSTANCES)


class InstantiateError(Exception):
    pass


@dataclass
class LinExpr:
    """线性表达式：{变量实例: 系数} + 常数项。变量实例 = (族名, (成员下标...))。"""
    coef: dict = field(default_factory=dict)
    const: float = 0.0

    def add(self, other, sign=1.0):
        for k, v in other.coef.items():
            self.coef[k] = self.coef.get(k, 0.0) + sign * v
        self.const += sign * other.const
        return self


@dataclass
class FlatLP:
    sense: str                       # 'max' | 'min'
    keys: list                       # 全部变量实例（求解向量顺序）
    kind: dict                       # key -> 'cont' | 'bin' | 'int'
    free: set                        # 自由变量（无 >= 0 限制）
    obj: dict                        # key -> 目标系数
    rows: list                       # (名称, {key: 系数}, op, 右端常数)
    labels: dict                     # key -> 字符串标签，如 X_W1_C1


def _neg(a):
    return LinExpr({k: -v for k, v in a.coef.items()}, -a.const)


def _mul(a, b):
    if a.coef and b.coef:
        raise InstantiateError("出现变量×变量：本工具只支持线性表达式")
    if b.coef:
        a, b = b, a
    if not a.coef:
        return LinExpr(const=a.const * b.const)
    return LinExpr({k: v * b.const for k, v in a.coef.items()}, a.const * b.const)


def _div(a, b):
    if b.coef:
        raise InstantiateError("除数含变量：本工具只支持线性表达式")
    if b.const == 0:
        raise InstantiateError("除以 0")
    return LinExpr({k: v / b.const for k, v in a.coef.items()}, a.const / b.const)


def _normkey(v):
    """下标值归一成成员键：数字 2.0 → '2'，字符串成员原样保留。"""
    if isinstance(v, str):
        return v
    f = float(v)
    return str(int(f)) if f.is_integer() else str(f)


def _tonum(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        raise InstantiateError(f"成员 {v!r} 不是数字，不能参与算术或数值比较")


class Flattener:
    def __init__(self, model):
        self.m = model
        sy = analyze(model)
        # 参数值表：(族名, 实例) -> 数值
        self.values = {}
        for name, (dom, vals) in sy.params.items():
            for inst, v in zip(self._instances(dom), vals):
                self.values[(name, inst)] = v
        # 变量实例
        self.keys = []
        self.kind = {}
        self.free = set()
        for name, dom in sy.vars.items():
            kd = model.varkind.get(name)
            for inst in self._instances(dom):
                key = (name, inst)
                self.keys.append(key)
                self.kind[key] = {'bin': 'bin', 'gin': 'int'}.get(kd, 'cont')
                if kd == 'free':
                    self.free.add(key)
                if len(self.keys) > MAX_INSTANCES:
                    raise InstantiateError(
                        f"变量实例总数超过上限 {MAX_INSTANCES}（防内存耗尽）；"
                        "请缩小集合规模或拆分模型")

    def _instances(self, dom):
        if not dom:
            yield ()
            return
        pools = [self.m.sets[s].members for s in dom]
        if any(not p for p in pools):
            raise InstantiateError(
                f"集合 {'/'.join(dom)} 没有成员（在 SETS 或 DATA 中定义成员后再试）")
        yield from product(*pools)

    # ---- 下标表达式求值（结果：成员字符串或数字）----
    def eval_idx(self, e, env):
        if isinstance(e, IVar):
            if e.name in env:
                return env[e.name]
            return e.name               # 未绑定 → 当作字面成员名
        if isinstance(e, Num):
            return e.value
        if isinstance(e, Neg):
            return -_tonum(self.eval_idx(e.x, env))
        if isinstance(e, Bin):
            a = _tonum(self.eval_idx(e.l, env))
            b = _tonum(self.eval_idx(e.r, env))
            if e.op == '+':
                return a + b
            if e.op == '-':
                return a - b
            if e.op == '*':
                return a * b
            if e.op == '^':
                return a ** b
            if b == 0:
                raise InstantiateError("下标表达式除以 0")
            return a / b
        raise InstantiateError(f"下标表达式中出现非法节点 {type(e).__name__}")

    # ---- 条件过滤式求值 ----
    def eval_qual(self, q, env):
        if isinstance(q, QCmp):
            lv, rv = self.eval_idx(q.l, env), self.eval_idx(q.r, env)
            try:
                lv, rv = _tonum(lv), _tonum(rv)
            except InstantiateError:
                if q.op not in ('=', '!='):
                    raise
                lv, rv = str(lv), str(rv)
            return {'<=': lv <= rv, '>=': lv >= rv, '=': lv == rv,
                    '!=': lv != rv, '<': lv < rv, '>': lv > rv}[q.op]
        if isinstance(q, QAnd):
            return self.eval_qual(q.a, env) and self.eval_qual(q.b, env)
        if isinstance(q, QOr):
            return self.eval_qual(q.a, env) or self.eval_qual(q.b, env)
        if isinstance(q, QNot):
            return not self.eval_qual(q.a, env)
        raise InstantiateError(f"条件过滤式中出现非法节点 {type(q).__name__}")

    def _combos(self, domain, qual, env):
        """枚举域内成员组合，套用条件过滤，产出绑定后的 env。"""
        idx = [d[0] for d in domain]
        pools = [self.m.sets[s].members for _, s in domain]
        for combo in product(*pools):
            env2 = {**env, **dict(zip(idx, combo))}
            if qual is None or self.eval_qual(qual, env2):
                yield env2

    # ---- 表达式求值（要求线性）----
    def eval(self, e, env):
        if isinstance(e, Num):
            return LinExpr(const=e.value)
        if isinstance(e, Ref):
            inst = tuple(_normkey(self.eval_idx(x, env)) for x in e.indices)
            key = (e.name, inst)
            if key in self.values:
                return LinExpr(const=self.values[key])
            if key in self.kind:
                return LinExpr(coef={key: 1.0})
            shown = f"{e.name}({', '.join(inst)})" if inst else e.name
            raise InstantiateError(f"{shown} 未定义（不是参数也不是变量实例）")
        if isinstance(e, Neg):
            return _neg(self.eval(e.x, env))
        if isinstance(e, Bin):
            a, b = self.eval(e.l, env), self.eval(e.r, env)
            if e.op == '+':
                return a.add(b)
            if e.op == '-':
                return a.add(b, -1.0)
            if e.op == '*':
                return _mul(a, b)
            if e.op == '/':
                return _div(a, b)
            if e.op == '^':
                if a.coef or b.coef:
                    raise InstantiateError(
                        "幂运算 ^ 只支持常数底数与常数指数（保持模型线性）")
                try:
                    return LinExpr(const=a.const ** b.const)
                except (OverflowError, ZeroDivisionError):
                    raise InstantiateError("幂运算结果溢出或 0 的负次幂")
            raise InstantiateError(f"未知运算符 {e.op}")
        if isinstance(e, Sum):
            out = LinExpr()
            for env2 in self._combos(e.domain, e.qual, env):
                out.add(self.eval(e.body, env2))
            return out
        if isinstance(e, Func):
            raise InstantiateError(
                f"@{e.name.upper()} 是非线性函数，只能用于 CALC 段计算参数；"
                "目标/约束中不允许出现（本工具只解线性模型）")
        raise InstantiateError(f"未知表达式节点 {type(e).__name__}")

    @staticmethod
    def _label(key):
        """变量实例 → 标签。各组件先转义 '_' 再拼接，保证单射：
        成员 'A_B'（X_A__B）与成员对 ('A','B')（X_A_B）不再混淆。"""
        name, inst = key
        parts = [name] + [str(p) for p in inst]
        return '_'.join(p.replace('_', '__') for p in parts)

    def flatten(self):
        m = self.m
        obj = self.eval(m.objective, {})
        if not obj.coef:
            raise InstantiateError("目标函数不含任何决策变量")
        rows = []
        for i, c in enumerate(m.constraints, 1):
            for env in self._combos(c.domain, c.qual, {}):
                diff = self.eval(c.lhs, env).add(self.eval(c.rhs, env), -1.0)  # lhs - rhs
                coef = {k: v for k, v in diff.coef.items() if v != 0.0}
                if not coef:
                    raise InstantiateError(f"约束 {c.name or i} 展开后不含变量")
                base = c.name or f'c{i}'
                if c.domain:
                    suffix = '_'.join(_normkey(env[v]) for v, _ in c.domain)
                    base = f"{base}_{suffix}"
                rows.append((base, coef, c.op, -diff.const))
                if len(rows) > MAX_INSTANCES:
                    raise InstantiateError(
                        f"约束展开行数超过上限 {MAX_INSTANCES}（防内存耗尽）；"
                        "请缩小集合规模或拆分模型")
        labels = {key: self._label(key) for key in self.keys}
        return FlatLP(m.sense, self.keys, self.kind, self.free, obj.coef, rows, labels)


def flatten(model):
    return Flattener(model).flatten()
