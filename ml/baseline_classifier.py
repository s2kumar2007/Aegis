"""
Baseline fraud classifier.

Trains an XGBoost model (GPU histogram tree method when a GPU is
available, CPU fallback otherwise) purely on features that already
come out of account_velocity_view — i.e. Exasol has already done every
aggregation; this script only fits/scores a model on the result set.

This is deliberately the SAFE, always-working layer: steps 1-4 of the
brief. Everything downstream (GNN, Bayesian explainability, adaptive
loop) is additive on top of the `model_score` this produces.
"""
import sys
import numpy as np
import pandas as pd
import xgboost as xgb
from sklearn.model_selection import train_test_split

sys.path.append("/app/simulation")
from exasol_conn import get_connection  # noqa: E402

FEATURE_COLS = [
    "txn_count_1h", "txn_sum_1h", "txn_count_24h", "txn_sum_24h",
    "avg_amount_30d", "stddev_amount_30d", "amount_deviation_score",
    "distinct_receivers_1h", "in_txn_count_1h", "distinct_senders_1h",
    "time_since_first_txn", "amount_vs_running_avg_ratio", "velocity_acceleration",
    "ring_membership_score",
    # newly added features
    "time_since_last_txn", "device_ip_reuse_count", "amount_zscore",
    "txn_hour_of_day", "is_odd_hour"
]


def load_features() -> pd.DataFrame:
    """Pull the already-aggregated feature set straight from Exasol."""
    conn = get_connection()
    df = conn.export_to_pandas(
        "SELECT * FROM account_velocity_view"
    )
    conn.close()
    return df


def load_labels() -> pd.DataFrame:
    """Per-transaction ground truth for planted rings, for supervised training."""
    conn = get_connection()
    df = conn.export_to_pandas(
        "SELECT txn_id, is_planted FROM fraud_labels"
    )
    conn.close()
    return df


def build_training_frame(ring_scores: pd.DataFrame = None) -> pd.DataFrame:
    feats = load_features()
    labels = load_labels()
    merged = feats.merge(labels, on="txn_id", how="left")
    merged["is_planted"] = merged["is_planted"].fillna(False).astype(int)
    
    if ring_scores is not None and not ring_scores.empty:
        merged = merged.merge(ring_scores, on="account_id", how="left")
    
    if "ring_membership_score" not in merged.columns:
        merged["ring_membership_score"] = 0.0
    else:
        merged["ring_membership_score"] = merged["ring_membership_score"].fillna(0.0)

    return merged


def train_model(df: pd.DataFrame):
    X = df[FEATURE_COLS].fillna(0)
    y = df["is_planted"]

    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, random_state=42, stratify=y if y.sum() > 1 else None
    )

    scale_pos_weight = max(1.0, (y_train == 0).sum() / max(1, (y_train == 1).sum()))

    base_params = dict(
        n_estimators=200,
        max_depth=5,
        learning_rate=0.08,
        subsample=0.8,
        colsample_bytree=0.8,
        eval_metric="aucpr",
    )

    from sklearn.metrics import precision_score, recall_score, f1_score, average_precision_score
    
    def evaluate_and_print(model_name, model):
        if len(X_test) == 0 or y_test.sum() == 0:
            return
        proba = model.predict_proba(X_test)[:, 1]
        preds = model.predict(X_test)
        prec = precision_score(y_test, preds, zero_division=0)
        rec = recall_score(y_test, preds, zero_division=0)
        f1 = f1_score(y_test, preds, zero_division=0)
        prauc = average_precision_score(y_test, proba)
        print(f"[baseline_classifier] {model_name} -> Precision: {prec:.3f}, Recall: {rec:.3f}, F1: {f1:.3f}, PR-AUC: {prauc:.3f}")

    # Train BEFORE (unweighted)
    print("[baseline_classifier] Training BEFORE (unweighted)...")
    try:
        model_before = xgb.XGBClassifier(tree_method="gpu_hist", predictor="gpu_predictor", **base_params)
        model_before.fit(X_train, y_train)
    except Exception:
        model_before = xgb.XGBClassifier(tree_method="hist", **base_params)
        model_before.fit(X_train, y_train)
    evaluate_and_print("Before (Unweighted)", model_before)

    # Train AFTER (weighted)
    print(f"[baseline_classifier] Training AFTER (weighted, scale_pos_weight={scale_pos_weight:.1f})...")
    params_weighted = dict(**base_params, scale_pos_weight=scale_pos_weight)
    try:
        model_after = xgb.XGBClassifier(tree_method="gpu_hist", predictor="gpu_predictor", **params_weighted)
        model_after.fit(X_train, y_train)
        print("[baseline_classifier] trained with GPU (gpu_hist)")
    except Exception as e:
        print(f"[baseline_classifier] GPU training unavailable ({e}); falling back to CPU 'hist'")
        model_after = xgb.XGBClassifier(tree_method="hist", **params_weighted)
        model_after.fit(X_train, y_train)
    evaluate_and_print("After (Weighted)", model_after)

    return model_after


def score_accounts(model, df: pd.DataFrame) -> pd.DataFrame:
    """Aggregate per-transaction scores up to a per-account model_score (max risk seen)."""
    X = df[FEATURE_COLS].fillna(0)
    df = df.copy()
    df["txn_score"] = model.predict_proba(X)[:, 1]
    account_scores = (
        df.groupby("account_id")["txn_score"]
        .max()
        .reset_index()
        .rename(columns={"txn_score": "model_score"})
    )
    return account_scores


def run(ring_scores: pd.DataFrame = None) -> pd.DataFrame:
    df = build_training_frame(ring_scores)
    if df.empty:
        raise RuntimeError("account_velocity_view returned no rows — run generate_data.py first")
    model = train_model(df)
    scores = score_accounts(model, df)
    return scores


if __name__ == "__main__":
    scores = run()
    print(scores.sort_values("model_score", ascending=False).head(20))
