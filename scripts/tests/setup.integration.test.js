import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(__dirname, "..", "..");
const DB_PATH = path.join(ROOT, "backend", "author_identity.db");

function runNpm(script, timeoutMs = 120_000) {
  return new Promise((resolve, reject) => {
    const child = spawn("npm", ["run", script], {
      cwd: ROOT,
      env: process.env,
      stdio: ["ignore", "pipe", "pipe"],
    });
    let stdout = "";
    let stderr = "";
    const timer = setTimeout(() => {
      child.kill("SIGTERM");
      reject(new Error(`Timed out running npm run ${script}`));
    }, timeoutMs);
    child.stdout.on("data", (chunk) => {
      stdout += chunk.toString();
    });
    child.stderr.on("data", (chunk) => {
      stderr += chunk.toString();
    });
    child.on("error", (error) => {
      clearTimeout(timer);
      reject(error);
    });
    child.on("exit", (code) => {
      clearTimeout(timer);
      resolve({ code, stdout, stderr });
    });
  });
}

test("SQLite setup:database succeeds and is idempotent", async () => {
  const existedBefore = fs.existsSync(DB_PATH);
  const sizeBefore = existedBefore ? fs.statSync(DB_PATH).size : 0;

  const first = await runNpm("setup:database");
  assert.equal(first.code, 0, first.stderr || first.stdout);
  assert.match(first.stdout, /SQLite/i);
  assert.doesNotMatch(first.stdout + first.stderr, /PostgreSQL|Homebrew|winget|apt-get/i);
  assert.equal(fs.existsSync(DB_PATH), true);

  const second = await runNpm("setup:database");
  assert.equal(second.code, 0, second.stderr || second.stdout);
  assert.match(second.stdout, /SQLite database initialized and verified|Alembic migrations are up to date/i);

  // Existing data must not be wiped by a repeated setup.
  if (existedBefore) {
    assert.ok(fs.statSync(DB_PATH).size >= sizeBefore);
  }
});

test("npm run dev starts frontend and backend together", async () => {
  const child = spawn("npm", ["run", "dev"], {
    cwd: ROOT,
    env: process.env,
    stdio: ["ignore", "pipe", "pipe"],
  });

  let output = "";
  const combined = await new Promise((resolve, reject) => {
    const timer = setTimeout(() => {
      child.kill("SIGINT");
      reject(new Error(`Timed out waiting for dev servers.\n${output}`));
    }, 45_000);

    const onData = (chunk) => {
      output += chunk.toString();
      if (
        /Uvicorn running on/.test(output) &&
        /Local:\s+http:\/\/localhost:5173/.test(output)
      ) {
        clearTimeout(timer);
        resolve(output);
      }
    };
    child.stdout.on("data", onData);
    child.stderr.on("data", onData);
    child.on("error", (error) => {
      clearTimeout(timer);
      reject(error);
    });
  });

  assert.match(combined, /Uvicorn running on/);
  assert.match(combined, /localhost:5173/);
  assert.doesNotMatch(combined, /PostgreSQL|Homebrew|winget/i);

  child.kill("SIGINT");
  await new Promise((resolve) => {
    const timer = setTimeout(() => {
      child.kill("SIGKILL");
      resolve();
    }, 5_000);
    child.on("exit", () => {
      clearTimeout(timer);
      resolve();
    });
  });
});
