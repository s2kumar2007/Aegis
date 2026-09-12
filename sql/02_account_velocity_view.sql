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
        )                                              AS distinct_receivers_1h,

        COUNT(*) OVER (
            PARTITION BY t.sender_id
            ORDER BY t.txn_timestamp
            RANGE BETWEEN INTERVAL '2' HOUR PRECEDING AND INTERVAL '1' HOUR PRECEDING
        )                                              AS txn_count_prior_1h,

        MIN(t.txn_timestamp) OVER (
            PARTITION BY t.sender_id
            ORDER BY t.txn_timestamp
            RANGE UNBOUNDED PRECEDING
        )                                              AS first_txn_ts,
        
        -- NEW FEATURE 1: time since last transaction
        SECONDS_BETWEEN(
            t.txn_timestamp,
            LAG(t.txn_timestamp) OVER (
                PARTITION BY t.sender_id
                ORDER BY t.txn_timestamp
            )
        )                                              AS time_since_last_txn,
        
        -- NEW FEATURE 2: device/IP reuse count 
        -- Note: Assumes device_id / ip_address columns are added to transactions
        COUNT(DISTINCT t.sender_id) OVER (
            PARTITION BY COALESCE(t.device_id, t.ip_address)
        )                                              AS device_ip_reuse_count,

        -- NEW FEATURE 4: hour of day and odd hour flag
        EXTRACT(HOUR FROM t.txn_timestamp)             AS txn_hour_of_day,
        CASE
            WHEN EXTRACT(HOUR FROM t.txn_timestamp) BETWEEN 1 AND 5 THEN 1
            ELSE 0
        END                                            AS is_odd_hour

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
    
    -- Original deviation score
    CASE
        WHEN o.stddev_amount_30d IS NULL OR o.stddev_amount_30d = 0 THEN 0
        ELSE (o.amount - o.avg_amount_30d) / o.stddev_amount_30d
    END                                                AS amount_deviation_score,
    
    -- NEW FEATURE 3: amount z-score (alias for standard deviation score)
    CASE
        WHEN o.stddev_amount_30d IS NULL OR o.stddev_amount_30d = 0 THEN 0
        ELSE (o.amount - o.avg_amount_30d) / o.stddev_amount_30d
    END                                                AS amount_zscore,
    
    o.distinct_receivers_1h,
    COALESCE(i.in_txn_count_1h, 0)                     AS in_txn_count_1h,
    COALESCE(i.distinct_senders_1h, 0)                 AS distinct_senders_1h,
    
    SECONDS_BETWEEN(o.txn_timestamp, o.first_txn_ts)   AS time_since_first_txn,
    CASE
        WHEN o.avg_amount_30d IS NULL OR o.avg_amount_30d = 0 THEN 0
        ELSE o.amount / o.avg_amount_30d
    END                                                AS amount_vs_running_avg_ratio,
    (o.txn_count_1h - o.txn_count_prior_1h)            AS velocity_acceleration,
    
    -- Expose new features
    COALESCE(o.time_since_last_txn, 0)                 AS time_since_last_txn,
    o.device_ip_reuse_count,
    o.txn_hour_of_day,
    o.is_odd_hour

FROM outbound o
LEFT JOIN inbound i
       ON i.account_id = o.account_id
      AND i.in_txn_id  = o.txn_id;
