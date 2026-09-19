---
name: lingo2x
description: >-
  需要运行、调试或验证 LINGO 语法（.lng/.lgo）的数学规划模型时使用。本机已安装
  lingo2x 开源工具链，可直接翻译并求解 LINGO 模型（LP / MIP / 0-1 规划）。
  绝对不要让用户"把模型拿到 LINGO 软件里运行"——用本 skill 的命令直接跑。
---

# lingo2x：在本机直接运行 LINGO 模型

流水线：LINGO 源码 → lingo2x 解析 → 中间模型 → 开源求解器后端（scipy/HiGHS、GLPK/glpsol）。

## 定位工具链

工具链是一个名为 `lingo2x` 的 Python 包。优先在当前工作区根目录找 `lingo2x/__init__.py`；
找不到时默认位于 `D:\奇妙项目\数学建模`。以下命令均在工具链根目录（即包含 `lingo2x/` 的目录）执行。

## 命令

统一使用项目 `.venv` 里的 Python（`@OLE` 依赖其中的 openpyxl）：

- **直接求解**（首选）：`.venv/Scripts/python -m lingo2x 模型.lng -b scipy`
  打印最优值和非零变量；加 `--all` 打印全部变量（含零值）；
  若模型含 `@OLE(...) = X` 写回语句，求解后自动写回 Excel。
  Linux/macOS 上把 `.venv/Scripts/python` 换成 `.venv/bin/python`。
- **语法检查**（只查错不求解，不加载 Excel，输出 `文件:行:列: 错误`）：
  `.venv/Scripts/python -m lingo2x 模型.lng --check`
- **翻译成 GMPL 用 glpsol 求解**：
  `.venv/Scripts/python -m lingo2x 模型.lng -b gmpl -o 模型.mod`，然后 `tools/glpk-4.65/w64/glpsol.exe -m 模型.mod`
- **生成通用 LP 文件**（CBC / HiGHS / SCIP 均可读）：`.venv/Scripts/python -m lingo2x 模型.lng -b lp`

## 支持的语法

`MODEL:/END`（可选）、`SETS:/ENDSETS`（基本集、派生集笛卡尔积、`/1..N/` 区间成员、
DATA 中定义成员）、`DATA:/ENDDATA`（多名字交错赋值）、`[name] MAX=/MIN=`、
线性约束（`<= >= =`，`#LE#` 系写法，`<`/`>` 按非严格处理）、
`@SUM`/`@FOR`（可省略下标走隐式下标；支持 `|` 条件过滤与 `#AND#/#OR#/#NOT#`；支持嵌套）、
`@BIN/@GIN/@FREE`、命名约束 `[name]`、下标算术（如 `X(i-1)`）、字面成员下标（如 `x(5,5)`）、
`^` 幂运算（仅限常数底数与常数指数，保持线性）、名字大小写不敏感、
注释 `!`（本行有分号到分号；否则下一行像散文则按多行注释延续到分号，像代码则到行尾）。

**防呆**：`@SUM`/`@FOR` 的下标若与外层下标重名会直接报错（内层遮蔽外层会静默改变
求和范围），遇到时改名（如 `k1`）或用嵌套写法即可。

外部数据与计算段：

- `@OLE('文件.xlsx'[, '区域'])` 读取 Excel 命名区域/单元格区域（行主序），可给集合成员和参数赋值。
  安全限制：xlsx 必须与模型文件在同一目录（拒绝 `..` 逃逸、绝对路径越界和 UNC 路径），
  并有 zip 炸弹预检。区域引用写错时会提示"找不到命名区域"并列出现有区域名
- `@OLE('文件.xlsx', '区域') = X;` 求解后把结果写回 Excel（仅 scipy 求解路径生效，同样受目录禁锢）
- `CALC: ... ENDCALC` 与 `procedure 名: ... endprocedure`：求解前的参数计算，
  支持赋值、`@FOR` 循环赋值、过程调用、`@SQRT/@ABS`（距离等参数现算）；
  `@TEXT/@TABLE/@WRITE` 解析后忽略。CALC 中只允许参数参与运算（引用决策变量会报错）

## 不支持（会明确报错，按报错提示改写即可）

- `@POINTER` / `@FILE` 等其他外部数据源
- 非线性表达式（变量×变量等）→ 本工具只支持线性模型
- 派生集的 `|` 成员过滤（如 `LOCATION(P,P) | &1 #LE# &2`）

## 验证

求解出结果后，如需交叉验证，运行 `.venv/Scripts/python tests/compare_backends.py`
（对 tests/github/ 下全部模型做 glpsol 与 scipy 双后端比对）。
