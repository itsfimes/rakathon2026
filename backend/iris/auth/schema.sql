-- ADMINISTRATIVE ARTIFACT ONLY. Execute in USER only after ownership review.
-- Stop on ANY existing table/index or error. Never DROP, TRUNCATE, or replace.
-- No runtime endpoint or Python startup executes this file.
CREATE TABLE FSB.AuthUsers (
    user_id VARCHAR(64) PRIMARY KEY,
    username_index VARCHAR(128) UNIQUE,
    password_hash VARCHAR(512),
    enc_nonce VARCHAR(64),
    enc_ct VARCHAR(1024),
    key_id VARCHAR(64),
    role VARCHAR(32),
    active VARCHAR(4),
    auth_version INT,
    created_at BIGINT,
    updated_at BIGINT
);
CREATE TABLE FSB.AuthSessions (
    token_hash VARCHAR(128) PRIMARY KEY,
    user_id VARCHAR(64),
    auth_version INT,
    role VARCHAR(32),
    created_at BIGINT,
    last_seen BIGINT,
    expires_at BIGINT
);
CREATE TABLE FSB.AuthRate (
    scope VARCHAR(16),
    key VARCHAR(256),
    slot INT,
    ts BIGINT,
    reservation_id VARCHAR(64),
    PRIMARY KEY (scope, key, slot)
);
