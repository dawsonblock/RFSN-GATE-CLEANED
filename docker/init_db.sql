-- RFSN Controller Database Schema
-- PostgreSQL 16+

-- =============================================================================
-- Action Outcomes: Stores bandit learning data
-- =============================================================================
CREATE TABLE IF NOT EXISTS action_outcomes (
    id SERIAL PRIMARY KEY,
    context_hash VARCHAR(64) NOT NULL,
    action_type VARCHAR(50) NOT NULL,
    action_json JSONB NOT NULL,
    outcome VARCHAR(20) NOT NULL,  -- 'success', 'failure', 'regression', 'partial'
    score FLOAT NOT NULL,
    timestamp TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    metadata JSONB
);

CREATE INDEX IF NOT EXISTS idx_ao_context_hash ON action_outcomes(context_hash);
CREATE INDEX IF NOT EXISTS idx_ao_action_type ON action_outcomes(action_type);
CREATE INDEX IF NOT EXISTS idx_ao_outcome ON action_outcomes(outcome);
CREATE INDEX IF NOT EXISTS idx_ao_timestamp ON action_outcomes(timestamp DESC);

-- =============================================================================
-- Repair Sessions: Tracks repair session history
-- =============================================================================
CREATE TABLE IF NOT EXISTS repair_sessions (
    id SERIAL PRIMARY KEY,
    session_id UUID NOT NULL UNIQUE,
    repo_url TEXT NOT NULL,
    test_command TEXT,
    start_time TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    end_time TIMESTAMP,
    status VARCHAR(20) NOT NULL,  -- 'running', 'success', 'failed', 'timeout'
    config JSONB NOT NULL,
    result JSONB,
    patches_applied INT DEFAULT 0,
    tokens_used INT DEFAULT 0,
    cost_usd FLOAT DEFAULT 0.0
);

CREATE INDEX IF NOT EXISTS idx_rs_session_id ON repair_sessions(session_id);
CREATE INDEX IF NOT EXISTS idx_rs_start_time ON repair_sessions(start_time DESC);
CREATE INDEX IF NOT EXISTS idx_rs_status ON repair_sessions(status);

-- =============================================================================
-- Beam Search History: Tracks beam search exploration
-- =============================================================================
CREATE TABLE IF NOT EXISTS beam_search_history (
    id SERIAL PRIMARY KEY,
    session_id UUID NOT NULL,
    step INT NOT NULL,
    candidate_id VARCHAR(64) NOT NULL,
    parent_id VARCHAR(64),
    score FLOAT NOT NULL,
    patches_applied INT NOT NULL,
    tests_passed BOOLEAN NOT NULL,
    strategy VARCHAR(50),
    metadata JSONB,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (session_id) REFERENCES repair_sessions(session_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_bsh_session ON beam_search_history(session_id);
CREATE INDEX IF NOT EXISTS idx_bsh_step ON beam_search_history(session_id, step);

-- =============================================================================
-- Strategy Statistics: Bandit learning stats per strategy
-- =============================================================================
CREATE TABLE IF NOT EXISTS strategy_stats (
    id SERIAL PRIMARY KEY,
    strategy_name VARCHAR(100) NOT NULL UNIQUE,
    alpha FLOAT NOT NULL DEFAULT 1.0,  -- Beta distribution param (successes + 1)
    beta FLOAT NOT NULL DEFAULT 1.0,   -- Beta distribution param (failures + 1)
    pulls INT NOT NULL DEFAULT 0,      -- Total times selected
    wins INT NOT NULL DEFAULT 0,       -- Successful repairs
    total_reward FLOAT NOT NULL DEFAULT 0.0,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_ss_strategy ON strategy_stats(strategy_name);

-- =============================================================================
-- Quarantine: Tracks quarantined (blocked) strategies
-- =============================================================================
CREATE TABLE IF NOT EXISTS quarantine (
    id SERIAL PRIMARY KEY,
    strategy_name VARCHAR(100) NOT NULL UNIQUE,
    consecutive_failures INT NOT NULL DEFAULT 0,
    quarantined_until TIMESTAMP,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_q_strategy ON quarantine(strategy_name);
CREATE INDEX IF NOT EXISTS idx_q_until ON quarantine(quarantined_until);

-- =============================================================================
-- Negative Memory: Context-specific failure patterns to avoid
-- =============================================================================
CREATE TABLE IF NOT EXISTS negative_memory (
    id SERIAL PRIMARY KEY,
    context_hash VARCHAR(64) NOT NULL,
    strategy_name VARCHAR(100) NOT NULL,
    failure_count INT NOT NULL DEFAULT 1,
    last_failure_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    metadata JSONB,
    UNIQUE(context_hash, strategy_name)
);

CREATE INDEX IF NOT EXISTS idx_nm_context ON negative_memory(context_hash);
CREATE INDEX IF NOT EXISTS idx_nm_strategy ON negative_memory(strategy_name);

-- =============================================================================
-- LLM Usage: Token and cost tracking
-- =============================================================================
CREATE TABLE IF NOT EXISTS llm_usage (
    id SERIAL PRIMARY KEY,
    session_id UUID,
    model VARCHAR(50) NOT NULL,
    prompt_tokens INT NOT NULL,
    completion_tokens INT NOT NULL,
    cost_usd FLOAT NOT NULL,
    latency_ms FLOAT NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_lu_session ON llm_usage(session_id);
CREATE INDEX IF NOT EXISTS idx_lu_model ON llm_usage(model);
CREATE INDEX IF NOT EXISTS idx_lu_created ON llm_usage(created_at DESC);

-- =============================================================================
-- Views for common queries
-- =============================================================================

-- Strategy performance summary
CREATE OR REPLACE VIEW v_strategy_performance AS
SELECT 
    strategy_name,
    wins,
    pulls,
    CASE WHEN pulls > 0 THEN ROUND((wins::float / pulls * 100)::numeric, 2) ELSE 0 END as success_rate,
    ROUND((alpha / (alpha + beta))::numeric, 4) as thompson_mean,
    total_reward,
    updated_at
FROM strategy_stats
ORDER BY success_rate DESC, pulls DESC;

-- Session summary
CREATE OR REPLACE VIEW v_session_summary AS
SELECT 
    DATE_TRUNC('day', start_time) as day,
    COUNT(*) as total_sessions,
    COUNT(CASE WHEN status = 'success' THEN 1 END) as successful,
    COUNT(CASE WHEN status = 'failed' THEN 1 END) as failed,
    ROUND(AVG(EXTRACT(EPOCH FROM (end_time - start_time)))::numeric, 2) as avg_duration_seconds,
    SUM(tokens_used) as total_tokens,
    SUM(cost_usd) as total_cost
FROM repair_sessions
WHERE end_time IS NOT NULL
GROUP BY DATE_TRUNC('day', start_time)
ORDER BY day DESC;
