-- =====================================================================
-- AEGIS — Exasol schema
-- All tables that back the fraud-detection pipeline.
-- =====================================================================

CREATE SCHEMA IF NOT EXISTS AEGIS;
OPEN SCHEMA AEGIS;

-- ---------------------------------------------------------------------
-- accounts
-- ---------------------------------------------------------------------
CREATE OR REPLACE TABLE accounts (
    account_id        VARCHAR(64)   NOT NULL,
    vpa               VARCHAR(128),
    bank_name         VARCHAR(64),
    account_age_days  INTEGER,
    kyc_tier          VARCHAR(16),   -- 'full' | 'minimal' | 'none'
    opened_at         TIMESTAMP,
    PRIMARY KEY (account_id)
);

-- ---------------------------------------------------------------------
-- transactions
-- ---------------------------------------------------------------------
CREATE OR REPLACE TABLE transactions (
    txn_id       VARCHAR(64)     NOT NULL,
    sender_id    VARCHAR(64)     NOT NULL,
    receiver_id  VARCHAR(64)     NOT NULL,
    amount       DECIMAL(18,2)   NOT NULL,
    txn_type     VARCHAR(32),     -- P2P | P2M | REFUND
    txn_timestamp TIMESTAMP      NOT NULL,
    channel      VARCHAR(32),     -- UPI_APP | QR | INTENT
    PRIMARY KEY (txn_id)
);

-- ---------------------------------------------------------------------
-- fraud_labels  (ground truth for planted rings — used for evaluation
-- and for the demo narrative, never fed to the model as a feature)
-- ---------------------------------------------------------------------
CREATE OR REPLACE TABLE fraud_labels (
    txn_id        VARCHAR(64)  NOT NULL,
    ring_id       VARCHAR(64),
    pattern_type  VARCHAR(32),   -- layering | smurfing | mule
    is_planted    BOOLEAN,
    PRIMARY KEY (txn_id)
);

-- ---------------------------------------------------------------------
-- risk_scores  (written by the ML layer, read by the API/frontend)
-- ---------------------------------------------------------------------
CREATE OR REPLACE TABLE risk_scores (
    account_id           VARCHAR(64)   NOT NULL,
    model_score           DOUBLE,        -- baseline XGBoost probability
    ring_membership_score DOUBLE,        -- GNN / community-detection score
    explanation           VARCHAR(2000), -- plain-language Bayesian explanation
    flagged_at             TIMESTAMP,
    PRIMARY KEY (account_id)
);

-- ---------------------------------------------------------------------
-- adaptation_log  (adaptive loop, step 6)
-- ---------------------------------------------------------------------
CREATE OR REPLACE TABLE adaptation_log (
    event_id      VARCHAR(64)  NOT NULL,
    ring_id       VARCHAR(64),
    detected_at   TIMESTAMP,
    old_threshold DOUBLE,
    new_threshold DOUBLE,
    note          VARCHAR(1000),
    PRIMARY KEY (event_id)
);
