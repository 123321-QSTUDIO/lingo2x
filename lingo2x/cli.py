"""命令行入口：python -m lingo2x 模型.lgo [-b 后端] [-o 输出文件] [--check]"""
import argparse
import os
import re
import sys

from .parser import parse_file, parse_text, load_text
from .model import analyze
from .backends import BACKENDS

_EXT = {'gmpl': '.mod', 'lp': '.lp'}


def _check(path):
    """语法检查：通过返回 0；失败输出 'path:行:列: 消息' 返回 1。"""
    text = load_text(path)
    try:
        parse_text(text, path)
    except Exception as e:
        msg = str(e)
        m = re.search(r'位置 (\d+)', msg)
        if m:
            off = int(m.group(1))
            line = text.count('\n', 0, off) + 1
            col = off - text.rfind('\n', 0, off)
            print(f'{path}:{line}:{col}: {msg}')
        else:
            print(f'{path}:1:1: {msg}')
        return 1
    print('OK: 语法检查通过')
    return 0


def main(argv=None):
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass
    ap = argparse.ArgumentParser(
        prog='lingo2x',
        description='LINGO 语法 → 中间模型 → 开源求解器后端（gmpl / lp / scipy）')
    ap.add_argument('model', help='LINGO 模型文件（.lgo）')
    ap.add_argument('-b', '--backend', default='gmpl', choices=sorted(BACKENDS),
                    help='求解器后端（默认 gmpl）')
    ap.add_argument('-o', '--output',
                    help='输出文件；默认与输入同名换扩展名；"-" 表示输出到屏幕')
    ap.add_argument('--check', action='store_true',
                    help='只做语法检查；错误以 "文件:行:列: 消息" 格式输出（供编辑器调用）')
    args = ap.parse_args(argv)

    if args.check:
        return _check(args.model)

    m = parse_file(args.model)
    be = BACKENDS[args.backend]

    if hasattr(be, 'solve'):                       # 直解后端
        r = be.solve(m)
        print(f"状态: {r['message']}")
        if r['success']:
            print(f"最优值: {r['objective']:g}")
            for k, v in r['values'].items():
                if abs(v) > 1e-9:
                    print(f"  {k} = {v:g}")
        return 0 if r['success'] else 1

    text = be.emit(m)                              # 文本后端
    out = args.output
    if out is None:
        out = os.path.splitext(args.model)[0] + _EXT.get(args.backend, '.txt')
    if out == '-':
        sys.stdout.write(text)
    else:
        with open(out, 'w', encoding='utf-8') as fp:
            fp.write(text)
        sy = analyze(m)
        print(f"[{args.backend}] 集合 {len(m.sets)} | 参数 {len(sy.params)} | "
              f"变量族 {len(sy.vars)} | 约束 {len(m.constraints)}")
        print(f"已写出: {out}")
    return 0
