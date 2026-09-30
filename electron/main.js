// Desktop shell: starts the Python server on a free local port and shows it in a window.
// The server and UI are unchanged, so the browser and the app behave the same.
const { app, BrowserWindow, Menu, shell, dialog } = require('electron');
const { spawn } = require('child_process');
const http = require('http');
const net = require('net');
const fs = require('fs');
const os = require('os');
const path = require('path');

let server = null;
let win = null;

// Packaged: the gitroster package sits in resources/. Dev (npm start in electron/): it is one folder up.
const pkgParent = app.isPackaged ? process.resourcesPath : path.join(__dirname, '..');

function pythonCandidates() {
  if (process.env.GITROSTER_PYTHON) return [[process.env.GITROSTER_PYTHON]];
  return process.platform === 'win32' ? [['py', '-3'], ['python'], ['python3']] : [['python3'], ['python']];
}

function freePort() {
  return new Promise((resolve, reject) => {
    const s = net.createServer();
    s.once('error', reject);
    s.listen(0, '127.0.0.1', () => { const { port } = s.address(); s.close(() => resolve(port)); });
  });
}

function roots() {
  if (process.env.GITROSTER_ROOTS) return process.env.GITROSTER_ROOTS.split(path.delimiter);
  const projects = path.join(os.homedir(), 'projects');
  return [fs.existsSync(projects) ? projects : os.homedir()];
}

function trySpawn(candidates, args, env) {
  const [cmd, ...pre] = candidates[0];
  return new Promise((resolve, reject) => {
    const child = spawn(cmd, [...pre, ...args], { env, cwd: pkgParent, stdio: ['ignore', 'pipe', 'pipe'], windowsHide: true });
    let err = '';
    child.stderr.on('data', d => { err += d; });
    child.once('error', e => candidates.length > 1 ? resolve(trySpawn(candidates.slice(1), args, env)) : reject(e));
    child.once('spawn', () => resolve(Object.assign(child, { tail: () => err })));
  });
}

function waitFor(url, child, tries = 80) {
  return new Promise((resolve, reject) => {
    const attempt = n => {
      if (child.exitCode !== null) return reject(new Error('gitroster exited early:\n' + child.tail().slice(-600)));
      http.get(url, res => { res.resume(); resolve(); }).on('error', () => {
        n <= 0 ? reject(new Error('gitroster did not start in time')) : setTimeout(() => attempt(n - 1), 250);
      });
    };
    attempt(tries);
  });
}

async function start() {
  const port = await freePort();
  const env = { ...process.env, PYTHONPATH: pkgParent + path.delimiter + (process.env.PYTHONPATH || ''), PYTHONUTF8: '1' };
  server = await trySpawn(pythonCandidates(), ['-m', 'gitroster', '--port', String(port), ...roots()], env);
  const url = `http://127.0.0.1:${port}`;
  await waitFor(url, server);
  return url;
}

function stop() { if (server && server.exitCode === null) server.kill(); server = null; }

async function createWindow() {
  win = new BrowserWindow({
    width: 1100, height: 820, title: 'gitroster', backgroundColor: '#111111',
    webPreferences: { contextIsolation: true, nodeIntegration: false, sandbox: true },
  });
  try {
    const url = await start();
    // Only our own page stays in the window; everything else opens in the real browser.
    const external = (e, u) => { if (!u.startsWith(url)) { e.preventDefault(); shell.openExternal(u); } };
    win.webContents.on('will-navigate', external);
    win.webContents.setWindowOpenHandler(({ url: u }) => { shell.openExternal(u); return { action: 'deny' }; });
    await win.loadURL(url);
  } catch (e) {
    dialog.showErrorBox('gitroster could not start',
      `${e.message}\n\nInstall Python 3.9+ (python.org), or set GITROSTER_PYTHON to its path.`);
    app.quit();
  }
}

if (!app.requestSingleInstanceLock()) app.quit();
app.on('second-instance', () => { if (win) { if (win.isMinimized()) win.restore(); win.focus(); } });
app.whenReady().then(() => {
  Menu.setApplicationMenu(Menu.buildFromTemplate([
    ...(process.platform === 'darwin' ? [{ role: 'appMenu' }] : []),
    { role: 'editMenu' }, { role: 'viewMenu' }, { role: 'windowMenu' },
  ]));
  createWindow();
});
app.on('window-all-closed', () => app.quit());
app.on('before-quit', stop);
process.on('exit', stop);
for (const sig of ['SIGTERM', 'SIGINT', 'SIGHUP']) process.on(sig, () => { stop(); app.exit(0); });
