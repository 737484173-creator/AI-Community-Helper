from __future__ import annotations


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    discord_user_id TEXT NOT NULL UNIQUE,
    discord_user_name TEXT,
    player_id TEXT,
    server_id TEXT,
    created_time TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_time TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS faq (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    category TEXT NOT NULL,
    subcategory TEXT,
    question TEXT NOT NULL,
    answer TEXT NOT NULL,
    keywords TEXT,
    enabled INTEGER NOT NULL DEFAULT 1,
    created_time TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_time TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(category, question)
);

CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    discord_message_id TEXT UNIQUE,
    discord_user_id TEXT NOT NULL,
    channel_id TEXT NOT NULL,
    message_source TEXT NOT NULL DEFAULT 'CHANNEL',
    message TEXT NOT NULL,
    ai_reply TEXT,
    message_type TEXT,
    created_time TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS discord_channels (
    channel_id TEXT PRIMARY KEY,
    channel_name TEXT NOT NULL,
    channel_type TEXT,
    guild_id TEXT,
    updated_time TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS feedback (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    discord_user_id TEXT NOT NULL,
    discord_user_name TEXT,
    channel_id TEXT,
    channel_name TEXT,
    thread_title TEXT,
    content TEXT NOT NULL,
    category TEXT NOT NULL,
    feature TEXT,
    keywords TEXT,
    sentiment TEXT NOT NULL DEFAULT 'Neutral',
    priority TEXT NOT NULL DEFAULT 'Low',
    status TEXT NOT NULL DEFAULT 'Open',
    created_time TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_time TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS feedback_action_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    feedback_id INTEGER NOT NULL,
    action_type TEXT NOT NULL,
    content TEXT,
    destination_label TEXT,
    discord_channel_id TEXT,
    discord_message_id TEXT,
    created_time TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(feedback_id) REFERENCES feedback(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS pending_tickets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    discord_user_id TEXT NOT NULL,
    channel_id TEXT NOT NULL,
    ticket_source TEXT NOT NULL DEFAULT 'AI_DM_UNRESOLVED',
    original_message TEXT NOT NULL,
    selected_category TEXT,
    selected_question TEXT,
    issue_description TEXT,
    status TEXT NOT NULL DEFAULT 'Open',
    assigned_to TEXT,
    created_time TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_time TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS pending_ticket_notes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticket_id INTEGER NOT NULL,
    operator_name TEXT,
    note TEXT NOT NULL,
    created_time TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(ticket_id) REFERENCES pending_tickets(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    content TEXT NOT NULL,
    event_type TEXT NOT NULL,
    event_options_json TEXT,
    event_image_path TEXT,
    channel_id TEXT NOT NULL,
    publish_time TEXT NOT NULL,
    repeat_rule TEXT NOT NULL DEFAULT 'none',
    status TEXT NOT NULL DEFAULT 'Draft',
    discord_message_id TEXT,
    created_time TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_time TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS event_analytics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id INTEGER NOT NULL,
    published_time TEXT,
    participant_count INTEGER NOT NULL DEFAULT 0,
    reaction_count INTEGER NOT NULL DEFAULT 0,
    poll_result_json TEXT,
    created_time TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_time TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(event_id) REFERENCES events(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS reports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    report_type TEXT NOT NULL,
    title TEXT NOT NULL,
    content TEXT NOT NULL,
    start_time TEXT NOT NULL,
    end_time TEXT NOT NULL,
    created_time TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS member_applications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    discord_username TEXT NOT NULL,
    discord_user_id TEXT NOT NULL,
    raw_application TEXT NOT NULL,
    player_name TEXT,
    server_id TEXT,
    raw_server_input TEXT,
    server_name TEXT,
    discord_nickname TEXT,
    review_status TEXT NOT NULL,
    reason_code TEXT NOT NULL,
    internal_reason TEXT NOT NULL,
    rejection_reason TEXT,
    confidence REAL NOT NULL DEFAULT 0,
    auto_approvable INTEGER NOT NULL DEFAULT 0,
    processed INTEGER NOT NULL DEFAULT 0,
    reviewer TEXT,
    final_result TEXT,
    nickname_result TEXT,
    discord_api_result TEXT,
    reviewed_time TEXT,
    created_time TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_time TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS member_review_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    application_id INTEGER NOT NULL,
    discord_username TEXT,
    discord_user_id TEXT,
    raw_application TEXT,
    player_name TEXT,
    server_id TEXT,
    server_name TEXT,
    discord_nickname TEXT,
    system_status TEXT,
    final_result TEXT NOT NULL,
    rejection_reason TEXT,
    reviewer TEXT,
    nickname_result TEXT,
    discord_api_result TEXT,
    review_time TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(application_id) REFERENCES member_applications(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS player_profiles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    player_id TEXT NOT NULL,
    server_id TEXT NOT NULL,
    display_name TEXT,
    last_login_time TEXT,
    profile_json TEXT,
    created_time TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_time TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(player_id, server_id)
);

CREATE TABLE IF NOT EXISTS vip_profiles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    player_id TEXT NOT NULL,
    server_id TEXT NOT NULL,
    vip_level INTEGER,
    total_payment_amount REAL,
    last_payment_time TEXT,
    payment_summary_json TEXT,
    created_time TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_time TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(player_id, server_id)
);

CREATE TABLE IF NOT EXISTS risk_profiles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    player_id TEXT NOT NULL,
    server_id TEXT NOT NULL,
    risk_score REAL,
    risk_level TEXT,
    risk_reason_json TEXT,
    created_time TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_time TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(player_id, server_id)
);

CREATE TABLE IF NOT EXISTS vip_ae_snapshots (
    project_id INTEGER NOT NULL,
    role_id TEXT NOT NULL,
    role_name TEXT,
    server_id TEXT,
    server_name TEXT,
    last_login_time TEXT,
    total_payment_amount REAL NOT NULL DEFAULT 0,
    payment_7d_amount REAL NOT NULL DEFAULT 0,
    payment_previous_7d_amount REAL,
    payment_28d_weekly_avg REAL,
    cps_group TEXT,
    server_type TEXT NOT NULL,
    user_source TEXT NOT NULL,
    build_fp REAL,
    tech_fp REAL,
    soldier_fp REAL,
    beast_fp REAL,
    hero_fp REAL,
    hiryu_fp REAL,
    com_fp REAL,
    leg_tech_fp REAL,
    cur_fp REAL,
    synced_at TEXT NOT NULL,
    PRIMARY KEY(project_id, role_id)
);

CREATE TABLE IF NOT EXISTS vip_purchase_packages (
    project_id INTEGER NOT NULL,
    role_id TEXT NOT NULL,
    window_key TEXT NOT NULL,
    window_label TEXT,
    giftbox_id TEXT NOT NULL,
    giftbox_name TEXT,
    category TEXT NOT NULL,
    purchase_count INTEGER NOT NULL DEFAULT 0,
    payment_amount REAL NOT NULL DEFAULT 0,
    items_json TEXT NOT NULL DEFAULT '[]',
    synced_at TEXT NOT NULL,
    PRIMARY KEY(project_id, role_id, window_key, giftbox_id)
);

CREATE TABLE IF NOT EXISTS vip_ae_sync_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL,
    status TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT NOT NULL,
    source_row_count INTEGER NOT NULL DEFAULT 0,
    vip_row_count INTEGER NOT NULL DEFAULT 0,
    cumulative_window TEXT,
    weekly_window TEXT,
    previous_week_window TEXT,
    rolling_28d_window TEXT,
    purchase_source_row_count INTEGER NOT NULL DEFAULT 0,
    purchase_vip_package_count INTEGER NOT NULL DEFAULT 0,
    purchase_lifetime_window TEXT,
    purchase_recent_window TEXT,
    error_message TEXT
);

CREATE TABLE IF NOT EXISTS game_chat_messages (
    message_key TEXT PRIMARY KEY,
    project_id INTEGER NOT NULL,
    event_time TEXT NOT NULL,
    role_id TEXT NOT NULL,
    server_id TEXT,
    server_name TEXT,
    chat_content TEXT NOT NULL,
    chat_channel TEXT,
    chat_type TEXT NOT NULL DEFAULT '发言',
    risk_level TEXT,
    risk_type TEXT,
    risk_reason TEXT,
    source_event TEXT NOT NULL DEFAULT 'role_chat',
    synced_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS game_chat_sync_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL,
    status TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT NOT NULL,
    range_start TEXT NOT NULL,
    range_end TEXT NOT NULL,
    source_row_count INTEGER NOT NULL DEFAULT 0,
    matched_row_count INTEGER NOT NULL DEFAULT 0,
    active_role_count INTEGER NOT NULL DEFAULT 0,
    error_message TEXT
);

CREATE INDEX IF NOT EXISTS idx_messages_created_time ON messages(created_time);
CREATE INDEX IF NOT EXISTS idx_messages_discord_user_id ON messages(discord_user_id);
CREATE INDEX IF NOT EXISTS idx_discord_channels_guild_id ON discord_channels(guild_id);
CREATE INDEX IF NOT EXISTS idx_feedback_category ON feedback(category);
CREATE INDEX IF NOT EXISTS idx_feedback_priority ON feedback(priority);
CREATE INDEX IF NOT EXISTS idx_feedback_sentiment ON feedback(sentiment);
CREATE INDEX IF NOT EXISTS idx_feedback_action_logs_feedback_time
    ON feedback_action_logs(feedback_id, created_time DESC, id DESC);
CREATE INDEX IF NOT EXISTS idx_pending_tickets_status ON pending_tickets(status);
CREATE INDEX IF NOT EXISTS idx_pending_ticket_notes_ticket_id ON pending_ticket_notes(ticket_id);
CREATE INDEX IF NOT EXISTS idx_events_status_publish_time ON events(status, publish_time);
CREATE INDEX IF NOT EXISTS idx_reports_type_created_time ON reports(report_type, created_time);
CREATE INDEX IF NOT EXISTS idx_member_applications_status ON member_applications(review_status, processed);
CREATE INDEX IF NOT EXISTS idx_member_applications_server ON member_applications(server_id);
CREATE INDEX IF NOT EXISTS idx_member_review_logs_application_id ON member_review_logs(application_id);
CREATE INDEX IF NOT EXISTS idx_player_profiles_player_server ON player_profiles(player_id, server_id);
CREATE INDEX IF NOT EXISTS idx_vip_profiles_player_server ON vip_profiles(player_id, server_id);
CREATE INDEX IF NOT EXISTS idx_risk_profiles_player_server ON risk_profiles(player_id, server_id);
CREATE INDEX IF NOT EXISTS idx_vip_ae_snapshots_total_payment
    ON vip_ae_snapshots(project_id, total_payment_amount DESC);
CREATE INDEX IF NOT EXISTS idx_vip_ae_sync_runs_project_time
    ON vip_ae_sync_runs(project_id, finished_at DESC, id DESC);
CREATE INDEX IF NOT EXISTS idx_vip_purchase_packages_role_window
    ON vip_purchase_packages(project_id, role_id, window_key, payment_amount DESC);
CREATE INDEX IF NOT EXISTS idx_game_chat_messages_project_time
    ON game_chat_messages(project_id, event_time DESC);
CREATE INDEX IF NOT EXISTS idx_game_chat_messages_project_server_time
    ON game_chat_messages(project_id, server_id, event_time DESC);
CREATE INDEX IF NOT EXISTS idx_game_chat_messages_project_risk_time
    ON game_chat_messages(project_id, risk_level, event_time DESC);
CREATE INDEX IF NOT EXISTS idx_game_chat_messages_project_role_time
    ON game_chat_messages(project_id, role_id, event_time DESC);
CREATE INDEX IF NOT EXISTS idx_game_chat_sync_runs_project_time
    ON game_chat_sync_runs(project_id, finished_at DESC, id DESC);
"""
