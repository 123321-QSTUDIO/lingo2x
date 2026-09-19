"""LINGO 语法分析：token 流 → 中间模型（IR）。

支持的 LINGO 子集：
  MODEL:/END（可选）、SETS:/ENDSETS、DATA:/ENDDATA、
  基本集：显式成员 /a,b,c/、区间 /1..N/、/MON..FRI/、或在 DATA 中定义成员；
  派生集：父集笛卡尔积（不支持 | 成员过滤）；
  [name] MAX=/MIN= 目标、线性约束（<= >= =，#LE# 等同义写法，< > 按 <= >= 处理）、
  @SUM/@FOR：可省略下标（隐式下标）、支持 | 条件过滤与 #AND#/#OR#/#NOT#、
  @BIN/@GIN/@FREE、命名约束 [name]（含 @FOR 体内）、嵌套 @FOR、
  下标算术（如 X(i-1)）、字面成员下标（如 x(5,5)）、大小写不敏感的名字。
明确不支持（给出清晰报错）：@OLE/@POINTER/@FILE 等外部数据、CALC:/procedure 段、
  非线性表达式。
"""
import re

from .lexer import tokenize
from .model import (Model, SetDef, Constraint, Num, Ref, Bin, Neg, Sum,
                    IVar, QCmp, QAnd, QOr, QNot, CalcAssign, CalcFor, CalcCall,
                    Func, validate_member, MAX_SET_MEMBERS)


class ParseError(Exception):
    pass


_KIND = {'@BIN': 'bin', '@GIN': 'gin', '@FREE': 'free'}
_HASH_CMP = {'#LE#': '<=', '#GE#': '>=', '#EQ#': '=', '#NE#': '!=',
             '#LT#': '<', '#GT#': '>'}
_DAYS = 'MON TUE WED THU FRI SAT SUN'.split()
_MONTHS = 'JAN FEB MAR APR MAY JUN JUL AUG SEP OCT NOV DEC'.split()
_EXTERNAL = ('@OLE', '@POINTER', '@FILE', '@TEXT', '@TABLE', '@WRITE', '@STATUS')


class Parser:
    def __init__(self, text):
        self.toks = tokenize(text)
        self.i = 0
        self.m = Model()
        self._canon = {}      # 大写名字 → 首次出现的写法（LINGO 大小写不敏感）
        self._fresh = 0       # 隐式下标变量计数器
        self._ctx = []        # 隐式下标上下文栈：元素为 domain 元组
        self._depth = 0       # 表达式/条件式递归深度（防栈溢出）

    _MAX_DEPTH = 200

    def _enter(self, what):
        self._depth += 1
        if self._depth > self._MAX_DEPTH:
            self._depth -= 1
            raise ParseError(f"{what}嵌套过深（超过 {self._MAX_DEPTH} 层），疑似畸形输入")

    def _leave(self):
        self._depth -= 1

    # ---- 基础工具 ----
    def peek(self, k=0):
        return self.toks[min(self.i + k, len(self.toks) - 1)]

    def next(self):
        t = self.toks[self.i]
        if t[0] != 'EOF':
            self.i += 1
        return t

    def err(self, msg):
        raise ParseError(f"{msg}（位置 {self.peek()[2]} 附近）")

    def at_op(self, *ops):
        t = self.peek()
        return t[0] == 'OP' and t[1] in ops

    def accept_op(self, op):
        if self.at_op(op):
            self.next()
            return True
        return False

    def expect_op(self, op):
        if not self.accept_op(op):
            self.err(f"期望 '{op}'，得到 {self.peek()[1]!r}")

    def at_kw(self, *kws):
        t = self.peek()
        return t[0] == 'ID' and t[1].upper() in kws

    def accept_kw(self, kw):
        if self.at_kw(kw):
            self.next()
            return True
        return False

    def expect_id(self, what='标识符'):
        t = self.next()
        if t[0] != 'ID':
            raise ParseError(f"期望{what}，得到 {t[1]!r}（位置 {t[2]}）")
        return t[1]

    def _name(self, what='标识符'):
        """模型名字：大小写不敏感，归一到首次出现的写法。"""
        raw = self.expect_id(what)
        return self._canon.setdefault(raw.upper(), raw)

    def _id_list(self):
        out = [self.expect_id()]
        while self.accept_op(','):
            out.append(self.expect_id())
        return out

    def _fresh_var(self):
        self._fresh += 1
        return f'_i{self._fresh}'

    # ---- 顶层 ----
    def parse(self):
        if self.accept_kw('MODEL'):
            self.expect_op(':')
        while not self.at_kw('END'):
            if self.peek()[0] == 'EOF':
                break
            if self.accept_kw('CALC'):
                self.expect_op(':')
                self.m.calc_main.extend(self._calc_block('ENDCALC'))
                continue
            if self.accept_kw('PROCEDURE'):
                pname = self._name('过程名')
                self.expect_op(':')
                self.m.calc_procs[pname] = self._calc_block('ENDPROCEDURE')
                continue
            if self.accept_kw('SETS'):
                self.expect_op(':')
                self.parse_sets()
            elif self.accept_kw('DATA'):
                self.expect_op(':')
                self.parse_data()
            else:
                self.parse_statement()
        self.accept_kw('END')
        if self.m.sense is None:
            raise ParseError("缺少目标函数（需要 MAX = ...; 或 MIN = ...;）")
        return self.m

    # ---- SETS 段 ----
    def parse_sets(self):
        while not self.accept_kw('ENDSETS'):
            name = self._name('集合名')
            if name in self.m.sets:
                self.err(f"集合 {name} 重复定义")
            parents = ()
            if self.accept_op('('):
                parents = tuple(self._canon.setdefault(a.upper(), a)
                                for a in self._id_list())
                self.expect_op(')')
            members = []
            if self.accept_op('/'):
                members = self._member_list()
                self.expect_op('/')
            if self.at_op('|'):
                self.err(f"暂不支持派生集 {name} 的成员过滤（| 条件）")
            attrs = []
            if self.accept_op(':'):
                if not self.at_op(';'):
                    attrs = [self._canon.setdefault(a.upper(), a)
                             for a in self._id_list()]
            self.expect_op(';')
            if parents and members:
                self.err(f"派生集 {name} 暂不支持显式成员列表（只支持笛卡尔积）")
            for p in parents:
                if p not in self.m.sets or self.m.sets[p].parents:
                    self.err(f"派生集 {name} 的父集 {p} 必须是已定义的基本集")
            self.m.sets[name] = SetDef(name, parents, members, attrs)

    def _member_list(self):
        out = []
        while not self.at_op('/'):
            if self.accept_op(','):
                continue
            t = self.next()
            if t[0] == 'AT':
                raise ParseError(f"暂不支持外部数据源 {t[1]} 定义集合成员（位置 {t[2]}）")
            if t[0] not in ('ID', 'NUM', 'STR'):
                raise ParseError(f"集合成员应为标识符或数字，得到 {t[1]!r}（位置 {t[2]}）")
            if self.accept_op('..'):
                t2 = self.next()
                if t2[0] not in ('ID', 'NUM'):
                    raise ParseError(f"区间右端应为标识符或数字，得到 {t2[1]!r}（位置 {t2[2]}）")
                out.extend(self._expand_range(t[1], t2[1]))
            else:
                out.append(validate_member(t[1]))
            if len(out) > MAX_SET_MEMBERS:
                self.err(f"集合成员数超过上限 {MAX_SET_MEMBERS}（防内存耗尽）")
        return out

    def _expand_range(self, a, b):
        if re.fullmatch(r'\d+', a) and re.fullmatch(r'\d+', b):
            if len(a) > 9 or len(b) > 9:
                self.err(f"区间 {a}..{b} 端点过大")
            lo, hi = int(a), int(b)
            if lo > hi:
                self.err(f"区间 {a}..{b} 左端大于右端")
            if hi - lo + 1 > MAX_SET_MEMBERS:
                self.err(f"区间 {a}..{b} 展开后有 {hi - lo + 1} 个成员，"
                         f"超过上限 {MAX_SET_MEMBERS}（防内存耗尽）")
            return [str(i) for i in range(lo, hi + 1)]
        for table in (_DAYS, _MONTHS):
            ua, ub = a.upper(), b.upper()
            if ua in table and ub in table:
                return table[table.index(ua):table.index(ub) + 1]
        self.err(f"无法展开的区间成员 {a}..{b}")

    # ---- DATA 段 ----
    def _parse_ole_call(self):
        """@OLE('文件' [, '区域']) → (文件名, 区域或None)"""
        self.next()                            # @OLE
        self.expect_op('(')
        t = self.next()
        if t[0] != 'STR':
            raise ParseError(f"@OLE 的第一个参数应为文件名字符串，得到 {t[1]!r}（位置 {t[2]}）")
        fname = t[1]
        rng = None
        if self.accept_op(','):
            t = self.next()
            if t[0] != 'STR':
                raise ParseError(f"@OLE 的区域参数应为字符串，得到 {t[1]!r}（位置 {t[2]}）")
            rng = t[1]
        self.expect_op(')')
        return fname, rng

    def parse_data(self):
        while not self.accept_kw('ENDDATA'):
            t = self.peek()
            if t[0] == 'AT':
                f = t[1].upper()
                if f == '@OLE':                # @OLE('f','r') = X, Y; → 求解后写回 Excel
                    fname, rng = self._parse_ole_call()
                    self.expect_op('=')
                    names = [self._canon.setdefault(a.upper(), a) for a in self._id_list()]
                    self.expect_op(';')
                    self.m.ole_writes.append((fname, rng, names))
                    continue
                self.err(f"暂不支持外部数据/输出函数 {f}；DATA 段只支持 @OLE")
            names = [self._canon.setdefault(a.upper(), a) for a in self._id_list()]
            self.expect_op('=')
            if self.peek()[0] == 'AT':
                f = self.peek()[1].upper()
                if f == '@OLE':                # 名 = @OLE('f'[,'r']); → 从 Excel 读
                    fname, rng = self._parse_ole_call()
                    self.expect_op(';')
                    self.m.ole_reads.append((names, fname, rng))
                    continue
                self.err(f"暂不支持外部数据函数 {f}；DATA 段只支持 @OLE")
            vals = []
            while not self.at_op(';'):
                if self.accept_op(','):
                    continue
                sign = 1.0
                if self.accept_op('-'):
                    sign = -1.0
                else:
                    self.accept_op('+')
                t = self.next()
                if t[0] == 'NUM':
                    vals.append(sign * float(t[1]))
                elif t[0] in ('ID', 'STR') and sign > 0:
                    vals.append(t[1])
                else:
                    raise ParseError(f"DATA 的值应为数字或成员名，得到 {t[1]!r}（位置 {t[2]}）")
            self.expect_op(';')
            k = len(names)
            if len(vals) % k:
                self.err(f"多名字赋值的值个数（{len(vals)}）应为名字个数（{k}）的倍数")
            for j, name in enumerate(names):
                self._assign_data(name, vals[j::k])

    def _assign_data(self, name, sub):
        if name in self.m.sets:
            sd = self.m.sets[name]
            if sd.parents:
                self.err(f"派生集 {name} 不能在 DATA 中定义成员")
            if len(sub) > MAX_SET_MEMBERS:
                self.err(f"集合 {name} 成员数超过上限 {MAX_SET_MEMBERS}（防内存耗尽）")
            mems = [validate_member(self._member_str(v), where=f'（集合 {name} 的 DATA）')
                    for v in sub]
            if sd.members and sd.members != mems:
                self.err(f"集合 {name} 的成员重复定义且不一致")
            sd.members = mems
        else:
            nums = []
            for v in sub:
                if not isinstance(v, float):
                    self.err(f"参数 {name} 的数据必须是数字，得到 {v!r}")
                nums.append(v)
            self.m.data[name] = nums

    @staticmethod
    def _member_str(v):
        return f"{v:g}" if isinstance(v, float) else str(v)

    # ---- 语句 ----
    def parse_statement(self):
        t = self.peek()
        if t[0] == 'AT':
            f = t[1].upper()
            if f == '@FOR':
                return self.parse_for()
            if f in _KIND:                       # @BIN(X); 直接修饰整个变量族
                self.next()
                self.expect_op('(')
                self.m.varkind[self._name('变量名')] = _KIND[f]
                self.expect_op(')')
                self.expect_op(';')
                return
            # 其他 @ 函数（如 @SUM(...) <= 10;）按普通表达式约束处理
        name = None
        if self.accept_op('['):
            name = self.expect_id('约束名')
            self.expect_op(']')
        if self.at_kw('MAX', 'MIN'):               # [name] MAX = ...; 命名目标
            sense = 'max' if self.peek()[1].upper() == 'MAX' else 'min'
            self.next()
            self.expect_op('=')
            self._ctx.append(())
            e = self.expr()
            self._ctx.pop()
            self.expect_op(';')
            if self.m.sense is not None:
                self.err("只能有一个目标函数")
            self.m.sense, self.m.objective = sense, e
            return
        lhs = self.expr()
        op = self._compare_op()
        rhs = self.expr()
        self.expect_op(';')
        self.m.constraints.append(Constraint(lhs, op, rhs, name))

    def _compare_op(self):
        t = self.next()
        if t[0] == 'OP':
            v = _HASH_CMP.get(t[1], t[1])
            if v == '!=':
                raise ParseError(f"线性约束不支持 #NE#（位置 {t[2]}）")
            if v in ('<=', '>=', '=', '<', '>'):
                return {'<': '<=', '>': '>='}.get(v, v)   # LINGO 中 < > 即 <= >=
        raise ParseError(f"期望比较运算符（<=、>=、=），得到 {t[1]!r}（位置 {t[2]}）")

    # ---- CALC 段 / procedure ----
    def _calc_block(self, end_kw):
        stmts = []
        while not self.accept_kw(end_kw):
            if self.peek()[0] == 'EOF':
                self.err(f"缺少 {end_kw}")
            st = self._calc_stmt()
            if st is not None:
                stmts.append(st)
        return stmts

    def _calc_stmt(self, in_for=False):
        t = self.peek()
        if t[0] == 'AT':
            f = t[1].upper()
            if f == '@FOR':
                return self._calc_for()
            if f in ('@TEXT', '@TABLE', '@WRITE'):   # 显示类函数：解析并忽略
                self.next()
                if self.accept_op('('):
                    depth = 1
                    while depth and self.peek()[0] != 'EOF':
                        if self.accept_op('('):
                            depth += 1
                        elif self.accept_op(')'):
                            depth -= 1
                        else:
                            self.next()
                if self.accept_op('='):
                    self.next()                # 忽略右侧（一般是输出字符串）
                self.expect_op(';')
                return None
            self.err(f"CALC 段中暂不支持函数 {f}")
        name = self._name('名字')
        if self.accept_op(';'):                # 裸名字：调用 procedure
            return CalcCall(name)
        idx = ()
        if self.accept_op('('):
            idx = [self._idx_expr()]
            while self.accept_op(','):
                idx.append(self._idx_expr())
            self.expect_op(')')
        self.expect_op('=')
        e = self.expr()
        if not in_for:                         # @FOR 体内的赋值不带分号
            self.expect_op(';')
        return CalcAssign(name, tuple(idx), e)

    def _calc_for(self):
        self.next()                            # @FOR
        domain, qual = self._for_head()
        self.expect_op(':')
        self._ctx.append(domain)
        try:
            body = self._calc_stmt(in_for=True)
        finally:
            self._ctx.pop()
        self.expect_op(')')
        self.expect_op(';')
        return CalcFor(domain, qual, [body] if body is not None else [])

    # ---- @FOR ----
    def parse_for(self):
        self.next()                                # @FOR
        domain, qual = self._for_head()
        self.expect_op(':')
        self._for_body(domain, qual)
        self.expect_op(')')
        self.expect_op(';')

    def _for_head(self):
        self.expect_op('(')
        setname = self._name('集合名')
        if setname not in self.m.sets:
            self.err(f"集合 {setname} 未定义（SETS 段需出现在语句之前）")
        idx = []
        if self.accept_op('('):
            idx = self._id_list()
            self.expect_op(')')
        qual = None
        if self.accept_op('|'):
            qual = self._qual()
        return self._domain(setname, idx), qual

    def _for_body(self, domain, qual):
        t = self.peek()
        if t[0] == 'AT' and t[1].upper() == '@FOR':      # 嵌套 @FOR
            self.next()
            d2, q2 = self._for_head()
            self.expect_op(':')
            self._for_body(domain + d2, self._and(qual, q2))
            self.expect_op(')')
            return
        if t[0] == 'AT' and t[1].upper() in _KIND:       # @FOR(S(I): @BIN(X(I)))
            f = t[1].upper()
            self.next()
            self.expect_op('(')
            name = self._name('变量名')
            if self.accept_op('('):                      # 吃掉下标部分 X(I)
                self._id_list()
                self.expect_op(')')
            self.expect_op(')')
            self.m.varkind[name] = _KIND[f]
            return
        name = None
        if self.accept_op('['):                          # @FOR 体内的命名约束
            name = self.expect_id('约束名')
            self.expect_op(']')
        self._ctx.append(domain)
        try:
            lhs = self.expr()
            op = self._compare_op()
            rhs = self.expr()
        finally:
            self._ctx.pop()
        self.m.constraints.append(Constraint(lhs, op, rhs, name, domain, qual))

    @staticmethod
    def _and(a, b):
        if a is None:
            return b
        if b is None:
            return a
        return QAnd(a, b)

    def _domain(self, setname, idx):
        dom = self.m.set_domain(setname)
        if not idx:                              # 省略下标 → 生成隐式下标变量
            idx = [self._fresh_var() for _ in dom]
        if len(idx) != len(dom):
            self.err(f"集合 {setname} 是 {len(dom)} 维的，下标变量却有 {len(idx)} 个")
        return tuple(zip(idx, dom))

    # ---- 条件过滤式（| 条件，支持 #AND#/#OR#/#NOT#）----
    def _qual(self):
        return self._qor()

    def _qor(self):
        self._enter('条件过滤式')
        try:
            e = self._qand()
            while self.at_op('#OR#'):
                self.next()
                e = QOr(e, self._qand())
            return e
        finally:
            self._leave()

    def _qand(self):
        e = self._qnot()
        while self.at_op('#AND#'):
            self.next()
            e = QAnd(e, self._qnot())
        return e

    def _qnot(self):
        if self.at_op('#NOT#'):
            self.next()
            return QNot(self._qnot())
        if self.accept_op('('):
            e = self._qor()
            self.expect_op(')')
            return e
        l = self._idx_expr()
        t = self.next()
        op = _HASH_CMP.get(t[1], t[1]) if t[0] == 'OP' else None
        if op not in ('<=', '>=', '=', '!=', '<', '>'):
            raise ParseError(f"条件过滤式中期望比较运算符，得到 {t[1]!r}（位置 {t[2]}）")
        return QCmp(op, l, self._idx_expr())

    # ---- 下标表达式（下标变量与数字的算术）----
    def _idx_expr(self):
        self._enter('下标表达式')
        try:
            e = self._idx_term()
            while self.at_op('+', '-'):
                op = self.next()[1]
                e = Bin(op, e, self._idx_term())
            return e
        finally:
            self._leave()

    def _idx_term(self):
        e = self._idx_atom()
        while self.at_op('*', '/'):
            op = self.next()[1]
            e = Bin(op, e, self._idx_atom())
        return e

    def _idx_atom(self):
        t = self.next()
        if t[0] == 'NUM':
            return Num(float(t[1]), t[1])
        if t[0] == 'ID':
            return IVar(t[1])
        if t[0] == 'OP' and t[1] == '-':
            return Neg(self._idx_atom())
        if t[0] == 'OP' and t[1] == '(':
            e = self._idx_expr()
            self.expect_op(')')
            return e
        raise ParseError(f"下标表达式中出现意外的 {t[1]!r}（位置 {t[2]}）")

    # ---- 表达式（优先级：加减 < 乘除 < 一元负号 < 原子）----
    def expr(self):
        self._enter('表达式')
        try:
            e = self.term()
            while self.at_op('+', '-'):
                op = self.next()[1]
                e = Bin(op, e, self.term())
            return e
        finally:
            self._leave()

    def term(self):
        e = self.factor()
        while self.at_op('*', '/'):
            op = self.next()[1]
            e = Bin(op, e, self.factor())
        return e

    def factor(self):
        if self.accept_op('-'):
            return Neg(self.factor())
        if self.accept_op('+'):
            return self.factor()
        return self.primary()

    def primary(self):
        t = self.next()
        if t[0] == 'NUM':
            return Num(float(t[1]), t[1])
        if t[0] == 'AT':
            if t[1].upper() in ('@SQRT', '@ABS'):
                # 数值函数：仅在 CALC 段可求值；在目标/约束中会被实例化器拒绝
                # （AT token 已在 primary() 开头被消费，不再 next）
                self.expect_op('(')
                arg = self.expr()
                self.expect_op(')')
                return Func(t[1].upper()[1:].lower(), arg)
            if t[1].upper() != '@SUM':
                raise ParseError(f"表达式中暂不支持函数 {t[1].upper()}（位置 {t[2]}）")
            self.expect_op('(')
            setname = self._name('集合名')
            if setname not in self.m.sets:
                self.err(f"集合 {setname} 未定义（SETS 段需出现在语句之前）")
            idx = []
            if self.accept_op('('):
                idx = self._id_list()
                self.expect_op(')')
            qual = None
            if self.accept_op('|'):
                qual = self._qual()
            self.expect_op(':')
            domain = self._domain(setname, idx)
            self._ctx.append(domain)
            try:
                body = self.expr()
            finally:
                self._ctx.pop()
            self.expect_op(')')
            return Sum(domain, body, qual)
        if t[0] == 'ID':
            name = self._canon.setdefault(t[1].upper(), t[1])
            if self.accept_op('('):
                idx = [self._idx_expr()]
                while self.accept_op(','):
                    idx.append(self._idx_expr())
                self.expect_op(')')
                return Ref(name, tuple(idx))
            return Ref(name, self._implicit(name))
        if t[0] == 'OP' and t[1] == '(':
            e = self.expr()
            self.expect_op(')')
            return e
        raise ParseError(f"表达式中出现意外的 {t[1]!r}（位置 {t[2]}）")

    def _implicit(self, name):
        """裸属性名 → 自动补上下标变量。

        在最近一层域（含外层）中按"属性的父集序列是有序子序列"的规则匹配，
        例如 @SUM(ARC(m,p): cout*X) 中 cout（PERIODES 上的一维属性）补为 cout[p]。
        """
        if not self._ctx:
            return ()
        adom = None
        for sd in self.m.sets.values():
            if name in sd.attrs:
                adom = self.m.set_domain(sd.name)
                break
        if not adom:
            return ()
        for dom in reversed(self._ctx):
            if len(dom) < len(adom):
                continue
            chosen = []
            start = 0
            for want in adom:
                found = None
                for j in range(start, len(dom)):
                    if dom[j][1] == want:
                        found = j
                        break
                if found is None:
                    break
                chosen.append(dom[found][0])
                start = found + 1
            if len(chosen) == len(adom):
                return tuple(IVar(v) for v in chosen)
        return ()


def parse_text(text, source=''):
    m = Parser(text).parse()
    m.source = source
    return m


def load_text(path):
    """读源码：先试 UTF-8，失败按 latin-1（老的 LINGO 文件常见编码）。"""
    with open(path, 'rb') as fp:
        raw = fp.read()
    try:
        return raw.decode('utf-8')
    except UnicodeDecodeError:
        return raw.decode('latin-1')


def parse_file(path):
    return parse_text(load_text(path), str(path))
