"""
AEGIS synthetic UPI transaction generator.

Produces:
  - accounts            (normal population + accounts belonging to planted rings)
  - transactions        (normal P2P/P2M noise + planted fraud-ring transactions)
  - fraud_labels        (ground truth linking planted txns to a ring_id/pattern_type)

Planted patterns:
  - smurfing : one source account splits a large sum into many small transfers
               to many distinct receiver ("smurf") accounts in a short window.
  - layering : funds are routed through a chain of 3-5 mule accounts,
               A -> B -> C -> D -> E, each hop shrinking slightly (fees/cash-out).
  - mule     : a fan-in/fan-out cluster — many senders funnel into one mule
               account, which then fans back out to many receivers.

All rows are written straight into Exasol tables (accounts, transactions,
fraud_labels) — no intermediate CSVs required, though a CSV/JSON snapshot
is also written to /app/simulation/seed_data/ for convenience & the
timestamp-ordered replay mode used by the live demo.
"""
import os
import json
import random
import string
import argparse
from datetime import datetime, timedelta

import pandas as pd
from faker import Faker

from exasol_conn import get_connection, run_sql_file

fake = Faker("en_IN")
random.seed(42)
Faker.seed(42)

BANKS = ["SBI", "HDFC", "ICICI", "Axis", "PNB", "Kotak", "BOB", "Paytm Payments Bank"]
CHANNELS = ["UPI_APP", "QR", "INTENT"]
TXN_TYPES = ["P2P", "P2M", "REFUND"]

SIM_START = datetime(2026, 8, 1, 8, 0, 0)


def _id(prefix: str, n: int) -> str:
    return f"{prefix}{n:07d}"


def make_account(account_id: str, opened_days_ago: int, kyc_tier: str = None) -> dict:
    opened_at = SIM_START - timedelta(days=opened_days_ago)
    return {
        "account_id": account_id,
        "vpa": f"{fake.user_name()}@{random.choice(['okhdfcbank','oksbi','okicici','okaxis','ybl'])}",
        "bank_name": random.choice(BANKS),
        "account_age_days": opened_days_ago,
        "kyc_tier": kyc_tier or random.choices(["full", "minimal", "none"], weights=[0.75, 0.2, 0.05])[0],
        "opened_at": opened_at,
    }


def gen_normal_population(n_accounts: int):
    accounts = [make_account(_id("ACC", i), random.randint(30, 2000)) for i in range(n_accounts)]
    return accounts


def gen_normal_transactions(accounts: list, n_txns: int, txn_counter: list):
    ids = [a["account_id"] for a in accounts]
    txns = []
    for _ in range(n_txns):
        sender, receiver = random.sample(ids, 2)
        ts = SIM_START + timedelta(
            hours=random.uniform(0, 24 * 6),
            minutes=random.uniform(0, 60),
        )
        txns.append({
            "txn_id": _id("TXN", txn_counter[0]),
            "sender_id": sender,
            "receiver_id": receiver,
            "amount": round(random.lognormvariate(6.5, 1.0), 2),  # skewed small amounts, occasional big ones
            "txn_type": random.choices(TXN_TYPES, weights=[0.7, 0.25, 0.05])[0],
            "txn_timestamp": ts,
            "channel": random.choice(CHANNELS),
        })
        txn_counter[0] += 1
    return txns


def plant_smurfing_ring(ring_no: int, txn_counter: list, base_time: datetime):
    """One source splits a large sum into many small transfers to fresh smurf accounts."""
    ring_id = f"RING_SMURF_{ring_no:03d}"
    source = make_account(_id("MULE", 10000 + ring_no * 100), random.randint(5, 40), kyc_tier="minimal")
    n_smurfs = random.randint(5, 25)
    smurfs = [make_account(_id("MULE", 10001 + ring_no * 100 + i), random.randint(1, 15), kyc_tier="none")
              for i in range(n_smurfs)]
    total = random.uniform(150000, 400000)
    per_txn = total / n_smurfs

    accounts = [source] + smurfs
    txns, labels = [], []
    for i, smurf in enumerate(smurfs):
        ts = base_time + timedelta(minutes=random.uniform(0, 25))  # tight burst window
        txn_id = _id("TXN", txn_counter[0])
        txns.append({
            "txn_id": txn_id,
            "sender_id": source["account_id"],
            "receiver_id": smurf["account_id"],
            "amount": round(per_txn * random.uniform(0.85, 1.15), 2),
            "txn_type": "P2P",
            "txn_timestamp": ts,
            "channel": "UPI_APP",
        })
        labels.append({"txn_id": txn_id, "ring_id": ring_id, "pattern_type": "smurfing", "is_planted": True})
        txn_counter[0] += 1
    return accounts, txns, labels


def plant_layering_chain(ring_no: int, txn_counter: list, base_time: datetime):
    """Funds routed through 3-5 mule accounts, shrinking slightly each hop (cash-out fee)."""
    ring_id = f"RING_LAYER_{ring_no:03d}"
    chain_len = random.randint(3, 8)  # A -> ... -> chain_len accounts total, 2-7 hops
    chain_accounts = [make_account(_id("MULE", 20000 + ring_no * 100 + i), random.randint(2, 20), kyc_tier="minimal")
                       for i in range(chain_len)]
    amount = random.uniform(80000, 250000)
    ts = base_time
    txns, labels = [], []
    for i in range(chain_len - 1):
        amount *= random.uniform(0.90, 0.97)  # small skim at each hop
        ts = ts + timedelta(minutes=random.uniform(10, 90))
        txn_id = _id("TXN", txn_counter[0])
        txns.append({
            "txn_id": txn_id,
            "sender_id": chain_accounts[i]["account_id"],
            "receiver_id": chain_accounts[i + 1]["account_id"],
            "amount": round(amount, 2),
            "txn_type": "P2P",
            "txn_timestamp": ts,
            "channel": "UPI_APP",
        })
        labels.append({"txn_id": txn_id, "ring_id": ring_id, "pattern_type": "layering", "is_planted": True})
        txn_counter[0] += 1
    return chain_accounts, txns, labels


def plant_mule_fan(ring_no: int, txn_counter: list, base_time: datetime):
    """Fan-in/fan-out: many senders -> one mule hub -> many receivers."""
    ring_id = f"RING_MULE_{ring_no:03d}"
    hub = make_account(_id("MULE", 30000 + ring_no * 1000), random.randint(3, 25), kyc_tier="minimal")
    n_in = random.randint(3, 15)
    n_out = random.randint(3, 15)
    senders = [make_account(_id("MULE", 30001 + ring_no * 1000 + i), random.randint(30, 500)) for i in range(n_in)]
    receivers = [make_account(_id("MULE", 30500 + ring_no * 1000 + i), random.randint(1, 10), kyc_tier="none")
                 for i in range(n_out)]

    accounts = [hub] + senders + receivers
    txns, labels = [], []
    pooled = 0.0
    t = base_time
    for s in senders:
        amt = random.uniform(8000, 30000)
        pooled += amt
        t = t + timedelta(minutes=random.uniform(1, 20))
        txn_id = _id("TXN", txn_counter[0])
        txns.append({
            "txn_id": txn_id, "sender_id": s["account_id"], "receiver_id": hub["account_id"],
            "amount": round(amt, 2), "txn_type": "P2P", "txn_timestamp": t, "channel": "UPI_APP",
        })
        labels.append({"txn_id": txn_id, "ring_id": ring_id, "pattern_type": "mule", "is_planted": True})
        txn_counter[0] += 1

    per_out = pooled / n_out
    for r in receivers:
        t = t + timedelta(minutes=random.uniform(5, 30))
        txn_id = _id("TXN", txn_counter[0])
        txns.append({
            "txn_id": txn_id, "sender_id": hub["account_id"], "receiver_id": r["account_id"],
            "amount": round(per_out * random.uniform(0.8, 1.1), 2), "txn_type": "P2P",
            "txn_timestamp": t, "channel": "UPI_APP",
        })
        labels.append({"txn_id": txn_id, "ring_id": ring_id, "pattern_type": "mule", "is_planted": True})
        txn_counter[0] += 1
    return accounts, txns, labels


def build_dataset(n_normal_accounts=4500, n_normal_txns=50000,
                   n_smurf_rings=15, n_layer_rings=15, n_mule_rings=10):
    txn_counter = [1]
    all_accounts = gen_normal_population(n_normal_accounts)
    all_txns = gen_normal_transactions(all_accounts, n_normal_txns, txn_counter)
    all_labels = []

    ring_time_cursor = SIM_START + timedelta(hours=12)
    for i in range(n_smurf_rings):
        accs, txns, labels = plant_smurfing_ring(i, txn_counter, ring_time_cursor)
        all_accounts += accs; all_txns += txns; all_labels += labels
        ring_time_cursor += timedelta(hours=random.uniform(8, 20))

    for i in range(n_layer_rings):
        accs, txns, labels = plant_layering_chain(i, txn_counter, ring_time_cursor)
        all_accounts += accs; all_txns += txns; all_labels += labels
        ring_time_cursor += timedelta(hours=random.uniform(8, 20))

    for i in range(n_mule_rings):
        accs, txns, labels = plant_mule_fan(i, txn_counter, ring_time_cursor)
        all_accounts += accs; all_txns += txns; all_labels += labels
        ring_time_cursor += timedelta(hours=random.uniform(8, 20))

    accounts_df = pd.DataFrame(all_accounts).drop_duplicates(subset="account_id")
    txns_df = pd.DataFrame(all_txns).sort_values("txn_timestamp").reset_index(drop=True)
    labels_df = pd.DataFrame(all_labels)

    return accounts_df, txns_df, labels_df


def load_into_exasol(accounts_df, txns_df, labels_df):
    conn = get_connection()
    print("[generate_data] running schema + view SQL...")
    for f in ["sql/01_schema.sql", "sql/02_account_velocity_view.sql",
              "sql/03_ring_trace_view.sql", "sql/04_ring_summary_view.sql"]:
        run_sql_file(conn, f)

    print(f"[generate_data] loading {len(accounts_df)} accounts...")
    conn.import_from_pandas(accounts_df, "accounts")

    print(f"[generate_data] loading {len(txns_df)} transactions...")
    conn.import_from_pandas(txns_df, "transactions")

    print(f"[generate_data] loading {len(labels_df)} fraud labels...")
    conn.import_from_pandas(labels_df, "fraud_labels")

    conn.close()
    print("[generate_data] done.")


def save_seed_snapshot(accounts_df, txns_df, labels_df, out_dir="seed_data"):
    os.makedirs(out_dir, exist_ok=True)
    accounts_df.to_csv(f"{out_dir}/accounts.csv", index=False)
    txns_df.to_csv(f"{out_dir}/transactions.csv", index=False)
    labels_df.to_csv(f"{out_dir}/fraud_labels.csv", index=False)
    # replay manifest: ordered list of txn_ids with timestamps, used by
    # POST /simulate/replay to step through history at demo speed
    replay = txns_df[["txn_id", "txn_timestamp"]].sort_values("txn_timestamp")
    replay.to_json(f"{out_dir}/replay_manifest.json", orient="records", date_format="iso")
    print(f"[generate_data] seed snapshot written to {out_dir}/")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-load", action="store_true", help="only generate CSVs, don't write to Exasol")
    args = parser.parse_args()

    accounts_df, txns_df, labels_df = build_dataset()
    save_seed_snapshot(accounts_df, txns_df, labels_df)

    if not args.skip_load:
        load_into_exasol(accounts_df, txns_df, labels_df)
    else:
        print("[generate_data] --skip-load set; CSVs written only.")
