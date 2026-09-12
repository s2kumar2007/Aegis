"""
Confidence calibration layer (Step 4).

Fits isotonic-regression calibrators for both `model_score` (XGBoost
baseline) and `ring_membership_score` (GNN heuristic) so that the raw
0-1 outputs become proper posterior probabilities before they enter
explainability.py's Bayesian network.

Design decisions
----------------
* Calibrators are fitted on a held-out validation split and persisted
  with joblib to CALIBRATOR_DIR.  The heavy refit only happens when the
  pipeline is explicitly told to adapt (`/adapt/run`); normal
  `/pipeline/run` just loads the cached files.
* If no cached calibrator exists yet the module silently returns the
  raw scores unchanged so the first cold-start demo never crashes.
* sklearn.isotonic.IsotonicRegression is strictly monotone and never
  needs a GPU — safe on every machine this repo targets.
"""
import os
import pathlib

import numpy as np
import pandas as pd
import joblib
from sklearn.isotonic import IsotonicRegression

CALIBRATOR_DIR = pathlib.Path(
    os.environ.get("AEGIS_CALIBRATOR_DIR", "/tmp/aegis_calibrators")
)
BASELINE_CALIBRATOR_PATH = CALIBRATOR_DIR / "baseline_calibrator.joblib"
RING_CALIBRATOR_PATH     = CALIBRATOR_DIR / "ring_calibrator.joblib"


def _ensure_dir():
    CALIBRATOR_DIR.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# Fitting  (called by adaptive_loop / /adapt/run, NOT by /pipeline/run)
# ---------------------------------------------------------------------------

def fit_baseline_calibrator(
    raw_scores: np.ndarray,
    labels: np.ndarray,
) -> IsotonicRegression:
    """Fit and persist an isotonic calibrator for XGBoost model_score.

    Parameters
    ----------
    raw_scores : array of shape (n,)
        Uncalibrated model probabilities on the validation split.
    labels : array of shape (n,)
        Binary ground-truth (1 = fraud, 0 = normal).
    """
    _ensure_dir()
    cal = IsotonicRegression(out_of_bounds="clip")
    cal.fit(raw_scores, labels)
    joblib.dump(cal, BASELINE_CALIBRATOR_PATH)
    print(f"[calibration] baseline calibrator fitted and saved to {BASELINE_CALIBRATOR_PATH}")
    return cal


def fit_ring_calibrator(
    ring_scores: np.ndarray,
    labels: np.ndarray,
) -> IsotonicRegression:
    """Fit and persist an isotonic calibrator for ring_membership_score."""
    _ensure_dir()
    cal = IsotonicRegression(out_of_bounds="clip")
    cal.fit(ring_scores, labels)
    joblib.dump(cal, RING_CALIBRATOR_PATH)
    print(f"[calibration] ring calibrator fitted and saved to {RING_CALIBRATOR_PATH}")
    return cal


# ---------------------------------------------------------------------------
# Convenience: fit both at once from a labelled merged dataframe
# ---------------------------------------------------------------------------

def fit_all(merged_df: pd.DataFrame) -> None:
    """Fit calibrators from a dataframe that has model_score,
    ring_membership_score, and is_planted columns."""
    needed = {"model_score", "ring_membership_score", "is_planted"}
    missing = needed - set(merged_df.columns)
    if missing:
        print(f"[calibration] cannot fit calibrators — missing columns: {missing}")
        return

    labels = merged_df["is_planted"].astype(int).values

    fit_baseline_calibrator(
        merged_df["model_score"].fillna(0).values, labels
    )
    fit_ring_calibrator(
        merged_df["ring_membership_score"].fillna(0).values, labels
    )


# ---------------------------------------------------------------------------
# Applying  (called every /pipeline/run)
# ---------------------------------------------------------------------------

def _load(path: pathlib.Path) -> "IsotonicRegression | None":
    if path.exists():
        try:
            return joblib.load(path)
        except Exception as exc:
            print(f"[calibration] could not load calibrator at {path}: {exc}")
    return None


def calibrate_scores(merged_df: pd.DataFrame) -> pd.DataFrame:
    """Return a copy of merged_df with calibrated columns added.

    Adds:
        model_score_cal          – calibrated baseline score
        ring_membership_score_cal – calibrated ring score

    If no calibrator is available for a column the raw value is copied
    as-is so downstream code always has a *_cal column to read from.
    """
    df = merged_df.copy()

    baseline_cal = _load(BASELINE_CALIBRATOR_PATH)
    ring_cal     = _load(RING_CALIBRATOR_PATH)

    if baseline_cal is not None:
        df["model_score_cal"] = baseline_cal.predict(df["model_score"].fillna(0).values)
        print("[calibration] applied baseline calibrator")
    else:
        df["model_score_cal"] = df["model_score"].fillna(0)
        print("[calibration] no baseline calibrator found; using raw scores")

    if ring_cal is not None:
        df["ring_membership_score_cal"] = ring_cal.predict(
            df["ring_membership_score"].fillna(0).values
        )
        print("[calibration] applied ring calibrator")
    else:
        df["ring_membership_score_cal"] = df["ring_membership_score"].fillna(0)
        print("[calibration] no ring calibrator found; using raw ring scores")

    return df
