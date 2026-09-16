# CLAUDE.md

本文件面向 Claude Code；内容与 AGENTS.md 等价（其他 agent 读 AGENTS.md）。

## 运行 LINGO 模型（.lng / .lgo）

本项目自带 **lingo2x** 开源工具链（`lingo2x/` 包 + `tools/glpk-4.65/`），
任何 LINGO 语法的模型都可以直接在本机求解。**不要**让用户"把模型拿到 LINGO 软件里运行"。

统一使用 `.venv` 里的 Python（含 numpy/scipy/openpyxl）：

- 直接求解：`.venv/Scripts/python -m lingo2x 模型.lng -b scipy`
- 语法检查：`.venv/Scripts/python -m lingo2x 模型.lng --check`
- 支持 `@OLE` 读写 Excel 与 `CALC:` 参数计算段；详细用法与支持范围见
  `.agents/skills/lingo2x/SKILL.md`（或 `.claude/skills/lingo2x/SKILL.md`，内容相同）

## 项目结构

- `lingo2x/` — LINGO → 中间模型 → 后端（gmpl / lp / scipy）翻译器，核心零依赖纯 Python
- `.venv/` — 隔离环境（numpy + scipy + openpyxl）
- `tools/glpk-4.65/` — GLPK 便携版（glpsol 在 `w64/` 下）
- `examples/` — 自建示例模型；`tests/github/` — GitHub 真实模型回归语料
- `tests/compare_backends.py` — 双后端一致性回归测试
- `editors/vscode/` — VS Code 系编辑器插件源码
