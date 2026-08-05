/**
 * Shared process helpers for setup scripts.
 */

import { spawnSync } from "node:child_process";

/**
 * @typedef {object} RunResult
 * @property {number|null} status
 * @property {string} stdout
 * @property {string} stderr
 * @property {Error|null} error
 */

/**
 * @param {string} command
 * @param {string[]} [args]
 * @param {import('node:child_process').SpawnSyncOptions} [options]
 * @returns {RunResult}
 */
export function run(command, args = [], options = {}) {
  const result = spawnSync(command, args, {
    encoding: "utf8",
    shell: false,
    ...options,
  });

  return {
    status: result.status,
    stdout: (result.stdout ?? "").toString(),
    stderr: (result.stderr ?? "").toString(),
    error: result.error ?? null,
  };
}

/**
 * @param {string} command
 * @param {string[]} [args]
 * @param {import('node:child_process').SpawnSyncOptions} [options]
 * @returns {RunResult}
 */
export function runInherit(command, args = [], options = {}) {
  const result = spawnSync(command, args, {
    stdio: "inherit",
    shell: false,
    ...options,
  });

  return {
    status: result.status,
    stdout: "",
    stderr: "",
    error: result.error ?? null,
  };
}

/**
 * @param {string} command
 * @returns {boolean}
 */
export function commandExists(command) {
  const checker = process.platform === "win32" ? "where" : "which";
  const result = run(checker, [command]);
  return result.status === 0;
}

/**
 * @param {RunResult} result
 * @param {string} message
 */
export function assertOk(result, message) {
  if (result.error) {
    throw new Error(`${message}: ${result.error.message}`);
  }
  if (result.status !== 0) {
    const detail = (result.stderr || result.stdout || "").trim();
    throw new Error(detail ? `${message}\n${detail}` : message);
  }
}
