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

    Aub, bub, Aeq, beq = [], [], [], []
    for _nm, coef, op, rhs in f.rows:
        row = np.zeros(n)
        for k, v in coef.items():
            row[pos[k]] = v
        if op == '<=':
            Aub.append(row)
            bub.append(rhs)
        elif op == '>=':
            Aub.append(-row)
            bub.append(-rhs)
        else:
            Aeq.append(row)
            beq.append(rhs)

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

    res = linprog(c,
                  A_ub=np.array(Aub) if Aub else None,
                  b_ub=np.array(bub, dtype=float) if bub else None,
                  A_eq=np.array(Aeq) if Aeq else None,
                  b_eq=np.array(beq, dtype=float) if beq else None,
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
