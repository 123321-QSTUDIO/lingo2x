"""scipy (HiGHS) 直解后端：不经过文件，实例化后直接求解并返回结果。

需要 numpy + scipy（>= 1.9 才支持整数/0-1 变量的 HiGHS MIP）。
"""
from ..instantiate import flatten


class BackendError(Exception):
    pass


def solve(model):
    try:
        import numpy as np
        import scipy
        from scipy import sparse
        from scipy.optimize import linprog
    except ImportError:
        raise BackendError("scipy 后端需要 numpy 和 scipy：pip install numpy scipy")

    f = flatten(model)
    pos = {k: i for i, k in enumerate(f.keys)}
    n = len(f.keys)

    c = np.zeros(n)
    for k, v in f.obj.items():
        c[pos[k]] = v
    if f.sense == 'max':
        c = -c

    # 稀疏装配：稠密行向量的内存是 行数×列数，稀疏三元组只随非零元增长
    ub_list, eq_list = [], []
    for _nm, coef, op, rhs in f.rows:
        if op == '=':
            eq_list.append((coef, rhs))
        elif op == '<=':
            ub_list.append((coef, rhs))
        else:
            ub_list.append(({k: -v for k, v in coef.items()}, -rhs))

    def to_csr(lst):
        if not lst:
            return None, None
        ri, ci, vv, bb = [], [], [], []
        for coef, rhs in lst:
            r = len(bb)
            for k, v in coef.items():
                ri.append(r)
                ci.append(pos[k])
                vv.append(v)
            bb.append(rhs)
        return sparse.csr_matrix((vv, (ri, ci)), shape=(len(bb), n)), np.array(bb)

    A_ub, b_ub = to_csr(ub_list)
    A_eq, b_eq = to_csr(eq_list)

    bounds = []
    for k in f.keys:
        if k in f.free:
            bounds.append((None, None))
        elif f.kind[k] == 'bin':
            bounds.append((0, 1))
        else:
            bounds.append((0, None))

    integrality = None
    if any(f.kind[k] != 'cont' for k in f.keys):
        major, minor = (int(x) for x in scipy.__version__.split('.')[:2])
        if (major, minor) < (1, 9):
            raise BackendError(f"整数/0-1 变量需要 scipy >= 1.9，当前 {scipy.__version__}")
        integrality = np.array([0 if f.kind[k] == 'cont' else 1 for k in f.keys])

    res = linprog(c, A_ub=A_ub, b_ub=b_ub, A_eq=A_eq, b_eq=b_eq,
                  bounds=bounds, integrality=integrality, method='highs')
    obj = None
    if res.fun is not None:
        obj = -res.fun if f.sense == 'max' else res.fun
    if res.success and model.ole_writes:
        from ..resolve import write_ole_back
        import os
        write_ole_back(model, f, res.x,
                       os.path.dirname(os.path.abspath(model.source)) if model.source else '.')
    return {
        'success': bool(res.success),
        'message': str(res.message),
        'objective': obj,
        'values': {} if res.x is None else {f.labels[k]: float(res.x[i]) for i, k in enumerate(f.keys)},
    }
