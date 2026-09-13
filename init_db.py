"""
init_db.py — Runs once to set up Exasol schema.
Called by the db-init Docker container on first boot.
"""
import os
import glob
import time
import pyexasol

HOST     = os.environ.get("EXASOL_HOST", "exasol")
PORT     = os.environ.get("EXASOL_PORT", "8563")
USER     = os.environ.get("EXASOL_USER", "sys")
PASSWORD = os.environ.get("EXASOL_PASSWORD", "exasol123")

print("[init_db] Connecting to Exasol...")
conn = None
for attempt in range(30):
    try:
        conn = pyexasol.connect(
            dsn=f"{HOST}:{PORT}",
            user=USER,
            password=PASSWORD,
            websocket_sslopt={"cert_reqs": 0},
        )
        print("[init_db] Connected!")
        break
    except Exception as e:
        print(f"[init_db] attempt {attempt+1}/30 failed: {e}")
        time.sleep(10)

if conn is None:
    raise SystemExit("[init_db] Could not connect to Exasol. Aborting.")

for sql_file in sorted(glob.glob("/sql/*.sql")):
    print(f"[init_db] Running {sql_file}...")
    with open(sql_file) as f:
        raw = f.read()
    lines = [l for l in raw.splitlines() if not l.strip().startswith("--")]
    for stmt in "\n".join(lines).split(";"):
        stmt = stmt.strip()
        if stmt:
            try:
                conn.execute(stmt)
            except Exception as e:
                print(f"[init_db] WARN: {e}")

conn.close()
print("[init_db] Schema init complete!")
