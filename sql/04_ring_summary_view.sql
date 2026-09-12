CREATE OR REPLACE VIEW ring_summary_view AS
WITH ranked AS (
    SELECT
        *,
        ROW_NUMBER() OVER (PARTITION BY root_account_id ORDER BY hop_no DESC) AS rn
    FROM ring_trace_view
)
SELECT
    root_account_id,
    COUNT(DISTINCT account_id)               AS accounts_touched,
    COUNT(DISTINCT txn_id)                   AS hops_total,
    MAX(hop_no)                              AS max_depth,
    SUM(amount)                              AS total_amount_moved,
    MIN(hop_timestamp)                       AS chain_start,
    MAX(hop_timestamp)                       AS chain_end,
    MAX(CASE WHEN rn = 1 THEN route END)     AS sample_route
FROM ranked
GROUP BY root_account_id
HAVING COUNT(DISTINCT account_id) >= 3   -- at least a 3-account chain to call it a "ring candidate"
ORDER BY total_amount_moved DESC
