# lingo2x — LINGO 开源工具链 VS Code 插件

给 `.lng` / `.lgo` 文件提供：

- **语法高亮**（含 `@SUM`/`@FOR` 函数、`#LE#` 运算符、`!注释;`、约束标签 `[name]`）
- **代码片段**：输入 `model` / `sets` / `data` / `for` / `sum` / `sumif` / `bin` / `transport` 后按 Tab
- **保存时语法检查**：错误以波浪线标出（精确到行列），基于 `python -m lingo2x --check`
- **一键求解/翻译**（编辑器右上角按钮或右键菜单）：
  - `lingo2x: 求解（scipy/HiGHS）` — 直接求解并打印最优解
  - `lingo2x: 求解（GLPK/glpsol）` — 翻译成 `.mod` 后调 glpsol
  - `lingo2x: 翻译为 GMPL / LP` — 生成并并排打开结果文件

## 配置

| 设置项 | 默认行为 |
| --- | --- |
| `lingo2x.pythonPath` | 留空 → 优先 `<项目>/.venv/Scripts/python.exe`，再退回 PATH 的 `python` |
| `lingo2x.glpsolPath` | 留空 → 优先 `<项目>/tools/glpk-4.65/w64/glpsol.exe`，再退回 PATH 的 `glpsol` |
| `lingo2x.checkOnSave` | `true` |

要求：项目根目录下可导入 `lingo2x` 包（插件会把工作区根目录注入 `PYTHONPATH`）。
