"""
Explainability layer.

Builds a small discrete Bayesian network by hand (fixed structure +
hand-specified CPDs reflecting reasonable domain priors — this is a
hackathon-scale network, not learned from millions of labelled cases)
over:

    transaction_velocity (low/med/high)
    account_age          (new/established)
    ring_membership       (yes/no)
    amount_deviation      (normal/high)
      -> fraud_risk (low/med/high)

For every flagged account we discretize its actual feature values into
these bins, run inference, and turn the result into a plain-language
explanation string that's stored in risk_scores.explanation.
"""
from pgmpy.models import DiscreteBayesianNetwork
from pgmpy.factors.discrete import TabularCPD
from pgmpy.inference import VariableElimination


def build_network() -> DiscreteBayesianNetwork:
    model = DiscreteBayesianNetwork([
        ("transaction_velocity", "fraud_risk"),
        ("account_age", "fraud_risk"),
        ("ring_membership", "fraud_risk"),
        ("amount_deviation", "fraud_risk"),
        ("anomaly_signal", "fraud_risk"),   # Step 5: autoencoder anomaly node
    ])

    cpd_velocity = TabularCPD("transaction_velocity", 3, [[0.7], [0.2], [0.1]],
                               state_names={"transaction_velocity": ["low", "med", "high"]})
    cpd_age = TabularCPD("account_age", 2, [[0.85], [0.15]],
                          state_names={"account_age": ["established", "new"]})
    cpd_ring = TabularCPD("ring_membership", 2, [[0.9], [0.1]],
                           state_names={"ring_membership": ["no", "yes"]})
    cpd_deviation = TabularCPD("amount_deviation", 2, [[0.85], [0.15]],
                                state_names={"amount_deviation": ["normal", "high"]})
    cpd_anomaly = TabularCPD("anomaly_signal", 2, [[0.85], [0.15]],
                              state_names={"anomaly_signal": ["normal", "high"]})

    # fraud_risk | velocity(3) x age(2) x ring(2) x deviation(2) x anomaly(2) = 48 combos
    states_velocity = ["low", "med", "high"]
    states_age = ["established", "new"]
    states_ring = ["no", "yes"]
    states_dev = ["normal", "high"]
    states_anomaly = ["normal", "high"]

    def risk_weights(v, a, r, d, an):
        score = 0.0
        score += {"low": 0.0, "med": 0.35, "high": 0.7}[v]
        score += {"established": 0.0, "new": 0.25}[a]
        score += {"no": 0.0, "yes": 0.6}[r]
        score += {"normal": 0.0, "high": 0.3}[d]
        score += {"normal": 0.0, "high": 0.4}[an]   # anomaly adds up to 0.4
        score = min(score, 1.8)
        p_high = min(0.95, score / 1.8 * 0.9)
        p_low = max(0.02, 1 - score / 1.8) * 0.6
        p_med = max(0.03, 1 - p_high - p_low)
        total = p_low + p_med + p_high
        return [p_low / total, p_med / total, p_high / total]

    columns = []
    for v in states_velocity:
        for a in states_age:
            for r in states_ring:
                for d in states_dev:
                    for an in states_anomaly:
                        columns.append(risk_weights(v, a, r, d, an))

    # TabularCPD: rows = states of fraud_risk, cols = parent combos
    values = list(zip(*columns))  # transpose -> 3 rows x 48 cols

    cpd_fraud = TabularCPD(
        "fraud_risk", 3, list(map(list, values)),
        evidence=["transaction_velocity", "account_age", "ring_membership",
                  "amount_deviation", "anomaly_signal"],
        evidence_card=[3, 2, 2, 2, 2],
        state_names={
            "fraud_risk": ["low", "med", "high"],
            "transaction_velocity": states_velocity,
            "account_age": states_age,
            "ring_membership": states_ring,
            "amount_deviation": states_dev,
            "anomaly_signal": states_anomaly,
        },
    )

    model.add_cpds(cpd_velocity, cpd_age, cpd_ring, cpd_deviation, cpd_anomaly, cpd_fraud)
    assert model.check_model()
    return model


def discretize(row: dict) -> dict:
    """Map raw feature values (from account_velocity_view + risk_scores) into
    the Bayesian network's discrete states."""
    txn_count_1h = row.get("txn_count_1h", 0) or 0
    if txn_count_1h >= 6:
        velocity = "high"
    elif txn_count_1h >= 2:
        velocity = "med"
    else:
        velocity = "low"

    account_age_days = row.get("account_age_days", 999) or 999
    age = "new" if account_age_days < 30 else "established"

    ring_score = row.get("ring_membership_score", 0.0) or 0.0
    ring = "yes" if ring_score >= 0.5 else "no"

    deviation = row.get("amount_deviation_score", 0.0) or 0.0
    dev = "high" if abs(deviation) >= 2.0 else "normal"

    # anomaly_score from autoencoder (Step 5); defaults to 0.0 if absent
    anomaly = row.get("anomaly_score", 0.0) or 0.0
    anomaly_signal = "high" if anomaly >= 0.6 else "normal"

    return {
        "transaction_velocity": velocity,
        "account_age": age,
        "ring_membership": ring,
        "amount_deviation": dev,
        "anomaly_signal": anomaly_signal,
    }


def explain(model, infer: VariableElimination, row: dict) -> tuple[str, str]:
    """Returns (risk_level, plain_language_explanation)."""
    evidence = discretize(row)
    result = infer.query(variables=["fraud_risk"], evidence=evidence, show_progress=False)
    risk_level = result.state_names["fraud_risk"][int(result.values.argmax())]

    reasons = []
    if evidence["transaction_velocity"] != "low":
        reasons.append(f"{evidence['transaction_velocity']} transaction velocity")
    if evidence["account_age"] == "new":
        reasons.append("a newly opened account")
    if evidence["ring_membership"] == "yes":
        reasons.append("membership in a suspected ring")
    if evidence["amount_deviation"] == "high":
        reasons.append("an amount far outside this account's normal pattern")
    if evidence["anomaly_signal"] == "high":
        reasons.append("an anomalous behavioural signature (autoencoder)")

    if not reasons:
        explanation = "No significant risk factors detected; account behaviour is within normal bounds."
    else:
        explanation = f"Flagged ({risk_level} risk) due to " + ", ".join(reasons) + "."

    return risk_level, explanation


def explain_accounts(feature_rows: list[dict]) -> list[dict]:
    """
    feature_rows: list of dicts, each merging account_velocity_view +
    risk_scores fields for one account (see backend/services/scoring.py).
    Returns list of {account_id, risk_level, explanation}.
    """
    model = build_network()
    infer = VariableElimination(model)
    out = []
    for row in feature_rows:
        risk_level, explanation = explain(model, infer, row)
        out.append({
            "account_id": row["account_id"],
            "risk_level": risk_level,
            "explanation": explanation,
        })
    return out
