CREATE OR REPLACE VIEW ring_trace_view AS
SELECT * FROM (
    SELECT
        CONNECT_BY_ROOT sender_id                          AS root_account_id,
        LEVEL                                               AS hop_no,
        receiver_id                                         AS account_id,
        txn_id,
        amount,
        txn_timestamp                                       AS hop_timestamp,
        SYS_CONNECT_BY_PATH(receiver_id, '->')              AS route
    FROM transactions
    CONNECT BY NOCYCLE
        PRIOR receiver_id = sender_id
        AND LEVEL <= 5
)
WHERE hop_no >= 3
