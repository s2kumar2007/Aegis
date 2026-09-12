import pyexasol
from dotenv import load_dotenv
import os

load_dotenv()

conn = pyexasol.connect(
    dsn=f"{os.getenv('EXASOL_HOST')}:{os.getenv('EXASOL_PORT')}",
    user=os.getenv('EXASOL_USER'),
    password=os.getenv('EXASOL_PASSWORD'),
    encryption=True,
    websocket_sslopt={"cert_reqs": 0}
)

sql_files = [
    "sql/01_schema.sql",
    "sql/02_account_velocity_view.sql",
    "sql/03_ring_trace_view.sql",
    "sql/04_ring_summary_view.sql",
]

for f in sql_files:
    print(f"Running {f} ...")
    with open(f) as file:
        content = file.read()
    for statement in content.split(";"):
        stmt = statement.strip()
        if stmt:
            conn.execute(stmt)
    print(f"  done.")

print("All schema files applied successfully.")
conn.close()
