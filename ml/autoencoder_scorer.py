"""
Autoencoder anomaly scorer (Step 5).

Trains a simple feedforward PyTorch autoencoder **on non-fraud
transactions only** (account_velocity_view rows where is_planted = 0).
Reconstruction error acts as an anomaly signal: accounts whose feature
vectors reconstruct poorly are structurally unusual and get a higher
anomaly_score.

CPU / no-torch fallback
-----------------------
If `torch` is not importable we fall back to a per-column z-score
aggregation — the same "never break the baseline demo" pattern used in
gnn_ring_scorer.py.

Additive / optional wiring
---------------------------
`pipeline.py` imports this module inside a try/except.  If the import
fails (old environment, missing torch) the rest of the pipeline runs
completely unchanged.  The anomaly_score column simply won't appear in
the output, and explainability.py is tolerant of its absence.
"""
import sys
import numpy as np
import pandas as pd

sys.path.append("/app/simulation")
from exasol_conn import get_connection  # noqa: E402

# Columns from account_velocity_view used by the autoencoder.
# Matches FEATURE_COLS in baseline_classifier minus ring_membership_score
# (we want the raw Exasol features, not the derived GNN signal).
_AE_COLS = [
    "txn_count_1h", "txn_sum_1h", "txn_count_24h", "txn_sum_24h",
    "avg_amount_30d", "stddev_amount_30d", "amount_deviation_score",
    "distinct_receivers_1h", "in_txn_count_1h", "distinct_senders_1h",
    "time_since_first_txn", "amount_vs_running_avg_ratio", "velocity_acceleration",
]

# ------------------------------------------------------------------
# Optional torch import
# ------------------------------------------------------------------
try:
    import torch
    import torch.nn as nn
    _TORCH_OK = True
except Exception:  # noqa: BLE001
    _TORCH_OK = False


# ------------------------------------------------------------------
# PyTorch autoencoder definition
# ------------------------------------------------------------------
if _TORCH_OK:
    class _Autoencoder(nn.Module):
        def __init__(self, n_features: int, hidden: int = 32, bottleneck: int = 8):
            super().__init__()
            self.encoder = nn.Sequential(
                nn.Linear(n_features, hidden),
                nn.ReLU(),
                nn.Linear(hidden, bottleneck),
                nn.ReLU(),
            )
            self.decoder = nn.Sequential(
                nn.Linear(bottleneck, hidden),
                nn.ReLU(),
                nn.Linear(hidden, n_features),
            )

        def forward(self, x):
            return self.decoder(self.encoder(x))


# ------------------------------------------------------------------
# Data loading helpers
# ------------------------------------------------------------------

def _load_data() -> pd.DataFrame:
    """Load account_velocity_view joined with fraud_labels from Exasol."""
    conn = get_connection()
    df = conn.export_to_pandas(
        "SELECT v.*, COALESCE(f.is_planted, 0) AS is_planted "
        "FROM account_velocity_view v "
        "LEFT JOIN fraud_labels f ON f.txn_id = v.txn_id"
    )
    conn.close()
    return df


def _prepare_matrix(df: pd.DataFrame) -> np.ndarray:
    """Fill NaN, clip outliers, return float32 numpy array."""
    cols = [c for c in _AE_COLS if c in df.columns]
    X = df[cols].fillna(0).values.astype(np.float32)
    # winsorise at 99th percentile so single large outliers don't dominate training
    p99 = np.percentile(X, 99, axis=0) + 1e-8
    X = np.clip(X, -p99, p99)
    X = X / p99  # scale to [-1, 1] range (approx)
    return X


# ------------------------------------------------------------------
# Z-score fallback (no torch required)
# ------------------------------------------------------------------

def _zscore_anomaly(df: pd.DataFrame) -> pd.DataFrame:
    """Fallback: mean absolute z-score across feature columns as anomaly proxy."""
    cols = [c for c in _AE_COLS if c in df.columns]
    X = df[cols].fillna(0)
    mu = X.mean()
    sigma = X.std().replace(0, 1)
    z = ((X - mu) / sigma).abs().mean(axis=1)
    z_norm = (z - z.min()) / (z.max() - z.min() + 1e-9)
    anomaly_per_txn = df[["account_id"]].copy()
    anomaly_per_txn["anomaly_score"] = z_norm.values
    return anomaly_per_txn.groupby("account_id")["anomaly_score"].max().reset_index()


# ------------------------------------------------------------------
# PyTorch training + scoring
# ------------------------------------------------------------------

def _torch_anomaly(df: pd.DataFrame, epochs: int = 40, lr: float = 1e-3) -> pd.DataFrame:
    """Train autoencoder on non-fraud rows, score all rows by recon error."""
    cols = [c for c in _AE_COLS if c in df.columns]
    X_full = _prepare_matrix(df)
    normal_mask = df["is_planted"].fillna(0).astype(int) == 0

    X_normal = X_full[normal_mask]
    if len(X_normal) < 10:
        print("[autoencoder_scorer] too few normal rows; falling back to z-score")
        return _zscore_anomaly(df)

    device = "cuda" if torch.cuda.is_available() else "cpu"
    X_t = torch.tensor(X_normal, dtype=torch.float32).to(device)

    n_features = X_t.shape[1]
    model = _Autoencoder(n_features).to(device)
    optimizer = torch.optim.Adam(model.parameters(), lr=lr)
    loss_fn = nn.MSELoss()

    model.train()
    for epoch in range(epochs):
        optimizer.zero_grad()
        recon = model(X_t)
        loss = loss_fn(recon, X_t)
        loss.backward()
        optimizer.step()
        if (epoch + 1) % 10 == 0:
            print(f"[autoencoder_scorer] epoch {epoch+1}/{epochs} loss={loss.item():.5f}")

    # Score every row (including fraud) by reconstruction error
    model.eval()
    X_all_t = torch.tensor(X_full, dtype=torch.float32).to(device)
    with torch.no_grad():
        recon_all = model(X_all_t)
        recon_error = ((recon_all - X_all_t) ** 2).mean(dim=1).cpu().numpy()

    # Normalise to [0, 1]
    recon_norm = (recon_error - recon_error.min()) / (recon_error.max() - recon_error.min() + 1e-9)

    per_txn = df[["account_id"]].copy()
    per_txn["anomaly_score"] = recon_norm
    return per_txn.groupby("account_id")["anomaly_score"].max().reset_index()


# ------------------------------------------------------------------
# Public API
# ------------------------------------------------------------------

def run() -> pd.DataFrame:
    """
    Returns a DataFrame with columns [account_id, anomaly_score].

    anomaly_score is in [0, 1] — higher = more anomalous.
    Accounts not present in account_velocity_view get a default of 0
    (handled in pipeline.py via a left-join + fillna).
    """
    df = _load_data()
    if df.empty:
        print("[autoencoder_scorer] no data; returning empty anomaly frame")
        return pd.DataFrame(columns=["account_id", "anomaly_score"])

    if _TORCH_OK:
        print(f"[autoencoder_scorer] running PyTorch autoencoder "
              f"({'CUDA' if (torch.cuda.is_available()) else 'CPU'})")
        try:
            return _torch_anomaly(df)
        except Exception as exc:  # noqa: BLE001
            print(f"[autoencoder_scorer] torch path failed ({exc}); falling back to z-score")

    print("[autoencoder_scorer] torch not available; using z-score anomaly")
    return _zscore_anomaly(df)


if __name__ == "__main__":
    scores = run()
    print(scores.sort_values("anomaly_score", ascending=False).head(20))
