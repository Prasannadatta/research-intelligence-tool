/**
 * Create/reuse backend virtualenv and install Python dependencies.
 */

import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { assertOk, runInherit } from "./lib/run.js";
import * as log from "./lib/log.js";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(__dirname, "..");
const BACKEND = path.join(ROOT, "backend");

/**
 * @param {object} [options]
 * @param {boolean} [options.quiet]
 */
export function setupBackend(options = {}) {
  const node = process.execPath;
  const helper = path.join(__dirname, "backend-python.mjs");

  const venvPython =
    process.platform === "win32"
      ? path.join(BACKEND, ".venv", "Scripts", "python.exe")
      : path.join(BACKEND, ".venv", "bin", "python");
  const created = !fs.existsSync(venvPython);

  if (!options.quiet) {
    log.info("Ensuring backend/.venv exists (reuses existing environment).");
  }

  const ensure = runInherit(
    node,
    [helper, "--ensure-venv", "-c", "print('venv-ok')"],
    { cwd: ROOT },
  );
  assertOk(
    ensure,
    "Failed to create or reuse the backend Python virtual environment.",
  );

  if (!options.quiet) {
    log.success(created ? "Created backend/.venv" : "Reusing existing backend/.venv");
    log.info("Installing backend Python dependencies from requirements.txt");
  }

  const install = runInherit(
    node,
    [helper, "-m", "pip", "install", "-r", "requirements.txt"],
    { cwd: ROOT },
  );
  assertOk(install, "Failed to install backend Python dependencies.");
  if (!options.quiet) {
    log.success("Backend dependencies installed");
  }
}

const invokedDirectly =
  process.argv[1] &&
  path.resolve(process.argv[1]) === path.resolve(fileURLToPath(import.meta.url));

if (invokedDirectly) {
  try {
    setupBackend();
  } catch (error) {
    log.fail(error instanceof Error ? error.message : String(error));
    process.exit(1);
  }
}
