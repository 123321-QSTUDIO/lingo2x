# lingo2x

**用 LINGO 语法写数学规划模型，用开源求解器跑。** 不用装 LINGO。

> 项目初衷：不想装老师发的来路不明的 LINGO 11 破解版，于是自己写了一个。
> 反正数学建模要用的也就那几样：集合、求和、循环、0-1 变量。

```
LINGO 源码 (.lng/.lgo) → 解析器 → 中间模型 (IR) → 可插拔求解器后端
                                                  ├─ scipy/HiGHS（直接求解）
                                                  ├─ GMPL → glpsol（GLPK）
                                                  └─ LP 文件（CBC / HiGHS / SCIP 通吃）
```

纯 Python 实现核心（零依赖），Windows / Linux / macOS 都能跑。

## 特性

- **LINGO 语法子集**：`SETS`/`DATA`、`@SUM`/`@FOR`（含 `|` 条件过滤、嵌套、隐式下标）、
  `@BIN`/`@GIN`/`@FREE`、命名约束 `[name]`、下标算术、区间成员 `/1..N/`、大小写不敏感
- **@OLE 读写 Excel**：`COST = @OLE('data.xlsx')` 读数据；`@OLE('out.xlsx','X') = X;` 求解后写回
- **CALC 段**：`CALC:`/`procedure` 求解前的参数计算
- **三个后端**：scipy（HiGHS）直解 / 生成 GMPL 给 glpsol / 生成通用 LP 文件
- **编辑器插件**：语法高亮、代码片段、保存时语法检查（波浪线）、一键求解。
  VS Code 及所有 VS Code 系 AI IDE（Antigravity / Cursor / Windsurf / Trae …）通用
- **Agent skill**：标准 SKILL.md 格式，Antigravity IDE/CLI、Claude Code、Kimi Code 等
  各类 agent 装上后，看到 .lng 会直接用它求解，不会叫你"拿去 LINGO 里跑"

## 快速开始

```bash
# 准备隔离环境（scipy 后端与 @OLE 所需）
python -m venv .venv
.venv/Scripts/python -m pip install numpy scipy openpyxl   # Windows
# .venv/bin/python -m pip install numpy scipy openpyxl     # Linux/macOS

# 写一个模型（examples/transportation.lgo），然后直接求解
.venv/Scripts/python -m lingo2x examples/transportation.lgo -b scipy
```

输出：

```
状态: Optimization terminated successfully. (HiGHS Status 7: Optimal)
最优值: 885
  X_W1_C2 = 40
  X_W1_C3 = 20
  X_W2_C1 = 35
  X_W2_C3 = 10
```

其他用法：

```bash
python -m lingo2x 模型.lng --check          # 只做语法检查（输出 文件:行:列: 错误）
python -m lingo2x 模型.lng -b gmpl          # 生成 .mod（GMPL），配 glpsol 用
python -m lingo2x 模型.lng -b lp            # 生成 .lp，CBC/HiGHS/SCIP 都能读
```

想用 GLPK 求解器本体：下载 [winglpk](https://sourceforge.net/projects/winglpk/) 解压到
`tools/glpk-4.65/`（本仓库 `.gitignore` 已排除），然后
`tools/glpk-4.65/w64/glpsol.exe -m 模型.mod`。

## 一个完整模型长这样

```
MODEL:
SETS:
    WAREHOUSES /W1, W2/: CAP;
    CUSTOMERS  /C1, C2, C3/: DEMAND;
    LINKS(WAREHOUSES, CUSTOMERS): COST, X;
ENDSETS
DATA:
    CAP    = 60, 55;
    DEMAND = 35, 40, 30;
    COST   = 8, 6, 10,
             9, 12, 13;
ENDDATA
MIN = @SUM(LINKS(I, J): COST(I, J) * X(I, J));
@FOR(WAREHOUSES(I): @SUM(CUSTOMERS(J): X(I, J)) <= CAP(I));
@FOR(CUSTOMERS(J):  @SUM(WAREHOUSES(I): X(I, J)) >= DEMAND(J));
END
```

## 支持 / 不支持

| 支持 | 不支持（会明确报错） |
| --- | --- |
| 线性 LP / MIP / 0-1 规划 | 非线性表达式（变量×变量） |
| `@SUM`/`@FOR` 的 `\|` 条件过滤（`#AND#` 等） | 派生集 `\|` 成员过滤（`&1 #LE# &2`） |
| `@OLE` 读写 Excel（需 openpyxl） | `@POINTER` / `@FILE` 外部数据 |
| `CALC:` / `procedure` 参数计算 | `@PPOISCDF` 等概率分布函数 |
| 隐式下标、下标算术 `X(i-1)` | `@BND`（暂以变量默认界代替） |

## 编辑器插件（VS Code 系 IDE 通用）

`editors/vscode/` 是一个标准 VS Code 插件，**VS Code 及所有基于它的 AI IDE 都能装**
（Antigravity、Cursor、Windsurf、Trae …）：

- `.lng`/`.lgo` 语法高亮、片段（`model` / `transport` / `sumif` ...）
- 保存时语法检查，错误精确到行列
- 标题栏一键求解（scipy/HiGHS 或 GLPK/glpsol）

安装：打包成 vsix（本质是 zip，结构见仓库 `editors/vscode/`）后用各 IDE 的 CLI 安装：

```bash
code --install-extension lingo2x-0.1.0.vsix              # VS Code
antigravity-ide --install-extension lingo2x-0.1.0.vsix   # Antigravity
cursor --install-extension lingo2x-0.1.0.vsix            # Cursor
windsurf --install-extension lingo2x-0.1.0.vsix          # Windsurf
trae --install-extension lingo2x-0.1.0.vsix              # Trae
```

也可以把 `editors/vscode/` 整个目录复制到对应 IDE 的扩展目录后重载窗口
（VS Code 是 `~/.vscode/extensions/lingo2x-0.1.0`，各 IDE 换成自己的目录）。

## Agent skill（给 IDE / CLI 里的 AI agent 用）

`.agents/skills/lingo2x/SKILL.md` 是标准 SKILL.md 技能文件：告诉 agent 本项目可以
直接求解 LINGO 模型、用哪几条命令、支持到什么语法。装上之后，agent 看到 `.lng`
会直接求解，而不是让你"拿去 LINGO 里跑"。

把 `lingo2x` 这个 skill 目录复制到各 agent 的技能目录即可（本项目根目录已自带
项目级的 `.agents/skills/` 和 `.claude/skills/`）：

| Agent | 用户级（全局生效） | 项目级 |
| --- | --- | --- |
| Antigravity IDE | `~/.gemini/antigravity/skills/` | `.agents/skills/`（已自带） |
| Antigravity CLI（agy） | `~/.gemini/antigravity-cli/skills/` | `.agents/skills/`（已自带） |
| Claude Code | `~/.claude/skills/` | `.claude/skills/`（已自带） |
| Kimi Code | `~/.agents/skills/` | `.agents/skills/`（已自带） |

规则文件同理：`AGENTS.md` 被多数 agent 读取；**Claude Code 读的名字是 `CLAUDE.md`**
（项目根目录已备好，内容与 AGENTS.md 等价）。

## 测试

`tests/github/` 收录了 40 个 GitHub 上的真实 LINGO 模型（来自
[lingo_to_pyomo](https://github.com/Joaquim2805/lingo_to_pyomo) 的测试语料等）。
其中 26 个落在支持子集内，**26/26 在 glpsol 与 scipy/HiGHS 两条独立路径下结果完全一致**：

```bash
.venv/Scripts/python tests/compare_backends.py
```

其余 14 个属于明确不支持的特性（外部数据源缺失、非线性等），会给出清晰的报错而非静默出错。

## 目录结构

```
lingo2x/            翻译器核心（lexer / parser / IR / 实例化器 / 后端）
  backends/         gmpl、lp、scipy；在 backends/__init__.py 注册一行即可加新后端
examples/           示例模型（运输、背包、生产计划、CALC 演示）
tests/github/       真实模型回归语料（含 @OLE 测试用 xlsx）
editors/vscode/     编辑器插件源码
.agents/skills/     agent skill（SKILL.md 标准格式；.claude/skills/ 是同内容副本）
AGENTS.md           agent 规则文件（CLAUDE.md 是给 Claude Code 的等价副本）
```

## 加一个新求解器后端

在 `lingo2x/backends/` 里写个模块，实现 `emit(model) -> str`（文本后端）
或 `solve(model) -> dict`（直解后端），然后在 `backends/__init__.py` 的
`BACKENDS` 字典里登记一行。完事。

## License

MIT
