#!/usr/bin/env python3
"""Initialize and verify the local SQLite database from backend settings.

Reads DATABASE_URL via app.core.config.get_settings(). Idempotent and safe to
rerun; never deletes existing database files.
"""

from __future__ import annotations

import asyncio
import subprocess
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.config import get_settings


def _log(message: str) -> None:
    print(f"  {message}", flush=True)


def _fail(message: str, code: int = 1) -> None:
    print(f"\nDatabase setup failed:\n{message}\n", flush=True)
    raise SystemExit(code)


def _is_sqlite(url: str) -> bool:
    return url.startswith("sqlite")


def _sqlite_file_path(database_url: str) -> Path:
    sa_url = make_url(database_url)
    database = sa_url.database
    if not database:
        _fail("SQLite DATABASE_URL is missing a file path.")
    path = Path(database)
    if not path.is_absolute():
        path = (BACKEND_DIR / path).resolve()
    return path


def _ensure_sqlite_parent(path: Path) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        _fail(
            "Could not create the SQLite database directory.\n"
            f"Path: {path.parent}\n"
            "Check that you have write permission for this location.\n"
            f"Details: {exc}"
        )
    _log(f"SQLite database path: {path}")
    if path.exists():
        _log("Reusing existing SQLite database file")
    else:
        _log("SQLite database file will be created by migrations")


def _run_alembic() -> None:
    alembic_ini = BACKEND_DIR / "alembic.ini"
    if not alembic_ini.exists():
        _fail(f"Missing Alembic config: {alembic_ini}")
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=str(BACKEND_DIR),
        check=False,
    )
    if result.returncode != 0:
        _fail(
            "Alembic migrations failed.\n"
            "From the backend/ directory, inspect the error above, then rerun:\n"
            "  npm run setup:database"
        )
    _log("Alembic migrations are up to date")


async def _verify(database_url: str) -> None:
    engine = create_async_engine(database_url, pool_pre_ping=True)
    try:
        async with engine.connect() as conn:
            result = await conn.execute(text("SELECT 1"))
            value = result.scalar()
            if value != 1:
                _fail(f"Verification query returned unexpected value: {value!r}")
        _log("Verification query succeeded (SELECT 1)")
    except Exception as exc:  # noqa: BLE001
        _fail(
            "Database verification failed.\n"
            "If the local SQLite file is corrupted, stop the app, back it up, "
            "and rerun migrations after restoring a known-good copy.\n"
            f"Details: {exc}"
        )
    finally:
        await engine.dispose()


def main() -> None:
    settings = get_settings()
    database_url = (settings.database_url or "").strip()
    if not database_url:
        _fail(
            "DATABASE_URL is empty. Set it in backend/.env "
            "(see backend/.env.example)."
        )

    _log("Loaded database settings from application config")

    if not _is_sqlite(database_url):
        _fail(
            "This project currently uses SQLite only.\n"
            "Set DATABASE_URL to a sqlite+aiosqlite URL, for example:\n"
            "  DATABASE_URL=sqlite+aiosqlite:///./author_identity.db\n"
            f"Current value starts with a non-SQLite dialect: {database_url.split(':', 1)[0]}"
        )

    db_path = _sqlite_file_path(database_url)
    _ensure_sqlite_parent(db_path)

    _log("Running Alembic migrations...")
    try:
        _run_alembic()
    except SystemExit:
        raise
    except Exception as exc:  # noqa: BLE001
        _fail(f"Alembic migrations failed: {exc}")

    try:
        asyncio.run(_verify(database_url))
    except SystemExit:
        raise
    except Exception as exc:  # noqa: BLE001
        _fail(f"Database verification failed: {exc}")

    print("  ✓ SQLite database setup complete", flush=True)


if __name__ == "__main__":
    main()
