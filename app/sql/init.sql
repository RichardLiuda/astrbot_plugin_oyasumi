CREATE TABLE IF NOT EXISTS sleep_session (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL,
    sleep_time DATETIME,
    wake_time DATETIME,
    status TEXT NOT NULL CHECK(status IN ('open', 'closed', 'abandoned')),
    source TEXT NOT NULL CHECK(source IN ('regex', 'manual_edit', 'api', 'auto_fill')),
    is_auto_filled INTEGER NOT NULL DEFAULT 0,
    auto_fill_reason TEXT,
    created_at DATETIME NOT NULL DEFAULT (datetime('now', 'localtime')),
    updated_at DATETIME NOT NULL DEFAULT (datetime('now', 'localtime'))
);

CREATE TABLE IF NOT EXISTS sleep_event (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL,
    event_type TEXT NOT NULL CHECK(event_type IN ('good_morning', 'good_night', 'manual_edit')),
    event_time DATETIME NOT NULL,
    matched_pattern TEXT,
    raw_message TEXT,
    session_id INTEGER,
    event_status TEXT NOT NULL DEFAULT 'processed',
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at DATETIME NOT NULL DEFAULT (datetime('now', 'localtime')),
    FOREIGN KEY(session_id) REFERENCES sleep_session(id)
);

CREATE INDEX IF NOT EXISTS idx_sleep_session_user_status
ON sleep_session(user_id, status);

CREATE INDEX IF NOT EXISTS idx_sleep_session_user_sleep_time
ON sleep_session(user_id, sleep_time);

CREATE INDEX IF NOT EXISTS idx_sleep_event_user_time
ON sleep_event(user_id, event_time);

CREATE INDEX IF NOT EXISTS idx_sleep_event_user_type_status
ON sleep_event(user_id, event_type, event_status);
