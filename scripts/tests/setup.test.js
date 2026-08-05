import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";
import {
  ensureSqliteDirectory,
  loadDatabaseConfig,
  parseEnvContents,
  parseSqliteDatabaseUrl,
} from "../lib/envConfig.js";
import { assertOk } from "../lib/run.js";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(__dirname, "..", "..");
const PACKAGE_JSON = path.join(ROOT, "package.json");

test("parseEnvContents ignores comments and blank lines", () => {
  const values = parseEnvContents(
    "# comment\n\nDATABASE_URL=sqlite+aiosqlite:///./author_identity.db\nFOO=bar\n",
  );
  assert.equal(
    values.DATABASE_URL,
    "sqlite+aiosqlite:///./author_identity.db",
  );
  assert.equal(values.FOO, "bar");
});

test("parseSqliteDatabaseUrl resolves relative SQLite paths under backend/", () => {
  const backendDir = path.join(os.tmpdir(), "rit-backend");
  const parsed = parseSqliteDatabaseUrl(
    "sqlite+aiosqlite:///./author_identity.db",
    backendDir,
  );
  assert.equal(parsed.isSqlite, true);
  assert.equal(
    parsed.sqlitePath,
    path.resolve(backendDir, "./author_identity.db"),
  );
});

test("parseSqliteDatabaseUrl rejects non-SQLite URLs", () => {
  const parsed = parseSqliteDatabaseUrl(
    "postgresql+asyncpg://u:p@localhost:5432/db",
  );
  assert.equal(parsed.isSqlite, false);
  assert.equal(parsed.sqlitePath, null);
});

test("loadDatabaseConfig prefers process.env over files", () => {
  const config = loadDatabaseConfig({
    env: {
      DATABASE_URL: "sqlite+aiosqlite:///./from-env.db",
    },
    envPath: "/tmp/does-not-exist.env",
    examplePath: "/tmp/does-not-exist.example",
    backendDir: "/tmp/backend",
  });
  assert.equal(config.source, "process.env");
  assert.equal(config.isSqlite, true);
  assert.equal(config.sqlitePath, path.resolve("/tmp/backend", "./from-env.db"));
});

test("ensureSqliteDirectory creates missing database directories", () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "rit-sqlite-"));
  const dbPath = path.join(root, "nested", "data", "app.db");
  const dir = ensureSqliteDirectory(dbPath);
  assert.equal(dir, path.dirname(dbPath));
  assert.equal(fs.existsSync(dir), true);
  fs.rmSync(root, { recursive: true, force: true });
});

test("ensureSqliteDirectory is idempotent when the directory already exists", () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "rit-sqlite-"));
  const dbPath = path.join(root, "app.db");
  ensureSqliteDirectory(dbPath);
  ensureSqliteDirectory(dbPath);
  assert.equal(fs.existsSync(root), true);
  fs.rmSync(root, { recursive: true, force: true });
});

test("assertOk reports setup failures clearly", () => {
  assert.throws(
    () =>
      assertOk(
        { status: 2, stdout: "", stderr: "migration boom", error: null },
        "SQLite database initialization failed.",
      ),
    /SQLite database initialization failed[\s\S]*migration boom/,
  );
});

test("package.json keeps setup and concurrent dev scripts", () => {
  const pkg = JSON.parse(fs.readFileSync(PACKAGE_JSON, "utf8"));
  assert.equal(pkg.scripts.setup, "node scripts/setup.js");
  assert.equal(pkg.scripts["setup:frontend"], "npm --prefix frontend install");
  assert.match(pkg.scripts["setup:backend"], /setup-backend/);
  assert.match(pkg.scripts["setup:database"], /setup-database/);
  assert.match(pkg.scripts.dev, /concurrently -k -s first/);
  assert.match(pkg.scripts.dev, /dev:backend/);
  assert.match(pkg.scripts.dev, /dev:frontend/);
  assert.match(pkg.scripts["dev:frontend"], /frontend/);
  assert.match(pkg.scripts["dev:backend"], /uvicorn/);
});

test("setup:database rejects non-SQLite configuration with a clear error", async () => {
  const { setupDatabase } = await import("../setup-database.js");
  assert.throws(
    () =>
      setupDatabase({
        dbConfig: {
          databaseUrl: "postgresql+asyncpg://u:p@localhost:5432/db",
          isSqlite: false,
          sqlitePath: null,
          source: "test",
        },
      }),
    /uses SQLite only/,
  );
});
