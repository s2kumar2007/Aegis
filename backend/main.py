"""
AEGIS backend — FastAPI service.

All heavy computation (velocity features, multi-hop ring tracing) is
delegated to Exasol views; this service reads those views/tables and
exposes them as JSON, plus a couple of orchestration endpoints
(replay, pipeline trigger).
"""
import sys
import json
from datetime import datetime
from typing import Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
import pandas as pd

sys.path.append("/app/simulation")
sys.path.append("/app/ml")

from exasol_conn import get_connection  # noqa: E402

app = FastAPI(title="AEGIS Fraud Detection API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# In-memory replay cursor for the timeline demo (kept simple on purpose —
# this drives the frontend's time-scrubber, it is not the system of record).
_replay_state = {"running": False, "cursor_ts": None, "speed": 1.0}


def df_to_records(df: pd.DataFrame):
    return json.loads(df.to_json(orient="records", date_format="iso"))


@app.get("/health")
def health():
    return {"status": "ok", "time": datetime.utcnow().isoformat()}


@app.get("/accounts")
def get_accounts(limit: int = Query(500, le=5000)):
    conn = get_connection()
    df = conn.export_to_pandas(f"SELECT * FROM accounts LIMIT {limit}")
    conn.close()
    return df_to_records(df)


@app.get("/transactions")
def get_transactions(since: Optional[str] = None, limit: int = Query(2000, le=20000)):
    conn = get_connection()
    if since:
        safe_since = since.replace("'", "''")
        df = conn.export_to_pandas(
            f"SELECT * FROM transactions WHERE txn_timestamp >= '{safe_since}' ORDER BY txn_timestamp LIMIT {limit}"
        )
    else:
        df = conn.export_to_pandas(f"SELECT * FROM transactions ORDER BY txn_timestamp LIMIT {limit}")
    conn.close()
    return df_to_records(df)


@app.get("/risk-scores")
def get_risk_scores(min_score: float = 0.0, limit: int = Query(1000, le=10000)):
    conn = get_connection()
    df = conn.export_to_pandas(
        f"SELECT * FROM risk_scores WHERE model_score >= {min_score} "
        f"ORDER BY model_score DESC LIMIT {limit}"
    )
    conn.close()
    return df_to_records(df)

@app.get("/rings")
def get_rings(limit: int = Query(50, le=500)):
    """Ring candidates surfaced by the Exasol recursive-CTE trace (ring_summary_view)."""
    conn = get_connection()
    df = conn.export_to_pandas(f"SELECT * FROM ring_summary_view LIMIT {limit}")
    conn.close()
    return df_to_records(df)


@app.get("/rings/{root_account_id}/trace")
def get_ring_trace(root_account_id: str):
    """Full hop-by-hop path for one ring's case-file panel."""
    conn = get_connection()
    safe_root_id = root_account_id.replace("'", "''")
    df = conn.export_to_pandas(
        f"SELECT * FROM ring_trace_view WHERE root_account_id = '{safe_root_id}' ORDER BY hop_no"
    )
    conn.close()
    if df.empty:
        raise HTTPException(status_code=404, detail="No trace found for that root account")
    return df_to_records(df)


@app.get("/explain/{account_id}")
def explain_account(account_id: str):
    conn = get_connection()
    safe_id = account_id.replace("'", "''")
    df = conn.export_to_pandas(
        f"SELECT * FROM risk_scores WHERE account_id = '{safe_id}'"
    )
    conn.close()
    if df.empty:
        raise HTTPException(status_code=404, detail="No score/explanation on file for this account yet")
    return df_to_records(df)[0]


@app.post("/pipeline/run")
def trigger_pipeline():
    """Re-run baseline + graph + Bayesian layers and refresh risk_scores."""
    import pipeline
    result = pipeline.run_pipeline()
    return {"scored_accounts": len(result)}


@app.post("/simulate/replay")
def start_replay(speed: int = 60):
    """
    Marks the replay as running from the earliest transaction timestamp.
    The frontend polls GET /timeline-state?t=... while driving the
    scrubber; this endpoint just resets/starts the cursor server-side.
    """
    conn = get_connection()
    row = conn.execute("SELECT MIN(txn_timestamp) FROM transactions").fetchone()
    conn.close()
    _replay_state["running"] = True
    _replay_state["cursor_ts"] = str(row[0]) if row and row[0] else None
    _replay_state["speed"] = speed
    return _replay_state


@app.get("/timeline-state")
def timeline_state(t: str = Query(..., description="ISO timestamp to snapshot the network at")):
    """
    Returns the network state (accounts touched, transactions, flagged
    rings) as of simulated time `t`, for the time-scrubber.
    """
    conn = get_connection()
    safe_t = str(t).replace("'", "''")
    txns = conn.export_to_pandas(
        f"SELECT * FROM transactions WHERE txn_timestamp <= '{safe_t}' ORDER BY txn_timestamp"
    )
    rings = conn.export_to_pandas(
        f"SELECT * FROM ring_summary_view WHERE chain_start <= '{safe_t}'"
    )
    conn.close()
    return {
        "as_of": t,
        "transactions": df_to_records(txns),
        "rings": df_to_records(rings),
    }


@app.post("/adapt/run")
def trigger_adaptation():
    """Runs the adaptive-loop stretch feature (step 6). Safe to call even if unused."""
    import adaptive_loop
    events = adaptive_loop.run_adaptation_cycle()
    return {"events": events}
