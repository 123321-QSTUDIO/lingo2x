"""求解器后端注册表。

新增后端：写一个模块，实现 emit(model) -> str（文本后端）
或 solve(model) -> dict（直解后端），然后在 BACKENDS 里登记即可。
"""
from . import gmpl, lp, scipy_backend

BACKENDS = {
    'gmpl': gmpl,               # 输出 .mod，用 glpsol (GLPK) 求解
    'lp': lp,                   # 输出 .lp，CBC / HiGHS / SCIP / glpsol 通用
    'scipy': scipy_backend,     # 直接调用 scipy（HiGHS）求解
}
