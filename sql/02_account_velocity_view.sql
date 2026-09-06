-- =====================================================================
-- account_velocity_view
--
-- Purpose: per-account rolling-window transaction behaviour, computed
-- ENTIRELY inside Exasol using analytic window functions. This feeds
-- the baseline classifier directly — the backend SELECTs from this
-- view, it never recomputes these aggregates in pandas.
--
-- Windows:
--   - 1 hour   : burst detection (smurfing / fan-out bursts)
--   - 24 hour  : daily velocity
--   - 30 day   : historical baseline for deviation scoring
-- =====================================================================

OPEN SCHEMA AEGIS;

CREATE OR REPLACE VIEW account_velocity_view AS
WITH outbound AS (
    SELECT
        t.sender_id                                   AS account_id,
        t.txn_id,
        t.amount,
        t.txn_timestamp,

        -- rolling counts / sums per account over trailing windows,
        -- expressed as row-range window functions over time order
        COUNT(*) OVER (
            PARTITION BY t.sender_id
            ORDER BY t.txn_timestamp
            RANGE BETWEEN INTERVAL '1' HOUR PRECEDING AND CURRENT ROW
        )                                              AS txn_count_1h,

        SUM(t.amount) OVER (
            PARTITION BY t.sender_id
            ORDER BY t.txn_timestamp
            RANGE BETWEEN INTERVAL '1' HOUR PRECEDING AND CURRENT ROW
        )                                              AS txn_sum_1h,

        COUNT(*) OVER (
            PARTITION BY t.sender_id
            ORDER BY t.txn_timestamp
            RANGE BETWEEN INTERVAL '24' HOUR PRECEDING AND CURRENT ROW
        )                                              AS txn_count_24h,

        SUM(t.amount) OVER (
            PARTITION BY t.sender_id
            ORDER BY t.txn_timestamp
            RANGE BETWEEN INTERVAL '24' HOUR PRECEDING AND CURRENT ROW
        )                                              AS txn_sum_24h,

        AVG(t.amount) OVER (
            PARTITION BY t.sender_id
            ORDER BY t.txn_timestamp
            RANGE BETWEEN INTERVAL '30' DAY PRECEDING AND CURRENT ROW
        )                                              AS avg_amount_30d,

        STDDEV_POP(t.amount) OVER (
            PARTITION BY t.sender_id
            ORDER BY t.txn_timestamp
            RANGE BETWEEN INTERVAL '30' DAY PRECEDING AND CURRENT ROW
        )                                              AS stddev_amount_30d,

        -- distinct counterparties in the last hour -> fan-out signal
        COUNT(DISTINCT t.receiver_id) OVER (
            PARTITION BY t.sender_id
            ORDER BY t.txn_timestamp
            RANGE BETWEEN INTERVAL '1' HOUR PRECEDING AND CURRENT ROW
        )                                              AS distinct_receivers_1h

    FROM transactions t
),
inbound AS (
    SELECT
        t.receiver_id                                 AS account_id,
        COUNT(*) OVER (
            PARTITION BY t.receiver_id
            ORDER BY t.txn_timestamp
            RANGE BETWEEN INTERVAL '1' HOUR PRECEDING AND CURRENT ROW
        )                                              AS in_txn_count_1h,
        COUNT(DISTINCT t.sender_id) OVER (
            PARTITION BY t.receiver_id
            ORDER BY t.txn_timestamp
            RANGE BETWEEN INTERVAL '1' HOUR PRECEDING AND CURRENT ROW
        )                                              AS distinct_senders_1h,   -- fan-in signal
        t.txn_id                                       AS in_txn_id
    FROM transactions t
)
SELECT
    o.account_id,
    o.txn_id,
    o.txn_timestamp,
    o.amount,
    o.txn_count_1h,
    o.txn_sum_1h,
    o.txn_count_24h,
    o.txn_sum_24h,
    o.avg_amount_30d,
    o.stddev_amount_30d,
    -- z-score style deviation of this txn amount from the account's own 30d baseline
    CASE
        WHEN o.stddev_amount_30d IS NULL OR o.stddev_amount_30d = 0 THEN 0
        ELSE (o.amount - o.avg_amount_30d) / o.stddev_amount_30d
    END                                                AS amount_deviation_score,
    o.distinct_receivers_1h,
    COALESCE(i.in_txn_count_1h, 0)                     AS in_txn_count_1h,
    COALESCE(i.distinct_senders_1h, 0)                 AS distinct_senders_1h
FROM outbound o
LEFT JOIN inbound i
       ON i.account_id = o.account_id
      AND i.in_txn_id  = o.txn_id;
