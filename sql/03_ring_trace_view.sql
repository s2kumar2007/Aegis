-- =====================================================================
-- ring_trace_view
--
-- Purpose: trace multi-hop money-movement paths (A -> B -> C -> D -> ...)
-- up to depth 5, entirely inside Exasol via a recursive CTE. This is
-- the SQL-native equivalent of graph traversal, used to surface
-- layering / mule-chain candidates before they ever reach Python.
--
-- Output columns:
--   root_account_id : the account where the traced chain began
--   hop_no          : 1..5, position in the chain
--   account_id      : account at this hop (the receiver of that hop's txn)
--   txn_id          : the transaction that produced this hop
--   amount          : amount moved on this hop
--   hop_timestamp   : when this hop occurred
--   path            : human-readable "A->B->C" trail so far
--
-- Guardrails against cycles / explosion:
--   - each hop's timestamp must be >= previous hop's timestamp (money
--     can only move forward in time)
--   - an account cannot reappear later in the same path (no revisits)
--   - capped at MAX_DEPTH = 5 hops
-- =====================================================================

OPEN SCHEMA AEGIS;

CREATE OR REPLACE VIEW ring_trace_view AS
WITH RECURSIVE money_trail (
    root_account_id,
    hop_no,
    account_id,
    txn_id,
    amount,
    hop_timestamp,
    path,
    visited
) AS (
    -- Anchor: every transaction is a potential start of a chain
    SELECT
        t.sender_id                                   AS root_account_id,
        1                                              AS hop_no,
        t.receiver_id                                 AS account_id,
        t.txn_id,
        t.amount,
        t.txn_timestamp                               AS hop_timestamp,
        t.sender_id || '->' || t.receiver_id          AS path,
        '|' || t.sender_id || '|' || t.receiver_id || '|' AS visited
    FROM transactions t

    UNION ALL

    -- Recursive step: extend the chain by one more hop
    SELECT
        m.root_account_id,
        m.hop_no + 1                                  AS hop_no,
        t.receiver_id                                 AS account_id,
        t.txn_id,
        t.amount,
        t.txn_timestamp                               AS hop_timestamp,
        m.path || '->' || t.receiver_id               AS path,
        m.visited || t.receiver_id || '|'             AS visited
    FROM money_trail m
    JOIN transactions t
      ON t.sender_id = m.account_id
     AND t.txn_timestamp >= m.hop_timestamp            -- forward in time only
    WHERE m.hop_no < 5
      AND m.visited NOT LIKE '%|' || t.receiver_id || '|%'  -- no revisits (no trivial cycles)
)
SELECT
    root_account_id,
    hop_no,
    account_id,
    txn_id,
    amount,
    hop_timestamp,
    path
FROM money_trail
WHERE hop_no >= 3;   -- only surface chains of length >=3 (A->B->C or longer): candidate layering/mule paths
