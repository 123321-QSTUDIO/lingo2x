"""中间模型（IR）：解析器与所有后端共享的数据结构。

层次：LINGO 源码 → parser → Model(IR) → 后端（gmpl / lp / scipy）。
"""
from __future__ import annotations

from dataclasses import dataclass, field


class ModelError(Exception):
    pass


# ---------- 表达式 AST ----------

class Expr:
    """表达式基类。"""


@dataclass
class Num(Expr):
    value: float
    text: str = ""               # 源文件中的字面量，文本后端输出时保留写法


@dataclass
class Ref(Expr):
    name: str                    # 属性/标量名
    indices: tuple = ()          # 下标表达式（IVar/Num/Bin）元组；标量为 ()


@dataclass
class IVar(Expr):
    """下标变量（只在下标表达式和条件过滤式中出现）。"""
    name: str = ""


@dataclass
class Bin(Expr):
    op: str                      # '+' '-' '*' '/'
    l: Expr = None
    r: Expr = None


@dataclass
class Neg(Expr):
    x: Expr = None


# ---- 条件过滤式（@SUM/@FOR 的 | 条件）----

@dataclass
class QCmp(Expr):
    op: str = ""                 # '<=' '>=' '=' '!=' '<' '>'
    l: Expr = None               # 下标表达式
    r: Expr = None


@dataclass
class QAnd(Expr):
    a: Expr = None
    b: Expr = None


@dataclass
class QOr(Expr):
    a: Expr = None
    b: Expr = None


@dataclass
class QNot(Expr):
    a: Expr = None


@dataclass
class Sum(Expr):
    domain: tuple = ()           # ((下标变量, 集合名), ...)
    body: Expr = None
    qual: Expr = None            # | 条件过滤（QCmp/QAnd/QOr/QNot），可选


# ---------- 模型 ----------

@dataclass
class SetDef:
    name: str
    parents: tuple = ()                      # 派生集的父集；基本集为 ()
    members: list = field(default_factory=list)   # 基本集的成员
    attrs: list = field(default_factory=list)


@dataclass
class Constraint:
    lhs: Expr
    op: str                          # '<=' '>=' '='
    rhs: Expr
    name: str | None = None
    domain: tuple = ()               # @FOR 循环域 ((下标变量, 集合名), ...)
    qual: Expr = None                # @FOR 的 | 条件过滤，可选


# ---------- CALC 段语句 ----------

@dataclass
class CalcAssign:
    """CALC/procedure 里的赋值：name(indices) = expr（只允许参数参与运算）。"""
    name: str
    indices: tuple = ()
    expr: Expr = None


@dataclass
class CalcFor:
    domain: tuple = ()
    qual: Expr = None
    body: list = field(default_factory=list)   # CalcAssign / CalcFor / CalcCall


@dataclass
class CalcCall:
    """调用 procedure 定义的过程。"""
    name: str = ""


@dataclass
class Model:
    sets: dict = field(default_factory=dict)       # 名 -> SetDef（保持声明顺序）
    data: dict = field(default_factory=dict)       # 属性/标量名 -> 扁平值列表（行主序）
    sense: str | None = None                       # 'max' | 'min'
    objective: Expr | None = None
    constraints: list = field(default_factory=list)
    varkind: dict = field(default_factory=dict)    # 变量族名 -> 'bin'|'gin'|'free'
    source: str = ""                               # 源文件名，用于输出注释
    # @OLE 外部数据：读 = ([名字...], 文件, 区域或None)；写 = (文件, 区域或None, [名字...])
    ole_reads: list = field(default_factory=list)
    ole_writes: list = field(default_factory=list)
    # CALC 段：procedure 定义表 + 主 CALC 语句序列
    calc_procs: dict = field(default_factory=dict)
    calc_main: list = field(default_factory=list)
    calc_assigned: set = field(default_factory=set)  # CALC 中被赋值的名字（执行时填写）

    def set_domain(self, setname):
        """集合的维度序列：基本集 → 自身；派生集 → 父集序列。"""
        sd = self.sets[setname]
        return sd.parents if sd.parents else (sd.name,)


@dataclass
class Symbols:
    """analyze() 的结果：把名字分类为参数与决策变量。"""
    params: dict = field(default_factory=dict)     # name -> (domain, [值...])
    vars: dict = field(default_factory=dict)       # name -> domain


def _walk(e, acc):
    if isinstance(e, Ref):
        acc.append(e)
    elif isinstance(e, Bin):
        _walk(e.l, acc)
        _walk(e.r, acc)
    elif isinstance(e, Neg):
        _walk(e.x, acc)
    elif isinstance(e, Sum):
        _walk(e.body, acc)


def _check_len(m, name, dom, vals):
    n = 1
    for s in dom:
        n *= len(m.sets[s].members)
    if len(vals) != n:
        raise ModelError(f"{name} 应有 {n} 个值，实际给了 {len(vals)} 个")


def analyze(m: Model) -> Symbols:
    """名字分类：出现在 DATA 中的属性/标量是参数，其余属性是决策变量族。"""
    sy = Symbols()
    attr_of = {}   # 属性名 -> 所在集合名
    for sd in m.sets.values():
        dom = m.set_domain(sd.name)
        for a in sd.attrs:
            if a in attr_of:
                raise ModelError(f"属性 {a} 在集合 {attr_of[a]} 和 {sd.name} 中重名")
            attr_of[a] = sd.name
            if a in m.data:
                if not sd.parents and not sd.members:
                    # 集合未显式给成员：按数据长度推断为 1..N（教学文件常见写法）
                    sd.members = [str(i + 1) for i in range(len(m.data[a]))]
                _check_len(m, a, dom, m.data[a])
                sy.params[a] = (dom, list(m.data[a]))
            else:
                sy.vars[a] = dom

    # 表达式中引用的名字
    refs = []
    if m.objective is not None:
        _walk(m.objective, refs)
    for c in m.constraints:
        _walk(c.lhs, refs)
        _walk(c.rhs, refs)
    for r in refs:
        if r.indices:
            if r.name not in attr_of:
                raise ModelError(f"未定义的名字 {r.name}：带下标的引用必须是集合属性")
            dom = sy.params[r.name][0] if r.name in sy.params else sy.vars[r.name]
            if len(r.indices) != len(dom):
                raise ModelError(f"{r.name} 需要 {len(dom)} 个下标，实际用了 {len(r.indices)} 个")
        else:
            if r.name in m.sets:
                raise ModelError(f"集合名 {r.name} 不能直接出现在表达式中")
            if r.name in attr_of:
                raise ModelError(f"属性 {r.name} 是集合属性，使用时需要下标")
            if r.name in m.data:
                _check_len(m, r.name, (), m.data[r.name])
                sy.params.setdefault(r.name, ((), list(m.data[r.name])))
            else:
                sy.vars.setdefault(r.name, ())

    # @BIN/@GIN/@FREE 的目标必须是变量
    for name in m.varkind:
        if name in sy.params:
            raise ModelError(f"@BIN/@GIN/@FREE 不能作用于参数 {name}")
        sy.vars.setdefault(name, ())

    # DATA 中未被引用的名字也登记为标量参数
    for name, vals in m.data.items():
        if name not in sy.params and name not in attr_of:
            _check_len(m, name, (), vals)
            sy.params[name] = ((), list(vals))
    return sy
