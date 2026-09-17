"""安全回归测试：覆盖安全扫描（scan_20260917-150207）各发现对应的边界。

运行：.venv/Scripts/python -m unittest tests.test_security -v
每个测试都包含恶意输入和至少一个合法对照。
"""
import os
import subprocess
import sys
import tempfile
import unittest
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from lingo2x.parser import parse_text, ParseError
from lingo2x.model import analyze, ModelError
from lingo2x.instantiate import flatten, InstantiateError
from lingo2x import resolve as resolve_mod
from lingo2x.resolve import resolve_external
from lingo2x.backends import gmpl, lp


def make_model(text):
    return parse_text(text, source='test.lng')


class TestMemberIntake(unittest.TestCase):
    """findings 7/8/9：成员名别名与求解器文件注入。"""

    def test_injection_member_rejected(self):
        with self.assertRaises(ModelError):
            make_model("MODEL:\nSETS:\n A /'x;y'/ : P;\nENDSETS\n"
                       "MAX = 1;\nEND\n")  # 分号成员会注入 GMPL 数据段

    def test_legit_members_pass(self):
        # 合法对照：标识符与数字成员正常工作
        m = make_model("MODEL:\nSETS:\n A /W1, W_2, 3, v4/: P, X;\nENDSETS\n"
                       "DATA: P = 1, 2, 3, 4; ENDDATA\n"
                       "MAX = @SUM(A(i): P(i)*X(i));\nEND\n")
        analyze(m)
        # DATA 段定义的含 . - 字符成员（引号字符串形式）也应被接受
        m2 = make_model("MODEL:\nSETS:\n A: P, X;\nENDSETS\n"
                        "DATA: A = 'v.1', 'w-2'; P = 1, 2; ENDDATA\n"
                        "MAX = @SUM(A(i): P(i)*X(i));\nEND\n")
        analyze(m2)

    def test_alias_members_rejected(self):
        m = make_model("MODEL:\nSETS:\n A /1, 1.0/: P, X;\nENDSETS\n"
                       "DATA: P = 1, 2; ENDDATA\n"
                       "MAX = @SUM(A(i): P(i)*X(i));\nEND\n")
        with self.assertRaises(ModelError):
            analyze(m)  # '1' 与 '1.0' 归一化后相同 → 别名

    def test_label_injective(self):
        m = make_model("MODEL:\nSETS:\n S /A, B, C, A_B/: P;\n L(S, S): Q, X;\nENDSETS\n"
                       "DATA: P = 1, 2, 3, 4;\n"
                       "Q = 1,1,1,1, 1,1,1,1, 1,1,1,1, 1,1,1,1; ENDDATA\n"
                       "MAX = @SUM(L(i,j): Q(i,j)*X(i,j));\n"
                       "@FOR(S(i): X(i,i) <= 1);\nEND\n")
        f = flatten(m)
        labels = list(f.labels.values())
        self.assertEqual(len(labels), len(set(labels)),
                         '标签必须单射（A_B 与 (A,B) 不能混淆）')


class TestOleConfinement(unittest.TestCase):
    """findings 1/2/14/15：@OLE 路径禁锢、范围校验、zip 炸弹预检。"""

    def _model_with_ole(self, ole_expr):
        text = ("MODEL:\nSETS:\n N /1..2/: P, X;\nENDSETS\n"
                "DATA:\n P = " + ole_expr + ";\nENDDATA\n"
                "MAX = @SUM(N(i): P(i)*X(i));\n@SUM(N(i): X(i)) <= 1;\nEND\n")
        d = tempfile.mkdtemp()
        p = os.path.join(d, 'm.lng')
        with open(p, 'w', encoding='utf-8') as fp:
            fp.write(text)
        from lingo2x.parser import parse_file
        return parse_file(p), d

    def test_dotdot_escape_rejected(self):
        m, d = self._model_with_ole("@OLE('../evil.xlsx')")
        with self.assertRaises(ModelError):
            resolve_external(m, d)

    def test_unc_path_rejected(self):
        m, d = self._model_with_ole("@OLE('\\\\\\\\evilhost\\\\share\\\\x.xlsx')")
        with self.assertRaises(ModelError):
            resolve_external(m, d)

    def test_legit_ole_read_passes(self):
        # 合法对照：仓库里的 Omega 模型 + xlsx 应该正常读取
        from lingo2x.parser import parse_file
        m = parse_file(os.path.join(ROOT, 'tests', 'github', 'Omega.lng'))
        resolve_external(m, os.path.join(ROOT, 'tests', 'github'))
        self.assertIn('PROFIT', m.data)
        self.assertEqual(m.sets['PRODUITS'].members, ['1', '2', '3'])

    def test_zipbomb_rejected(self):
        d = tempfile.mkdtemp()
        p = os.path.join(d, 'bomb.xlsx')
        with zipfile.ZipFile(p, 'w', zipfile.ZIP_DEFLATED) as zf:
            zf.writestr('xl/worksheets/sheet1.xml', '0' * (50 * 1024 * 1024))
        with self.assertRaises(ModelError):
            resolve_mod._check_zip_bomb(p)

    def test_bad_zip_rejected_cleanly(self):
        d = tempfile.mkdtemp()
        p = os.path.join(d, 'notzip.xlsx')
        with open(p, 'w') as fp:
            fp.write('not a zip')
        with self.assertRaises(ModelError):
            resolve_mod._check_zip_bomb(p)


class TestDosGuards(unittest.TestCase):
    """findings 5/11/12：规模上限、递归深度、CALC 下标除零。"""

    def test_range_cap(self):
        with self.assertRaises(ParseError):
            make_model("MODEL:\nSETS:\n A /1..200000/: X;\nENDSETS\n"
                       "MAX = @SUM(A(i): X(i));\nEND\n")

    def test_instance_cap(self):
        m = make_model("MODEL:\nSETS:\n A /1..100000/:;\n B /1..100000/:;\n"
                       " L(A, B): X;\nENDSETS\n"
                       "MAX = @SUM(L(i,j): X(i,j));\nEND\n")
        with self.assertRaises(InstantiateError):
            flatten(m)

    def test_recursion_guard(self):
        deep = '(' * 5000 + '1' + ')' * 5000
        with self.assertRaises(ParseError):
            make_model(f"MODEL:\nMAX = {deep};\nx <= 1;\nEND\n")

    def test_calc_idx_divzero_is_model_error(self):
        # i=1 时 (i-1)=0：旧实现用字典求值会顺带计算 a/0 抛 ZeroDivisionError
        m = make_model("MODEL:\nSETS:\n N /1..2/: A, B, X;\nENDSETS\n"
                       "DATA: A = 5, 6; ENDDATA\n"
                       "CALC:\n @FOR(N(i): B(i + (i-1)*0) = A(i));\nENDCALC\n"
                       "MAX = @SUM(N(i): B(i)*X(i));\n@SUM(N(i): X(i)) <= 1;\nEND\n")
        resolve_external(m, tempfile.mkdtemp())
        f = flatten(m)
        # B 应被算成 5,6；目标是 B*X → obj 里 X 的系数
        self.assertEqual(f.obj[('X', ('1',))], 5.0)
        self.assertEqual(f.obj[('X', ('2',))], 6.0)

    def test_calc_proc_cycle_rejected(self):
        m = make_model("MODEL:\nSETS:\n N /1..2/: A, X;\nENDSETS\n"
                       "DATA: A = 1, 2; ENDDATA\n"
                       "procedure p1:\n p2;\nendprocedure\n"
                       "procedure p2:\n p1;\nendprocedure\n"
                       "CALC:\n p1;\nENDCALC\n"
                       "MAX = @SUM(N(i): A(i)*X(i));\nEND\n")
        with self.assertRaises(ModelError):
            resolve_external(m, tempfile.mkdtemp())


class TestOutputInjection(unittest.TestCase):
    """findings 4/10：输出转义与生成文件头部注释分隔符。"""

    def test_gmpl_header_comment_neutralized(self):
        m = make_model("MODEL:\nSETS:\n N /1/: P, X;\nENDSETS\n"
                       "DATA: P = 1; ENDDATA\nMAX = P(1)*X(1);\nEND\n")
        m.source = 'evil*/ @ole(1);\n/*'
        out = gmpl.emit(m)
        first = out.split('\n')[0]
        self.assertTrue(first.endswith('*/'))
        self.assertNotIn('evil*/', out)

    def test_lp_header_comment_neutralized(self):
        m = make_model("MODEL:\nSETS:\n N /1/: P, X;\nENDSETS\n"
                       "DATA: P = 1; ENDDATA\nMAX = P(1)*X(1);\nEND\n")
        m.source = 'evil*\\\nMinimize'
        out = lp.emit(m)
        first = out.split('\n')[0]
        self.assertTrue(first.endswith('*\\'))
        self.assertNotIn('evil*\\', out)
        self.assertNotIn('Minimize\n obj', first)


class TestCliErrors(unittest.TestCase):
    """findings 4/13：顶层错误 containment，不抛 traceback。"""

    def test_cli_clean_error_no_traceback(self):
        d = tempfile.mkdtemp()
        p = os.path.join(d, 'bad.lng')
        with open(p, 'w', encoding='utf-8') as fp:
            fp.write("MODEL:\nMAX = @SUM(NOSUCH(i): X(i));\nEND\n")
        r = subprocess.run([sys.executable, '-m', 'lingo2x', p, '-b', 'gmpl', '-o', '-'],
                           capture_output=True, cwd=ROOT,
                           env={**os.environ, 'PYTHONIOENCODING': 'utf-8'})
        self.assertEqual(r.returncode, 1)
        err = r.stderr.decode('utf-8', errors='replace')
        self.assertIn('错误', err)
        self.assertNotIn('Traceback', err)

    def test_cli_legit_still_works(self):
        r = subprocess.run([sys.executable, '-m', 'lingo2x',
                            os.path.join(ROOT, 'examples', 'transportation.lgo'),
                            '-b', 'lp', '-o', '-'],
                           capture_output=True, cwd=ROOT,
                           env={**os.environ, 'PYTHONIOENCODING': 'utf-8'})
        self.assertEqual(r.returncode, 0)
        self.assertIn('Minimize', r.stdout.decode('utf-8', errors='replace'))


if __name__ == '__main__':
    unittest.main()
