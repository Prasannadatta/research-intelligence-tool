/**
 * Initialize and verify the local SQLite database.
 */

import path from "node:path";
import { fileURLToPath } from "node:url";
import {
  ensureSqliteDirectory,
  loadDatabaseConfig,
} from "./lib/envConfig.js";
import { assertOk, runInherit } from "./lib/run.js";
import * as log from "./lib/log.js";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(__dirname, "..");

/**
 * @param {object} [options]
 * @param {ReturnType<typeof loadDatabaseConfig>} [options.dbConfig]
 */
export function setupDatabase(options = {}) {
  const dbConfig = options.dbConfig ?? loadDatabaseConfig();

  if (!dbConfig.databaseUrl) {
    throw new Error(
      [
        "DATABASE_URL is not configured.",
        "Copy backend/.env.example to backend/.env and set DATABASE_URL,",
        "then rerun: npm run setup",
      ].join("\n"),
    );
  }

  log.info(`Using database settings from ${dbConfig.source}`);

  if (!dbConfig.isSqlite) {
    throw new Error(
      [
        "This project currently uses SQLite only.",
        "Set DATABASE_URL to a sqlite+aiosqlite URL in backend/.env, for example:",
        "  DATABASE_URL=sqlite+aiosqlite:///./author_identity.db",
      ].join("\n"),
    );
  }

  try {
    const dir = ensureSqliteDirectory(dbConfig.sqlitePath);
    log.info(`SQLite directory ready: ${dir}`);
  } catch (error) {
    throw new Error(
      [
        "Could not create the SQLite database directory.",
        "Check write permissions for the database path.",
        error instanceof Error ? error.message : String(error),
      ].join("\n"),
    );
  }

  log.info("Running SQLite migrations and verification...");
  const helper = path.join(__dirname, "backend-python.mjs");
  const init = runInherit(
    process.execPath,
    [helper, "scripts/setup_database.py"],
    { cwd: ROOT },
  );
  assertOk(init, "SQLite database initialization failed.");
  log.success("SQLite database initialized and verified");
}

const invokedDirectly =
  process.argv[1] &&
  path.resolve(process.argv[1]) === path.resolve(fileURLToPath(import.meta.url));

if (invokedDirectly) {
  try {
    setupDatabase();
  } catch (error) {
    log.fail(error instanceof Error ? error.message : String(error));
    process.exit(1);
  }
}
