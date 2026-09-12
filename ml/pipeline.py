"""
End-to-end scoring pipeline:

  1. gnn_ring_scorer.run()       -> ring_membership_score      (best-effort)
  2. baseline_classifier.run()   -> model_score per account   (ALWAYS runs)
                                    (GNN score is stacked as a feature)
  3. calibration.calibrate_scores() -> *_cal columns           (best-effort)
  4. autoencoder_scorer.run()    -> anomaly_score              (best-effort, optional)
  5. explainability.explain_accounts() -> plain-language reason (best-effort)
  6. writes the merged result into Exasol's risk_scores table

Each stage degrades gracefully: if any optional stage throws we log it
and continue with whatever the earlier stage produced, so a partial demo
never crashes the API.
"""
import sys
import traceback
from datetime import datetime

import pandas as pd

sys.path.append("/app/simulation")
from exasol_conn import get_connection  # noqa: E402

import baseline_classifier
import gnn_ring_scorer
import explainability

# --- Optional imports (additive) -----------------------------------------------
try:
    import calibration as _calibration
    _HAS_CALIBRATION = True
except Exception:  # noqa: BLE001
    _HAS_CALIBRATION = False
    print("[pipeline] calibration module not available; skipping calibration step")

try:
    import autoencoder_scorer as _ae_scorer
    _HAS_AE = True
except Exception:  # noqa: BLE001
    _HAS_AE = False
    print("[pipeline] autoencoder_scorer module not available; skipping anomaly step")


def run_pipeline(flag_threshold: float = 0.5) -> pd.DataFrame:
    # --- 1. graph / GNN ring scoring (best-effort) -------------------------------
    try:
        ring_scores = gnn_ring_scorer.run()
    except Exception:
        print("[pipeline] ring scoring failed, defaulting to empty dataframe:")
        traceback.print_exc()
        ring_scores = pd.DataFrame(columns=["account_id", "ring_membership_score"])

    # --- 2. baseline (mandatory) — GNN score stacked as feature -----------------
    baseline_scores = baseline_classifier.run(ring_scores)

    merged = baseline_scores.merge(ring_scores, on="account_id", how="left").fillna(0)
    if "ring_membership_score" not in merged.columns:
        merged["ring_membership_score"] = 0.0

    # --- 3. confidence calibration (best-effort) ---------------------------------
    if _HAS_CALIBRATION:
        try:
            merged = _calibration.calibrate_scores(merged)
        except Exception:
            print("[pipeline] calibration failed; using raw scores:")
            traceback.print_exc()
            merged["model_score_cal"]           = merged["model_score"]
            merged["ring_membership_score_cal"] = merged["ring_membership_score"]
    else:
        merged["model_score_cal"]           = merged["model_score"]
        merged["ring_membership_score_cal"] = merged["ring_membership_score"]

    # --- 4. autoencoder anomaly signal (best-effort, optional) -------------------
    if _HAS_AE:
        try:
            ae_scores = _ae_scorer.run()
            merged = merged.merge(ae_scores, on="account_id", how="left")
            merged["anomaly_score"] = merged["anomaly_score"].fillna(0.0)
        except Exception:
            print("[pipeline] autoencoder scoring failed; defaulting anomaly_score to 0:")
            traceback.print_exc()
            merged["anomaly_score"] = 0.0
    else:
        merged["anomaly_score"] = 0.0

    # --- 5. pull raw features for the Bayesian layer -----------------------------
    conn = get_connection()
    feat_df = conn.export_to_pandas(
        "SELECT v.account_id, v.txn_count_1h, v.amount_deviation_score, a.account_age_days "
        "FROM account_velocity_view v "
        "JOIN accounts a ON a.account_id = v.account_id"
    )
    conn.close()

    # keep the worst (max) velocity/deviation reading per account for explanation purposes
    feat_agg = (
        feat_df.groupby("account_id")
        .agg(txn_count_1h=("txn_count_1h", "max"),
             amount_deviation_score=("amount_deviation_score", "max"),
             account_age_days=("account_age_days", "first"))
        .reset_index()
    )

    merged = merged.merge(feat_agg, on="account_id", how="left")

    # --- 6. Bayesian explainability (best-effort) --------------------------------
    try:
        rows = merged.to_dict(orient="records")
        explanations = explainability.explain_accounts(rows)
        exp_df = pd.DataFrame(explanations)
        merged = merged.merge(exp_df, on="account_id", how="left")
    except Exception:
        print("[pipeline] explainability failed, defaulting to generic message:")
        traceback.print_exc()
        merged["explanation"] = "Explanation unavailable (Bayesian layer error)."
        merged["risk_level"] = merged["model_score"].apply(
            lambda s: "high" if s >= flag_threshold else "low"
        )

    merged["flagged_at"] = datetime.utcnow()

    # --- 7. write back to Exasol -------------------------------------------------
    out_cols = [
        "account_id", "model_score", "ring_membership_score",
        "anomaly_score", "explanation", "flagged_at",
    ]
    # Only keep columns that actually exist (anomaly_score may be absent if schema is old)
    out_cols_present = [c for c in out_cols if c in merged.columns]
    out = merged[out_cols_present].copy()

    conn = get_connection()
    conn.execute("DELETE FROM risk_scores")
    conn.import_from_pandas(out, "risk_scores")
    conn.close()

    print(f"[pipeline] wrote {len(out)} rows to risk_scores")
    return out


if __name__ == "__main__":
    result = run_pipeline()
    print(result.sort_values("model_score", ascending=False).head(15))
