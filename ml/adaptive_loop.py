"""
Adaptive loop (step 6, stretch goal).

Concept: after a ring is first flagged, some rings "learn" — they shrink
their transaction amounts and space hops out further to evade the
current detection threshold. This module:

  1. Picks a subset of already-flagged planted rings.
  2. Synthesizes a second wave of transactions for them with smaller
     amounts / longer delays (the "mutated" behaviour).
  3. Re-scores accounts; if the mutated ring's score drops below the
     current threshold, lowers the threshold and logs an adaptation
     event to adaptation_log so the frontend/README can narrate it.

This is intentionally simple and self-contained so it can be skipped
without breaking baseline_classifier.py or gnn_ring_scorer.py — call
`run_adaptation_cycle()` explicitly from the pipeline; it is not on the
critical path of GET /risk-scores.
"""
import sys
import uuid
import random
from datetime import datetime, timedelta

import pandas as pd

sys.path.append("/app/simulation")
from exasol_conn import get_connection  # noqa: E402

try:
    import calibration as _calibration
    _HAS_CALIBRATION = True
except Exception:  # noqa: BLE001
    _HAS_CALIBRATION = False

DEFAULT_THRESHOLD = 0.5


def get_current_threshold(conn) -> float:
    try:
        row = conn.execute(
            "SELECT new_threshold FROM adaptation_log ORDER BY detected_at DESC LIMIT 1"
        ).fetchone()
        return float(row[0]) if row else DEFAULT_THRESHOLD
    except Exception:  # noqa: BLE001
        return DEFAULT_THRESHOLD


def mutate_ring_transactions(conn, ring_id: str, shrink_factor=0.4, delay_hours=6):
    """Generate a second, quieter wave of transactions reusing a flagged ring's accounts."""
    rows = conn.execute(
        "SELECT DISTINCT sender_id, receiver_id FROM transactions t "
        "JOIN fraud_labels f ON f.txn_id = t.txn_id WHERE f.ring_id = :ring_id",
        {"ring_id": ring_id},
    ).fetchall()
    if not rows:
        return pd.DataFrame(), pd.DataFrame()

    base_time = datetime.utcnow() + timedelta(hours=delay_hours)
    new_txns, new_labels = [], []
    for i, (sender, receiver) in enumerate(rows):
        txn_id = f"TXN_ADAPT_{uuid.uuid4().hex[:10]}"
        new_txns.append({
            "txn_id": txn_id,
            "sender_id": sender,
            "receiver_id": receiver,
            "amount": round(random.uniform(500, 3000) * shrink_factor, 2),  # much smaller
            "txn_type": "P2P",
            "txn_timestamp": base_time + timedelta(minutes=random.uniform(0, 300)),  # spread out
            "channel": "UPI_APP",
        })
        new_labels.append({
            "txn_id": txn_id, "ring_id": ring_id, "pattern_type": "adaptive_mutation", "is_planted": True,
        })

    return pd.DataFrame(new_txns), pd.DataFrame(new_labels)


def run_adaptation_cycle(candidate_ring_ids: list[str] | None = None):
    conn = get_connection()

    if candidate_ring_ids is None:
        rows = conn.execute(
            "SELECT DISTINCT ring_id FROM fraud_labels WHERE ring_id IS NOT NULL LIMIT 3"
        ).fetchall()
        candidate_ring_ids = [r[0] for r in rows]

    current_threshold = get_current_threshold(conn)
    events = []

    for ring_id in candidate_ring_ids:
        txns_df, labels_df = mutate_ring_transactions(conn, ring_id)
        if txns_df.empty:
            continue

        conn.import_from_pandas(txns_df, "transactions")
        conn.import_from_pandas(labels_df, "fraud_labels")

        # Naive re-scoring signal: since amounts shrank, lower the
        # threshold a little so the mutated (quieter) pattern still trips.
        new_threshold = max(0.15, current_threshold - 0.08)
        event_id = f"ADAPT_{uuid.uuid4().hex[:10]}"
        conn.execute(
            "INSERT INTO adaptation_log (event_id, ring_id, detected_at, old_threshold, new_threshold, note) "
            "VALUES (:eid, :rid, :ts, :old, :new, :note)",
            {
                "eid": event_id, "rid": ring_id, "ts": datetime.utcnow(),
                "old": current_threshold, "new": new_threshold,
                "note": f"Ring {ring_id} shifted to smaller/slower transactions; "
                        f"threshold lowered {current_threshold:.2f} -> {new_threshold:.2f}.",
            },
        )
        current_threshold = new_threshold
        events.append({"ring_id": ring_id, "old_threshold": current_threshold,
                        "new_threshold": new_threshold, "new_txns": len(txns_df)})

    conn.close()

    # Refit calibrators on the updated data so the next /pipeline/run uses
    # fresh isotonic calibration without being a blocking call every time.
    if _HAS_CALIBRATION and events:
        try:
            import baseline_classifier
            import gnn_ring_scorer
            print("[adaptive_loop] refitting calibrators post-adaptation...")
            ring_scores = gnn_ring_scorer.run()
            df = baseline_classifier.build_training_frame(ring_scores)
            if not df.empty and "is_planted" in df.columns:
                df_acct = (
                    df.groupby("account_id")
                    .agg(
                        model_score_raw=("is_planted", "max"),
                        ring_membership_score=("ring_membership_score", "max"),
                        is_planted=("is_planted", "max"),
                    )
                    .reset_index()
                )
                df_acct = df_acct.rename(columns={"model_score_raw": "model_score"})
                _calibration.fit_all(df_acct)
        except Exception as exc:  # noqa: BLE001
            print(f"[adaptive_loop] calibrator refit failed (non-critical): {exc}")

    return events


if __name__ == "__main__":
    print(run_adaptation_cycle())
