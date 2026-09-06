"""
End-to-end scoring pipeline:

  1. baseline_classifier.run()   -> model_score per account   (ALWAYS runs)
  2. gnn_ring_scorer.run()       -> ring_membership_score      (best-effort)
  3. explainability.explain_accounts() -> plain-language reason (best-effort)
  4. writes the merged result into Exasol's risk_scores table

Each stage degrades gracefully: if the GNN or Bayesian stage throws,
we log it and continue with whatever the earlier stage produced, so a
partial demo never crashes the API.
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


def run_pipeline(flag_threshold: float = 0.5) -> pd.DataFrame:
    # --- 1. baseline (mandatory) -------------------------------------------------
    baseline_scores = baseline_classifier.run()

    # --- 2. graph / GNN ring scoring (best-effort) -------------------------------
    try:
        ring_scores = gnn_ring_scorer.run()
    except Exception:
        print("[pipeline] ring scoring failed, defaulting to 0:")
        traceback.print_exc()
        ring_scores = pd.DataFrame({"account_id": baseline_scores["account_id"], "ring_membership_score": 0.0})

    merged = baseline_scores.merge(ring_scores, on="account_id", how="outer").fillna(0)

    # --- 3. pull raw features again for the Bayesian layer -----------------------
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

    # --- 4. Bayesian explainability (best-effort) --------------------------------
    try:
        rows = merged.to_dict(orient="records")
        explanations = explainability.explain_accounts(rows)
        exp_df = pd.DataFrame(explanations)
        merged = merged.merge(exp_df, on="account_id", how="left")
    except Exception:
        print("[pipeline] explainability failed, defaulting to generic message:")
        traceback.print_exc()
        merged["explanation"] = "Explanation unavailable (Bayesian layer error)."
        merged["risk_level"] = merged["model_score"].apply(lambda s: "high" if s >= flag_threshold else "low")

    merged["flagged_at"] = datetime.utcnow()

    # --- 5. write back to Exasol ---------------------------------------------------
    out = merged[["account_id", "model_score", "ring_membership_score", "explanation", "flagged_at"]].copy()
    conn = get_connection()
    conn.execute("DELETE FROM risk_scores")
    conn.import_from_pandas(out, "risk_scores")
    conn.close()

    print(f"[pipeline] wrote {len(out)} rows to risk_scores")
    return out


if __name__ == "__main__":
    result = run_pipeline()
    print(result.sort_values("model_score", ascending=False).head(15))
