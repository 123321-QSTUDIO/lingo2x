"""特性回归测试：下标遮蔽报错、多行注释、@OLE 报错方向、^ 幂运算、输出格式。

运行：.venv/Scripts/python -m unittest tests.test_features -v
"""
import os
import subprocess
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from lingo2x.parser import parse_text, ParseError, parse_file
from lingo2x.model import ModelError
from lingo2x.instantiate import flatten, InstantiateError
from lingo2x.resolve import resolve_external

_SHADOW_MODEL = """MODEL:
SETS:
    A /1, 2/:;
    B /1, 2/:;
    C /1, 2/: DEM;
    F(A, B, C): X;
ENDSETS
DATA: DEM = 1, 2; ENDDATA
MIN = @SUM(F(i,j,k): X(i,j,k));
%s
@FOR(C(k): @BIN(X(1,1,k)));
END
"""


class TestIndexShadowing(unittest.TestCase):
    """@SUM/@FOR 下标与外层重名：硬错误（静默算错的根治）。"""

    def test_shadowing_rejected(self):
        with self.assertRaises(ParseError) as cm:
            parse_text(_SHADOW_MODEL % "@FOR(C(k): @SUM(F(i,j,k): X(i,j,k)) = DEM(k));")
        self.assertIn('重名', str(cm.exception))

    def test_legit_nested_sum_passes(self):
        m = parse_text(_SHADOW_MODEL %
                       "@FOR(C(k): @SUM(A(i): @SUM(B(j): X(i,j,k))) = DEM(k));")
        f = flatten(m)   # 每层下标名不同：正常展开
        self.assertTrue(any('DEM' not in str(r) for r in f.rows) or f.rows)

    def test_sibling_scope_reuse_ok(self):
        # 兄弟作用域（非嵌套）重用同名下标：不报错
        m = parse_text(_SHADOW_MODEL %
                       ("@FOR(A(i): @SUM(B(j): X(i,j,1)) <= 5);\n"
                        "@FOR(B(i): @SUM(A(j): X(j,i,2)) <= 5);"))
        flatten(m)


class TestComments(unittest.TestCase):
    """多行注释启发式。"""

    def test_prose_continues_to_semicolon(self):
        m = parse_text("! 这是一段多行注释\n"
                       "第二行还是散文说明;\n"
                       "MODEL:\nSETS:\n N /1/: P, X;\nENDSETS\n"
                       "DATA: P = 2; ENDDATA\nMAX = P(1)*X(1);\nEND\n")
        flatten(m)

    def test_single_line_comment_ends_at_newline(self):
        # 教学文件写法：! 注释不带分号，下一行是代码
        m = parse_text("! 单行注释不带分号\n"
                       "MODEL:\nSETS:\n N /1/: P, X;\nENDSETS\n"
                       "DATA: P = 2; ENDDATA\nMAX = P(1)*X(1);\nEND\n")
        flatten(m)

    def test_standardistes_now_parses(self):
        # 该文件头部是整段法语文本注释（真 LINGO 多行注释场景）
        parse_file(os.path.join(ROOT, 'tests', 'github', 'Standardistes.lng'))


class TestOleErrors(unittest.TestCase):
    """@OLE 区域不存在时的报错方向。"""

    def test_missing_named_range_message(self):
        m = parse_file(os.path.join(ROOT, 'tests', 'github', 'Omega.lng'))
        m.ole_reads = [(['PROFIT'], 'Omega.xlsx', 'CX')]
        with self.assertRaises(ModelError) as cm:
            resolve_external(m, os.path.join(ROOT, 'tests', 'github'))
        self.assertIn('命名区域', str(cm.exception))
        self.assertIn('CX', str(cm.exception))


class TestPowerOperator(unittest.TestCase):
    """^ 幂运算：常数可用，变量拒绝。"""

    def test_constant_power_in_objective(self):
        m = parse_text("MODEL:\nSETS:\n N /1/: P, X;\nENDSETS\n"
                       "DATA: P = 1; ENDDATA\n"
                       "MAX = 3^2 * X(1);\nX(1) <= 1;\nEND\n")
        f = flatten(m)
        self.assertEqual(f.obj[('X', ('1',))], 9.0)

    def test_power_in_calc(self):
        m = parse_text("MODEL:\nSETS:\n N /1/: B, X;\nENDSETS\n"
                       "CALC:\n B(1) = 2^10;\nENDCALC\n"
                       "MAX = B(1) * X(1);\nX(1) <= 1;\nEND\n")
        import tempfile
        resolve_external(m, tempfile.mkdtemp())
        f = flatten(m)
        self.assertEqual(f.obj[('X', ('1',))], 1024.0)

    def test_variable_power_rejected(self):
        m = parse_text("MODEL:\nSETS:\n N /1/: P, X;\nENDSETS\n"
                       "DATA: P = 1; ENDDATA\n"
                       "MAX = X(1)^2;\nX(1) <= 1;\nEND\n")
        with self.assertRaises(InstantiateError):
            flatten(m)


class TestCliOutput(unittest.TestCase):
    def test_precision_and_all_flag(self):
        r = subprocess.run([sys.executable, '-m', 'lingo2x',
                            os.path.join(ROOT, 'examples', 'transportation.lgo'),
                            '-b', 'scipy', '--all'],
                           capture_output=True, cwd=ROOT,
                           env={**os.environ, 'PYTHONIOENCODING': 'utf-8'})
        out = r.stdout.decode('utf-8', errors='replace')
        self.assertEqual(r.returncode, 0)
        self.assertIn('最优值: 885', out)
        self.assertIn('X_W1_C1 = 0', out)      # --all 打出零变量
        self.assertIn('X_W1_C2 = 40', out)

    def test_default_hides_zero_vars(self):
        r = subprocess.run([sys.executable, '-m', 'lingo2x',
                            os.path.join(ROOT, 'examples', 'transportation.lgo'),
                            '-b', 'scipy'],
                           capture_output=True, cwd=ROOT,
                           env={**os.environ, 'PYTHONIOENCODING': 'utf-8'})
        out = r.stdout.decode('utf-8', errors='replace')
        self.assertNotIn('X_W1_C1', out)


if __name__ == '__main__':
    unittest.main()
