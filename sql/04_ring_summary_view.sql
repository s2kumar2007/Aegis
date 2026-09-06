-- =====================================================================
-- ring_summary_view
--
-- Aggregates ring_trace_view chains per root_account_id into a
-- ring-candidate summary: distinct accounts touched, total amount
-- moved, max depth reached, and time span. This is the SQL source
-- for the frontend's "case file" panel and GET /rings endpoint.
-- =====================================================================

OPEN SCHEMA AEGIS;

CREATE OR REPLACE VIEW ring_summary_view AS
SELECT
    root_account_id,
    COUNT(DISTINCT account_id)               AS accounts_touched,
    COUNT(DISTINCT txn_id)                   AS hops_total,
    MAX(hop_no)                              AS max_depth,
    SUM(amount)                              AS total_amount_moved,
    MIN(hop_timestamp)                       AS chain_start,
    MAX(hop_timestamp)                       AS chain_end,
    -- longest observed path string, useful for display
    (SELECT rt2.path
       FROM ring_trace_view rt2
      WHERE rt2.root_account_id = rt.root_account_id
      ORDER BY rt2.hop_no DESC
      LIMIT 1)                               AS sample_path
FROM ring_trace_view rt
GROUP BY root_account_id
HAVING COUNT(DISTINCT account_id) >= 3   -- at least a 3-account chain to call it a "ring candidate"
ORDER BY total_amount_moved DESC;
