/**
 * First-time setup orchestrator (SQLite only).
 *
 * Usage: npm run setup
 */

import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { loadDatabaseConfig } from "./lib/envConfig.js";
import { setupDatabase } from "./setup-database.js";
import { assertOk, runInherit } from "./lib/run.js";
import * as log from "./lib/log.js";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(__dirname, "..");
const TOTAL_STEPS = 5;

function backendPythonHelper() {
  return path.join(__dirname, "backend-python.mjs");
}

function runBackendPython(args) {
  return runInherit(process.execPath, [backendPythonHelper(), ...args], {
    cwd: ROOT,
  });
}

function verifyPrerequisites(dbConfig) {
  const frontendPkg = path.join(ROOT, "frontend", "node_modules", "vite");
  const backendVenv =
    process.platform === "win32"
      ? path.join(ROOT, "backend", ".venv", "Scripts", "python.exe")
      : path.join(ROOT, "backend", ".venv", "bin", "python");

  if (!fs.existsSync(frontendPkg)) {
    throw new Error(
      "Frontend dependencies missing (vite not found in frontend/node_modules).",
    );
  }
  if (!fs.existsSync(backendVenv)) {
    throw new Error("Backend virtual environment missing at backend/.venv.");
  }
  if (!dbConfig.isSqlite || !dbConfig.databaseUrl) {
    throw new Error("SQLite DATABASE_URL is not configured.");
  }
  if (dbConfig.sqlitePath && !fs.existsSync(dbConfig.sqlitePath)) {
    throw new Error(
      `SQLite database file was not created: ${dbConfig.sqlitePath}`,
    );
  }
  log.success("Frontend, backend, and SQLite prerequisites verified");
}

/**
 * @param {object} [options]
 * @param {boolean} [options.skipRootInstall]
 */
export async function main(options = {}) {
  console.log("Research Intelligence Tool setup (SQLite)");

  const dbConfig = loadDatabaseConfig();

  if (!options.skipRootInstall) {
    log.step(1, TOTAL_STEPS, "Installing root dependencies");
    const rootInstall = runInherit("npm", ["install"], { cwd: ROOT });
    assertOk(rootInstall, "Failed to install root npm dependencies.");
    log.success("Root dependencies ready");
  } else {
    log.step(1, TOTAL_STEPS, "Installing root dependencies");
    log.info("Skipped (already installed for this run).");
  }

  log.step(2, TOTAL_STEPS, "Installing frontend dependencies");
  const frontendInstall = runInherit(
    "npm",
    ["--prefix", "frontend", "install"],
    { cwd: ROOT },
  );
  assertOk(frontendInstall, "Failed to install frontend dependencies.");
  log.success("Frontend dependencies ready");

  log.step(3, TOTAL_STEPS, "Creating Python environment");
  const ensure = runBackendPython(["--ensure-venv", "-c", "print('venv-ok')"]);
  assertOk(
    ensure,
    "Failed to create or reuse the backend Python virtual environment.",
  );
  log.success("Python virtual environment ready");

  log.step(4, TOTAL_STEPS, "Installing backend dependencies");
  const pip = runBackendPython([
    "-m",
    "pip",
    "install",
    "-r",
    "requirements.txt",
  ]);
  assertOk(pip, "Failed to install backend Python dependencies.");
  log.success("Backend dependencies ready");

  log.step(5, TOTAL_STEPS, "Initializing SQLite database");
  setupDatabase({ dbConfig });
  verifyPrerequisites(loadDatabaseConfig());

  console.log("\nSetup complete.");
  console.log("This project uses SQLite — no separate database install is required.");
  console.log("Start the application with:\n  npm run dev\n");
}

const invokedDirectly =
  process.argv[1] &&
  path.resolve(process.argv[1]) === path.resolve(fileURLToPath(import.meta.url));

if (invokedDirectly) {
  main().catch((error) => {
    log.fail(error instanceof Error ? error.message : String(error));
    process.exit(1);
  });
}
