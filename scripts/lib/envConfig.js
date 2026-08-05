/**
 * Read application database configuration without duplicating credentials.
 */

import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(__dirname, "..", "..");
const BACKEND_DIR = path.join(ROOT, "backend");
const BACKEND_ENV = path.join(BACKEND_DIR, ".env");
const BACKEND_ENV_EXAMPLE = path.join(BACKEND_DIR, ".env.example");

/**
 * @param {string} contents
 * @returns {Record<string, string>}
 */
export function parseEnvContents(contents) {
  /** @type {Record<string, string>} */
  const values = {};
  for (const rawLine of contents.split(/\r?\n/)) {
    const line = rawLine.trim();
    if (!line || line.startsWith("#")) continue;
    const eq = line.indexOf("=");
    if (eq <= 0) continue;
    const key = line.slice(0, eq).trim();
    let value = line.slice(eq + 1).trim();
    if (
      (value.startsWith('"') && value.endsWith('"')) ||
      (value.startsWith("'") && value.endsWith("'"))
    ) {
      value = value.slice(1, -1);
    }
    values[key] = value;
  }
  return values;
}

/**
 * @param {string} [envPath]
 * @returns {Record<string, string>}
 */
export function loadBackendEnv(envPath = BACKEND_ENV) {
  if (!fs.existsSync(envPath)) {
    return {};
  }
  return parseEnvContents(fs.readFileSync(envPath, "utf8"));
}

/**
 * @typedef {object} DatabaseConfig
 * @property {string} databaseUrl
 * @property {boolean} isSqlite
 * @property {string|null} sqlitePath
 * @property {string} source
 */

/**
 * Resolve the filesystem path for a SQLite SQLAlchemy URL.
 * Paths are interpreted relative to backend/ (Alembic / app cwd).
 *
 * @param {string} databaseUrl
 * @param {string} [backendDir]
 * @returns {{ isSqlite: boolean, sqlitePath: string|null, databaseUrl: string }}
 */
export function parseSqliteDatabaseUrl(databaseUrl, backendDir = BACKEND_DIR) {
  const normalized = databaseUrl.trim();
  const isSqlite = normalized.startsWith("sqlite");
  if (!isSqlite) {
    return { databaseUrl: normalized, isSqlite: false, sqlitePath: null };
  }

  // sqlite+aiosqlite:///relative/path.db
  // sqlite+aiosqlite:////absolute/path.db
  const withoutScheme = normalized.replace(/^sqlite(?:\+[a-z0-9]+)?:/i, "");
  let filePath = withoutScheme;
  if (filePath.startsWith("///")) {
    // Absolute on Unix: sqlite:/// /abs  -> three slashes + abs, or four for ////abs
    const rest = filePath.slice(3);
    if (rest.startsWith("/")) {
      filePath = rest;
    } else {
      filePath = rest;
    }
  } else if (filePath.startsWith("//")) {
    // sqlite://localhost/path ( uncommon )
    filePath = filePath.replace(/^\/\/[^/]*/, "") || filePath;
  }

  filePath = decodeURIComponent(filePath);
  if (!path.isAbsolute(filePath)) {
    filePath = path.resolve(backendDir, filePath);
  }

  return {
    databaseUrl: normalized,
    isSqlite: true,
    sqlitePath: filePath,
  };
}

/**
 * @param {{ envPath?: string, examplePath?: string, env?: NodeJS.ProcessEnv, backendDir?: string }} [options]
 * @returns {DatabaseConfig}
 */
export function loadDatabaseConfig(options = {}) {
  const envPath = options.envPath ?? BACKEND_ENV;
  const examplePath = options.examplePath ?? BACKEND_ENV_EXAMPLE;
  const processEnv = options.env ?? process.env;
  const backendDir = options.backendDir ?? BACKEND_DIR;

  /** @type {string|undefined} */
  let databaseUrl;
  /** @type {string} */
  let source = "missing";

  if (processEnv.DATABASE_URL) {
    databaseUrl = processEnv.DATABASE_URL;
    source = "process.env";
  } else {
    const fileEnv = loadBackendEnv(envPath);
    if (fileEnv.DATABASE_URL) {
      databaseUrl = fileEnv.DATABASE_URL;
      source = envPath;
    } else if (fs.existsSync(examplePath)) {
      const exampleEnv = loadBackendEnv(examplePath);
      if (exampleEnv.DATABASE_URL) {
        databaseUrl = exampleEnv.DATABASE_URL;
        source = `${examplePath} (fallback)`;
      }
    }
  }

  if (!databaseUrl) {
    return {
      databaseUrl: "",
      isSqlite: false,
      sqlitePath: null,
      source,
    };
  }

  const parsed = parseSqliteDatabaseUrl(databaseUrl, backendDir);
  return {
    ...parsed,
    source,
  };
}

/**
 * Ensure the parent directory for the SQLite file exists.
 * @param {string|null} sqlitePath
 * @param {{ mkdirSync?: typeof fs.mkdirSync }} [deps]
 */
export function ensureSqliteDirectory(sqlitePath, deps = {}) {
  if (!sqlitePath) {
    throw new Error("SQLite database path is missing.");
  }
  const dir = path.dirname(sqlitePath);
  const mkdirSync = deps.mkdirSync ?? fs.mkdirSync.bind(fs);
  mkdirSync(dir, { recursive: true });
  return dir;
}

export { BACKEND_ENV, BACKEND_DIR, ROOT };
