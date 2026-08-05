/**
 * Invoke the backend virtualenv Python when present, otherwise fall back to
 * the system Python. Avoids shell-specific activation commands.
 *
 * Pass --ensure-venv as the first argument to create backend/.venv when missing
 * (used by setup:backend).
 */
import { spawn, spawnSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const backendDir = path.join(__dirname, "..", "backend");
const isWindows = process.platform === "win32";
const venvDir = path.join(backendDir, ".venv");
const venvPython = path.join(
  venvDir,
  isWindows ? "Scripts" : "bin",
  isWindows ? "python.exe" : "python",
);

function systemPython() {
  return isWindows ? "python" : "python3";
}

function resolvePython() {
  if (fs.existsSync(venvPython)) {
    return venvPython;
  }
  return systemPython();
}

function ensureVenv() {
  if (fs.existsSync(venvPython)) {
    return;
  }
  const result = spawnSync(systemPython(), ["-m", "venv", ".venv"], {
    cwd: backendDir,
    stdio: "inherit",
    env: process.env,
  });
  if (result.status !== 0) {
    process.exit(result.status ?? 1);
  }
}

const rawArgs = process.argv.slice(2);
const shouldEnsureVenv = rawArgs[0] === "--ensure-venv";
const args = shouldEnsureVenv ? rawArgs.slice(1) : rawArgs;

if (shouldEnsureVenv) {
  ensureVenv();
}

const python = resolvePython();
const child = spawn(python, args, {
  cwd: backendDir,
  stdio: "inherit",
  env: process.env,
  shell: false,
});

child.on("exit", (code, signal) => {
  if (signal) {
    process.kill(process.pid, signal);
    return;
  }
  process.exit(code ?? 1);
});
