// lingo2x VS Code 插件：语法检查（波浪线）+ 一键求解/翻译。
// 依赖：工作区根目录下可 import 的 lingo2x 包（通过 PYTHONPATH 注入项目根）。
const vscode = require('vscode');
const cp = require('child_process');
const fs = require('fs');
const path = require('path');

let output;
let diagnostics;

function isLingo(doc) {
  return doc && doc.languageId === 'lingo' && doc.uri.scheme === 'file';
}

function cfg(key, fallback) {
  return vscode.workspace.getConfiguration('lingo2x').get(key, fallback);
}

function findProjectRoot(filePath) {
  // 从文件所在目录向上找包含 lingo2x 包的目录（兼容"只打开单个文件"的场景）
  let dir = path.dirname(filePath);
  for (let i = 0; i < 6; i++) {
    if (fs.existsSync(path.join(dir, 'lingo2x', '__init__.py'))) return dir;
    const up = path.dirname(dir);
    if (up === dir) break;
    dir = up;
  }
  return null;
}

function projectRoot(doc) {
  const ws = vscode.workspace.getWorkspaceFolder(doc.uri);
  if (ws && fs.existsSync(path.join(ws.uri.fsPath, 'lingo2x', '__init__.py'))) {
    return ws.uri.fsPath;
  }
  return findProjectRoot(doc.uri.fsPath)
    || (ws ? ws.uri.fsPath : path.dirname(doc.uri.fsPath));
}

function pythonPath(root) {
  const fromCfg = cfg('pythonPath', '');
  if (fromCfg) return fromCfg;
  const venv = path.join(root, '.venv', 'Scripts', 'python.exe');
  if (fs.existsSync(venv)) return venv;
  return 'python';
}

function glpsolPath(root) {
  const fromCfg = cfg('glpsolPath', '');
  if (fromCfg) return fromCfg;
  const local = path.join(root, 'tools', 'glpk-4.65', 'w64', 'glpsol.exe');
  if (fs.existsSync(local)) return local;
  return 'glpsol';
}

function run(cmd, args, cwd, encoding) {
  // encoding 默认 utf-8（Python 端已强制 PYTHONIOENCODING=utf-8）；
  // glpsol 等原生程序在中文 Windows 上输出 GBK，调用方传 'gbk'。
  let dec;
  try {
    dec = new TextDecoder(encoding || 'utf-8');
  } catch {
    dec = new TextDecoder('utf-8');
  }
  return new Promise(resolve => {
    output.appendLine(`> ${cmd} ${args.join(' ')}`);
    const p = cp.spawn(cmd, args, {
      cwd,
      env: { ...process.env, PYTHONPATH: root4import(cwd), PYTHONIOENCODING: 'utf-8' },
    });
    p.stdout.on('data', d => output.append(dec.decode(d, { stream: true })));
    p.stderr.on('data', d => output.append(dec.decode(d, { stream: true })));
    p.on('error', e => {
      output.appendLine(`启动失败: ${e.message}`);
      resolve(-1);
    });
    p.on('close', code => {
      output.append(dec.decode());
      output.appendLine(`（退出码 ${code}）`);
      resolve(code);
    });
  });
}

// 从 glpsol 的 -o 报告里提取最优值和非零变量，追加到输出面板
function printGlpsolSolution(solFile) {
  let text;
  try {
    text = fs.readFileSync(solFile, 'utf-8');
  } catch {
    return;
  }
  const obj = text.match(/Objective:\s*\S+\s*=\s*([-\d.eE+]+)/);
  if (obj) output.appendLine(`\n最优值: ${Number(obj[1])}`);
  const lines = text.split(/\r?\n/);
  let inCols = false;
  const rows = [];
  for (const ln of lines) {
    if (/Column name/.test(ln)) { inCols = true; continue; }
    if (inCols && /Row name/.test(ln)) break;
    if (!inCols) continue;
    const m = ln.match(/^\s*\d+\s+(\S+)\s+\S+\s+([-\d.eE+]+)/);
    if (m && Math.abs(Number(m[2])) > 1e-9) rows.push(`  ${m[1]} = ${Number(m[2])}`);
  }
  if (rows.length) {
    output.appendLine('非零变量:');
    rows.forEach(r => output.appendLine(r));
  }
}

function root4import(cwd) {
  // PYTHONPATH 里追加项目根，保证 python -m lingo2x 能 import
  return process.env.PYTHONPATH ? `${cwd}${path.delimiter}${process.env.PYTHONPATH}` : cwd;
}

// ---- 语法检查（静默运行，结果画成波浪线）----
function check(doc) {
  if (doc.isDirty) return; // 只查已保存到磁盘的内容
  const root = projectRoot(doc);
  cp.execFile(
    pythonPath(root),
    ['-m', 'lingo2x', doc.uri.fsPath, '--check'],
    {
      cwd: root,
      env: { ...process.env, PYTHONPATH: root4import(root), PYTHONIOENCODING: 'utf-8' },
    },
    (err, stdout, stderr) => {
      const out = (stdout || '').toString();
      const list = [];
      if (err) {
        const m = out.match(/^(.+):(\d+):(\d+): (.+)$/m);
        if (m) {
          const line = Math.max(0, parseInt(m[2], 10) - 1);
          const col = Math.max(0, parseInt(m[3], 10) - 1);
          list.push(new vscode.Diagnostic(
            new vscode.Range(line, col, line, col + 1),
            m[4], vscode.DiagnosticSeverity.Error));
        } else {
          list.push(new vscode.Diagnostic(
            new vscode.Range(0, 0, 0, 1),
            out.trim() || (stderr || '').toString().trim() || '语法检查失败',
            vscode.DiagnosticSeverity.Error));
        }
      }
      diagnostics.set(doc.uri, list);
    }
  );
}

// ---- 命令 ----
async function activeLingoDoc() {
  // 焦点在 Agent 面板/输出面板等非文本编辑器时，activeTextEditor 会是空，
  // 此时回退到所有可见编辑器中找第一个 LINGO 文档
  let doc = vscode.window.activeTextEditor?.document;
  if (!isLingo(doc)) {
    const alt = vscode.window.visibleTextEditors.find(e => isLingo(e.document));
    if (alt) doc = alt.document;
  }
  if (!isLingo(doc)) {
    vscode.window.showWarningMessage('请先打开一个 .lng / .lgo 文件');
    return null;
  }
  await doc.save();
  return doc;
}

async function solve(backend) {
  const doc = await activeLingoDoc();
  if (!doc) return;
  const root = projectRoot(doc);
  output.show(true);
  output.appendLine(`\n==== 求解（${backend}） ${path.basename(doc.uri.fsPath)} ====`);
  await run(pythonPath(root), ['-m', 'lingo2x', doc.uri.fsPath, '-b', backend], root);
}

async function solveGlpsol() {
  const doc = await activeLingoDoc();
  if (!doc) return;
  const root = projectRoot(doc);
  const file = doc.uri.fsPath;
  const mod = file.replace(/\.(lng|lgo)$/i, '') + '.mod';
  const sol = file.replace(/\.(lng|lgo)$/i, '') + '.sol.txt';
  output.show(true);
  output.appendLine(`\n==== 求解（glpsol） ${path.basename(file)} ====`);
  const rc = await run(pythonPath(root), ['-m', 'lingo2x', file, '-b', 'gmpl', '-o', mod], root);
  if (rc !== 0) return;
  const rc2 = await run(glpsolPath(root), ['-m', mod, '-o', sol], root, 'gbk');
  if (rc2 === 0) printGlpsolSolution(sol);
}

async function translate(backend) {
  const doc = await activeLingoDoc();
  if (!doc) return;
  const root = projectRoot(doc);
  const file = doc.uri.fsPath;
  const out = file.replace(/\.(lng|lgo)$/i, '') + (backend === 'gmpl' ? '.mod' : '.lp');
  const rc = await run(pythonPath(root), ['-m', 'lingo2x', file, '-b', backend, '-o', out], root);
  if (rc === 0) {
    const d = await vscode.workspace.openTextDocument(out);
    vscode.window.showTextDocument(d, { preview: true, viewColumn: vscode.ViewColumn.Beside });
  }
}

function activate(context) {
  output = vscode.window.createOutputChannel('lingo2x');
  diagnostics = vscode.languages.createDiagnosticCollection('lingo2x');
  context.subscriptions.push(output, diagnostics);

  context.subscriptions.push(
    vscode.commands.registerCommand('lingo2x.solveScipy', () => solve('scipy')),
    vscode.commands.registerCommand('lingo2x.solveGlpsol', solveGlpsol),
    vscode.commands.registerCommand('lingo2x.toGmpl', () => translate('gmpl')),
    vscode.commands.registerCommand('lingo2x.toLp', () => translate('lp')),
  );

  const trigger = doc => {
    if (isLingo(doc) && cfg('checkOnSave', true)) check(doc);
  };
  context.subscriptions.push(
    vscode.workspace.onDidSaveTextDocument(trigger),
    vscode.workspace.onDidOpenTextDocument(trigger),
    vscode.workspace.onDidCloseTextDocument(doc => diagnostics.delete(doc.uri)),
  );
  if (vscode.window.activeTextEditor) trigger(vscode.window.activeTextEditor.document);
}

function deactivate() {}

module.exports = { activate, deactivate };
