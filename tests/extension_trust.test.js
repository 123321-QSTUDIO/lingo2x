// 扩展信任门回归测试（findings 0/3）：未信任工作区绝不 spawn 子进程。
// 用桩替换 vscode / child_process 模块后加载插件源码，直接跑 node 即可：
//   node tests/extension_trust.test.js
const Module = require('module');
const path = require('path');

const spawned = [];
const warnings = [];
let trusted = false;
let saveHandlers = {};
let commands = {};

const fakeDoc = {
  languageId: 'lingo',
  isDirty: false,
  uri: { scheme: 'file', fsPath: path.join(__dirname, 'm.lng') },
  save: async () => {},
};

const fakeVscode = {
  workspace: {
    get isTrusted() { return trusted; },
    getConfiguration: () => ({
      get: (k, fb) => fb,
      inspect: () => ({ globalValue: undefined, workspaceValue: 'C:\\evil\\python.exe',
                         workspaceFolderValue: 'C:\\evil2\\python.exe', defaultValue: '' }),
    }),
    getWorkspaceFolder: () => null,
    onDidSaveTextDocument: h => { saveHandlers.save = h; return { dispose() {} }; },
    onDidOpenTextDocument: h => { saveHandlers.open = h; return { dispose() {} }; },
    onDidCloseTextDocument: () => ({ dispose() {} }),
    openTextDocument: async () => fakeDoc,
  },
  window: {
    createOutputChannel: () => ({ append() {}, appendLine() {}, show() {} }),
    createDiagnosticCollection: () => ({ set() {}, delete() {}, dispose() {} }),
    showWarningMessage: m => { warnings.push(m); return Promise.resolve(); },
    showTextDocument: async () => {},
    get activeTextEditor() { return { document: fakeDoc }; },
    visibleTextEditors: [{ document: fakeDoc }],
  },
  languages: {
    createDiagnosticCollection: () => ({ set() {}, delete() {}, dispose() {} }),
  },
  commands: {
    registerCommand: (id, fn) => { commands[id] = fn; return { dispose() {} }; },
  },
  Diagnostic: class { constructor(range, msg, sev) { this.msg = msg; } },
  Range: class { constructor(...a) { this.a = a; } },
  DiagnosticSeverity: { Error: 0 },
  ViewColumn: { Beside: 2 },
};

// languages/window 的 createDiagnosticCollection 取其一即可（上面 window 里的用不到）
delete fakeVscode.window.createDiagnosticCollection;

const fakeCp = {
  spawn: (...a) => { spawned.push(['spawn', ...a]); throw new Error('不应被调用'); },
  execFile: (...a) => { spawned.push(['execFile', ...a]); throw new Error('不应被调用'); },
};

const origLoad = Module._load;
Module._load = function (request, parent, isMain) {
  if (request === 'vscode') return fakeVscode;
  if (request === 'child_process') return fakeCp;
  return origLoad.apply(this, arguments);
};

const ext = require(path.join(__dirname, '..', 'editors', 'vscode', 'extension.js'));
const ctx = { subscriptions: [] };
ext.activate(ctx);

(async () => {
  // 1) 未信任：打开文件触发自动检查 → 不得执行
  trusted = false;
  saveHandlers.open(fakeDoc);
  // 2) 未信任：用户主动点求解 → 拒绝并告警
  await commands['lingo2x.solveScipy']();
  if (spawned.length !== 0) {
    console.error('FAIL: 未信任工作区仍然执行了子进程', spawned);
    process.exit(1);
  }
  if (warnings.length === 0) {
    console.error('FAIL: 拒绝执行时未给出告警');
    process.exit(1);
  }
  console.log('PASS: 未信任工作区拒绝一切执行（含自动检查），并给出告警');

  // 3) 已信任：求解应走到 spawn（桩会 throw，捕获即证明走到了执行路径）。
  //    信任工作区后尊重工作区级设置是 VS Code 信任模型的既有语义
  //   （tasks/debugger 同理），漏洞边界在"未信任时执行"，此处只验证恢复执行。
  trusted = true;
  warnings.length = 0;
  try {
    await commands['lingo2x.solveScipy']();
  } catch { /* 桩抛出 */ }
  if (spawned.length === 0) {
    console.error('FAIL: 信任工作区下求解未执行');
    process.exit(1);
  }
  console.log('PASS: 信任工作区恢复正常执行');
  console.log('全部通过');
})().catch(e => { console.error('FAIL:', e); process.exit(1); });
