"""
Shared Exasol connection helper.

Uses pyexasol (pure-Python websocket driver — no ODBC driver needed),
configured entirely from environment variables so the same code runs
inside Docker Compose or on a laptop pointed at a local Exasol Personal
instance.
"""
import os
import time
import pyexasol

EXASOL_HOST = os.getenv("EXASOL_HOST", "localhost")
EXASOL_PORT = os.getenv("EXASOL_PORT", "8563")
EXASOL_USER = os.getenv("EXASOL_USER", "sys")
EXASOL_PASSWORD = os.getenv("EXASOL_PASSWORD", "exasol")
EXASOL_SCHEMA = os.getenv("EXASOL_SCHEMA", "AEGIS")


def get_connection(retries: int = 20, delay_seconds: float = 5.0):
    """
    Connect to Exasol, retrying while the container finishes booting
    (Exasol Personal can take 60-90s to become queryable after the
    container reports healthy on the socket).
    """
    dsn = f"{EXASOL_HOST}:{EXASOL_PORT}"
    last_err = None
    for attempt in range(1, retries + 1):
        try:
            conn = pyexasol.connect(
                dsn=dsn,
                user=EXASOL_USER,
                password=EXASOL_PASSWORD,
                schema=EXASOL_SCHEMA,
                compression=True,
            )
            return conn
        except Exception as e:  # noqa: BLE001
            last_err = e
            print(f"[exasol_conn] attempt {attempt}/{retries} failed: {e}")
            time.sleep(delay_seconds)
    raise RuntimeError(f"Could not connect to Exasol after {retries} attempts") from last_err


def run_sql_file(conn, path: str):
    """Execute a .sql file's statements one at a time (split on ';')."""
    with open(path, "r") as f:
        raw = f.read()
    statements = [s.strip() for s in raw.split(";") if s.strip() and not s.strip().startswith("--")]
    for stmt in statements:
        # Skip pure-comment fragments left after split
        if not any(c.isalnum() for c in stmt):
            continue
        conn.execute(stmt)
