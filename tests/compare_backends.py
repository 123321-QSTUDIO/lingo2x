"""回归测试：对 tests/github 下所有可翻译的 .lng 模型，
分别走 gmpl→glpsol 和 scipy 两条路求解，比对最优值是否一致。

用法：.venv/Scripts/python tests/compare_backends.py
（glpsol 路径默认 tools/glpk-4.65/w64/glpsol.exe，可用环境变量 GLPSOL 覆盖）
"""
import glob
import os
import re
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GLPSOL = os.environ.get('GLPSOL', os.path.join(ROOT, 'tools', 'glpk-4.65', 'w64', 'glpsol.exe'))
# 每次运行在独立临时目录里写求解器工件，避免共享目录下可预测的固定文件名
TMP = tempfile.mkdtemp(prefix='lingo2x_cmp_')
PY = sys.executable


def _run(args):
    r = subprocess.run(args, capture_output=True, cwd=ROOT)
    return (r.returncode,
            r.stdout.decode('utf-8', errors='replace') if r.stdout else '')


def solve_scipy(path):
    _rc, out = _run([PY, '-m', 'lingo2x', path, '-b', 'scipy'])
    m = re.search(r'最优值: ([-\d.eE+]+)', out)
    return float(m.group(1)) if m else None


def solve_glpsol(path):
    mod = os.path.join(TMP, os.path.basename(path) + '.mod')
    out = os.path.join(TMP, 'lingo2x_glpsol_out.txt')
    rc, _ = _run([PY, '-m', 'lingo2x', path, '-b', 'gmpl', '-o', mod])
    if rc != 0:
        return None, '翻译失败'
    _rc, console = _run([GLPSOL, '-m', mod, '-o', out])
    text = ''
    if os.path.exists(out):
        text = open(out, encoding='utf-8', errors='replace').read()
    m = re.findall(r'Objective:\s*\S+\s*=\s*([-\d.eE+]+)', text)
    if 'OPTIMAL' not in console or 'SOLUTION FOUND' not in console:
        return None, 'glpsol 未找到最优解'
    return (float(m[-1]) if m else None), 'OK'


def main():
    files = sorted(glob.glob(os.path.join(ROOT, 'tests', 'github', '*.lng')))
    ok = diff = skipped = 0
    for f in files:
        name = os.path.basename(f)
        g_obj, g_st = solve_glpsol(f)
        if g_st == '翻译失败':
            skipped += 1
            continue
        s_obj = solve_scipy(f)
        if g_obj is None or s_obj is None:
            print(f'??    {name:35s} glpsol={g_obj} ({g_st}) scipy={s_obj}')
            diff += 1
            continue
        tol = 1e-4 * max(1.0, abs(s_obj))
        if abs(g_obj - s_obj) <= tol:
            print(f'MATCH {name:35s} glpsol={g_obj:g}  scipy={s_obj:g}')
            ok += 1
        else:
            print(f'DIFF! {name:35s} glpsol={g_obj:g}  scipy={s_obj:g}')
            diff += 1
    print(f'--- {ok} 一致, {diff} 不一致/异常, {skipped} 个跳过（不可翻译）')
    return 0 if diff == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
