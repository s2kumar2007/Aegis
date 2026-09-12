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
    baseline_scores, xgb_model, feature_df = baseline_classifier.run(ring_scores)

    merged = baseline_scores.merge(ring_scores, on="account_id", how="left").fillna(0)
    if "ring_membership_score" not in merged.columns:
        merged["ring_membership_score"] = 0.0

    # --- 2.5 Stacking Meta-Model -------------------------------------------------
    print("[pipeline] Fitting logistic regression stacker...")
    try:
        from sklearn.linear_model import LogisticRegression
        from sklearn.model_selection import train_test_split
        
        conn = get_connection()
        label_sql = """
        SELECT DISTINCT account_id, 1 as is_fraud FROM (
            SELECT t.sender_id AS account_id FROM transactions t JOIN fraud_labels fl ON t.txn_id = fl.txn_id
            UNION
            SELECT t.receiver_id AS account_id FROM transactions t JOIN fraud_labels fl ON t.txn_id = fl.txn_id
        )
        """
        labels_df = conn.export_to_pandas(label_sql)
        conn.close()
        
        merged_stack = merged.merge(labels_df, on="account_id", how="left")
        merged_stack["is_fraud"] = merged_stack["is_fraud"].fillna(0).astype(int)
        
        X_stack = merged_stack[["model_score", "ring_membership_score"]]
        y_stack = merged_stack["is_fraud"]
        
        # Train/Validation split
        X_train, X_val, y_train, y_val = train_test_split(
            X_stack, y_stack, test_size=0.2, random_state=42, stratify=y_stack if y_stack.sum() > 1 else None
        )
        
        stacker = LogisticRegression(class_weight="balanced")
        stacker.fit(X_train, y_train)
        
        print("\n[pipeline] Stacker Learned Weights:")
        print(f"  model_score weight:           {stacker.coef_[0][0]:.4f}")
        print(f"  ring_membership_score weight: {stacker.coef_[0][1]:.4f}")
        print(f"  Intercept:                    {stacker.intercept_[0]:.4f}\n")
        
        # Replace the final combined risk score with the stacker's output
        merged["model_score"] = stacker.predict_proba(X_stack)[:, 1]
    except Exception as e:
        print(f"[pipeline] Stacking failed: {e}")
        traceback.print_exc()

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

    # --- 6. SHAP & Bayesian explainability ---------------------------------------
    print("[pipeline] Computing SHAP values for explanations...")
    try:
        import shap
        import numpy as np
        
        # We find the highest-risk transaction for each account to explain
        X_all = feature_df[baseline_classifier.FEATURE_COLS].fillna(0)
        feature_df["temp_txn_score"] = xgb_model.predict_proba(X_all)[:, 1]
        idx_max = feature_df.groupby("account_id")["temp_txn_score"].idxmax()
        max_risk_txns = feature_df.loc[idx_max].copy()
        
        X_max = max_risk_txns[baseline_classifier.FEATURE_COLS].fillna(0)
        
        explainer = shap.TreeExplainer(xgb_model)
        # Handle XGBoost's TreeExplainer output (sometimes returns list for multi-class/binary, sometimes array)
        shap_vals = explainer.shap_values(X_max)
        if isinstance(shap_vals, list):
            shap_vals = shap_vals[1]  # positive class
            
        feature_names = baseline_classifier.FEATURE_COLS
        name_map = {
            "txn_count_1h": "unusual transaction velocity",
            "txn_sum_1h": "high hourly transaction volume",
            "amount_deviation_score": "highly anomalous transaction amount",
            "amount_zscore": "highly anomalous transaction amount",
            "distinct_receivers_1h": "fan-out to multiple receivers",
            "distinct_senders_1h": "fan-in from multiple senders",
            "velocity_acceleration": "sudden spike in transaction velocity",
            "ring_membership_score": "connection to a known fraud ring",
            "time_since_last_txn": "unusual timing since last transaction",
            "device_ip_reuse_count": "device or IP address reuse",
            "is_odd_hour": "transaction during unusual hours"
        }
        
        shap_exps = []
        for i in range(len(max_risk_txns)):
            acc_id = max_risk_txns.iloc[i]["account_id"]
            sv = shap_vals[i]
            # Top 2 features by absolute contribution
            top_indices = np.argsort(np.abs(sv))[-2:][::-1]
            
            reasons = []
            for idx in top_indices:
                fname = feature_names[idx]
                friendly = name_map.get(fname, fname.replace("_", " "))
                reasons.append(f"{friendly} (contribution: {sv[idx]:.2f})")
                
            expl_str = "Flagged due to " + " and ".join(reasons)
            shap_exps.append({"account_id": acc_id, "shap_explanation": expl_str})
            
        shap_df = pd.DataFrame(shap_exps)
        merged = merged.merge(shap_df, on="account_id", how="left")
    except Exception as e:
        print(f"[pipeline] SHAP explanation failed: {e}")
        traceback.print_exc()
        merged["shap_explanation"] = ""

    try:
        rows = merged.to_dict(orient="records")
        explanations = explainability.explain_accounts(rows)
        exp_df = pd.DataFrame(explanations)
        merged = merged.merge(exp_df, on="account_id", how="left")
        
        # Replace generic explanation with SHAP explanation if available
        merged["explanation"] = merged.apply(
            lambda r: r["shap_explanation"] if pd.notna(r.get("shap_explanation")) and r.get("shap_explanation") != "" else r.get("explanation", "Explanation unavailable."),
            axis=1
        )
    except Exception:
        print("[pipeline] explainability failed, defaulting to generic message:")
        traceback.print_exc()
        merged["explanation"] = merged.get("shap_explanation", "Explanation unavailable (Bayesian layer error).")
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
