"""
Shared Exasol connection helper.

Uses pyexasol (pure-Python websocket driver — no ODBC driver needed),
configured entirely from environment variables so the same code runs
inside Docker Compose or on a laptop pointed at a local Exasol Personalinstance.
"""
import os
import time
from dotenv import load_dotenv
import pyexasol
from packaging.version import Version

pyexasol.connection.ExaConnection.exasol_db_version = property(lambda self: Version("2026.2.0"))

_original_export_to_pandas = pyexasol.connection.ExaConnection.export_to_pandas
def _export_to_pandas_lowercase(self, *args, **kwargs):
    df = _original_export_to_pandas(self, *args, **kwargs)
    df.columns = df.columns.str.lower()
    return df
pyexasol.connection.ExaConnection.export_to_pandas = _export_to_pandas_lowercase

load_dotenv()
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
                encryption=True,
		websocket_sslopt={"cert_reqs": 0},  # skip verification for self-signed cert (local dev only)
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
    # Strip full-line comments from each line, then rejoin, before splitting
    # into statements -- otherwise a comment line preceding real SQL causes
    # the whole statement to look like "starts with --" and gets dropped.
    cleaned_lines = [line for line in raw.splitlines() if not line.strip().startswith("--")]
    cleaned = "\n".join(cleaned_lines)
    statements = [s.strip() for s in cleaned.split(";") if s.strip()]
    for stmt in statements:
        if not any(c.isalnum() for c in stmt):
            continue
        conn.execute(stmt)
