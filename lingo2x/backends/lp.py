"""LP 文件后端：实例化后输出 CPLEX LP 格式，CBC / HiGHS / SCIP / glpsol 都能读。"""
from ..instantiate import flatten


def _fmt(v):
    return f"{v:g}"


def _terms(coef, labels):
    items = list(coef.items())
    out = []
    for k, v in items:
        mag = '' if abs(v) == 1 else f"{_fmt(abs(v))} "
        t = f"{mag}{labels[k]}"
        if not out:
            out.append(('- ' if v < 0 else '') + t)
        else:
            out.append(('+ ' if v >= 0 else '- ') + t)
    return ' '.join(out)


def emit(model):
    f = flatten(model)
    # 来源路径进了注释：中和块注释分隔符与换行，防注释逃逸
    src = (model.source or 'stdin').replace('*\\', '* \\').replace('\n', ' ')
    L = [f"\\* 由 lingo2x 从 {src} 生成 *\\"]
    L.append('Maximize' if f.sense == 'max' else 'Minimize')
    L.append(f" obj: {_terms(f.obj, f.labels)}")
    L.append('Subject To')
    for nm, coef, op, rhs in f.rows:
        L.append(f" {nm}: {_terms(coef, f.labels)} {op} {_fmt(rhs)}")
    free = [k for k in f.keys if k in f.free]
    bins = [k for k in f.keys if f.kind[k] == 'bin']
    ints = [k for k in f.keys if f.kind[k] == 'int']
    if free:
        L.append('Bounds')
        for k in free:
            L.append(f" -inf <= {f.labels[k]} <= +inf")
    if bins:
        L.append('Binaries')
        L += [f" {f.labels[k]}" for k in bins]
    if ints:
        L.append('Generals')
        L += [f" {f.labels[k]}" for k in ints]
    L.append('End')
    return '\n'.join(L) + '\n'
