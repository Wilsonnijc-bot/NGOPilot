BEGIN;

SELECT pg_advisory_xact_lock(hashtext('ngopilot_schema_migrations'));

CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE IF NOT EXISTS schema_migrations (
    version INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email_normalized TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    display_name TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    disabled_at TIMESTAMPTZ,
    CONSTRAINT users_email_normalized CHECK (
        email_normalized = lower(btrim(email_normalized))
        AND char_length(email_normalized) BETWEEN 3 AND 320
    ),
    CONSTRAINT users_password_hash_bounded CHECK (
        octet_length(password_hash) BETWEEN 20 AND 512
    ),
    CONSTRAINT users_display_name_bounded CHECK (
        display_name IS NULL OR char_length(display_name) <= 120
    )
);

CREATE TABLE auth_sessions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    token_hash BYTEA NOT NULL UNIQUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at TIMESTAMPTZ NOT NULL,
    last_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    revoked_at TIMESTAMPTZ,
    CONSTRAINT auth_sessions_token_hash_sha256 CHECK (
        octet_length(token_hash) = 32
    ),
    CONSTRAINT auth_sessions_expiry CHECK (expires_at > created_at),
    CONSTRAINT auth_sessions_owner_id_unique UNIQUE (user_id, id)
);

CREATE INDEX auth_sessions_active_by_user_idx
    ON auth_sessions (user_id, expires_at DESC)
    WHERE revoked_at IS NULL;
CREATE INDEX auth_sessions_expiry_idx
    ON auth_sessions (expires_at)
    WHERE revoked_at IS NULL;

CREATE TABLE chat_sessions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    agent_session_id TEXT NOT NULL,
    title TEXT NOT NULL DEFAULT 'New chat',
    status TEXT NOT NULL DEFAULT 'active',
    model TEXT NOT NULL,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    archived_at TIMESTAMPTZ,
    deleted_at TIMESTAMPTZ,
    CONSTRAINT chat_sessions_agent_id_bounded CHECK (
        char_length(agent_session_id) BETWEEN 1 AND 256
    ),
    CONSTRAINT chat_sessions_title_bounded CHECK (
        char_length(title) BETWEEN 1 AND 200
    ),
    CONSTRAINT chat_sessions_status_bounded CHECK (
        char_length(status) BETWEEN 1 AND 32
    ),
    CONSTRAINT chat_sessions_model_bounded CHECK (
        char_length(model) BETWEEN 1 AND 200
    ),
    CONSTRAINT chat_sessions_metadata_object CHECK (
        jsonb_typeof(metadata) = 'object'
        AND octet_length(metadata::text) <= 16384
    ),
    CONSTRAINT chat_sessions_owner_id_unique UNIQUE (user_id, id),
    CONSTRAINT chat_sessions_owner_agent_unique UNIQUE (user_id, agent_session_id),
    CONSTRAINT chat_sessions_owner_id_agent_unique
        UNIQUE (user_id, id, agent_session_id)
);

CREATE INDEX chat_sessions_recent_by_user_idx
    ON chat_sessions (user_id, updated_at DESC, id)
    WHERE deleted_at IS NULL;

CREATE TABLE ws_tickets (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL,
    auth_session_id UUID NOT NULL,
    ticket_hash BYTEA NOT NULL UNIQUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at TIMESTAMPTZ NOT NULL,
    used_at TIMESTAMPTZ,
    CONSTRAINT ws_tickets_user_fk
        FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    CONSTRAINT ws_tickets_auth_owner_fk
        FOREIGN KEY (user_id, auth_session_id)
        REFERENCES auth_sessions(user_id, id) ON DELETE CASCADE,
    CONSTRAINT ws_tickets_hash_sha256 CHECK (octet_length(ticket_hash) = 32),
    CONSTRAINT ws_tickets_short_lived CHECK (
        expires_at > created_at
        AND expires_at <= created_at + interval '5 minutes'
    )
);

CREATE INDEX ws_tickets_pending_idx
    ON ws_tickets (expires_at)
    WHERE used_at IS NULL;

CREATE TABLE messages (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL,
    session_id UUID,
    agent_session_id TEXT NOT NULL,
    external_id TEXT,
    role TEXT NOT NULL,
    kind TEXT NOT NULL DEFAULT 'message',
    content JSONB NOT NULL DEFAULT '[]'::jsonb,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT messages_user_fk
        FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    CONSTRAINT messages_agent_owner_fk
        FOREIGN KEY (user_id, agent_session_id)
        REFERENCES chat_sessions(user_id, agent_session_id) ON DELETE CASCADE,
    CONSTRAINT messages_chat_owner_fk
        FOREIGN KEY (user_id, session_id, agent_session_id)
        REFERENCES chat_sessions(user_id, id, agent_session_id) ON DELETE CASCADE,
    CONSTRAINT messages_external_id_bounded CHECK (
        external_id IS NULL OR char_length(external_id) BETWEEN 1 AND 256
    ),
    CONSTRAINT messages_role_valid CHECK (
        role IN ('user', 'assistant', 'system', 'tool')
    ),
    CONSTRAINT messages_kind_bounded CHECK (
        char_length(kind) BETWEEN 1 AND 64
    ),
    CONSTRAINT messages_content_bounded CHECK (
        jsonb_typeof(content) IN ('array', 'object')
        AND octet_length(content::text) <= 1048576
    ),
    CONSTRAINT messages_metadata_object CHECK (
        jsonb_typeof(metadata) = 'object'
        AND octet_length(metadata::text) <= 16384
    )
);

CREATE UNIQUE INDEX messages_external_dedupe_idx
    ON messages (user_id, agent_session_id, external_id)
    WHERE external_id IS NOT NULL;
CREATE INDEX messages_session_timeline_idx
    ON messages (user_id, agent_session_id, created_at, id);

CREATE TABLE jobs (
    job_id TEXT PRIMARY KEY,
    user_id UUID NOT NULL,
    session_id UUID,
    agent_session_id TEXT NOT NULL,
    tool_name TEXT NOT NULL,
    state TEXT NOT NULL DEFAULT 'accepted',
    native_status TEXT,
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    result_summary JSONB NOT NULL DEFAULT '{}'::jsonb,
    native_refs JSONB NOT NULL DEFAULT '{}'::jsonb,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    start_request_id TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    deleted_at TIMESTAMPTZ,
    CONSTRAINT jobs_user_fk
        FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    CONSTRAINT jobs_agent_owner_fk
        FOREIGN KEY (user_id, agent_session_id)
        REFERENCES chat_sessions(user_id, agent_session_id) ON DELETE CASCADE,
    CONSTRAINT jobs_chat_owner_fk
        FOREIGN KEY (user_id, session_id, agent_session_id)
        REFERENCES chat_sessions(user_id, id, agent_session_id) ON DELETE CASCADE,
    CONSTRAINT jobs_owner_id_unique UNIQUE (user_id, job_id),
    CONSTRAINT jobs_id_bounded CHECK (char_length(job_id) BETWEEN 1 AND 96),
    CONSTRAINT jobs_tool_bounded CHECK (char_length(tool_name) BETWEEN 1 AND 96),
    CONSTRAINT jobs_state_bounded CHECK (char_length(state) BETWEEN 1 AND 64),
    CONSTRAINT jobs_native_status_bounded CHECK (
        native_status IS NULL OR char_length(native_status) <= 64
    ),
    CONSTRAINT jobs_request_id_bounded CHECK (
        start_request_id IS NULL OR char_length(start_request_id) BETWEEN 1 AND 256
    ),
    CONSTRAINT jobs_payload_bounded CHECK (
        jsonb_typeof(payload) = 'object'
        AND octet_length(payload::text) <= 1048576
    ),
    CONSTRAINT jobs_result_summary_bounded CHECK (
        jsonb_typeof(result_summary) = 'object'
        AND octet_length(result_summary::text) <= 1048576
    ),
    CONSTRAINT jobs_native_refs_bounded CHECK (
        jsonb_typeof(native_refs) = 'object'
        AND octet_length(native_refs::text) <= 65536
    ),
    CONSTRAINT jobs_metadata_object CHECK (
        jsonb_typeof(metadata) = 'object'
        AND octet_length(metadata::text) <= 16384
    )
);

CREATE UNIQUE INDEX jobs_start_idempotency_idx
    ON jobs (user_id, tool_name, start_request_id)
    WHERE start_request_id IS NOT NULL;
CREATE INDEX jobs_recent_by_user_idx
    ON jobs (user_id, updated_at DESC, job_id)
    WHERE deleted_at IS NULL;
CREATE INDEX jobs_by_session_idx
    ON jobs (user_id, agent_session_id, updated_at DESC)
    WHERE deleted_at IS NULL;

CREATE TABLE storage_objects (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL,
    session_id UUID,
    job_id TEXT,
    kind TEXT NOT NULL,
    filename TEXT NOT NULL,
    content_type TEXT NOT NULL,
    size_bytes BIGINT,
    sha256 TEXT,
    local_path TEXT,
    object_key TEXT,
    status TEXT NOT NULL DEFAULT 'pending',
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    verified_at TIMESTAMPTZ,
    deleted_at TIMESTAMPTZ,
    CONSTRAINT storage_objects_user_fk
        FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    CONSTRAINT storage_objects_chat_owner_fk
        FOREIGN KEY (user_id, session_id)
        REFERENCES chat_sessions(user_id, id) ON DELETE CASCADE,
    CONSTRAINT storage_objects_job_owner_fk
        FOREIGN KEY (user_id, job_id)
        REFERENCES jobs(user_id, job_id) ON DELETE CASCADE,
    CONSTRAINT storage_objects_kind_bounded CHECK (
        char_length(kind) BETWEEN 1 AND 64
    ),
    CONSTRAINT storage_objects_filename_bounded CHECK (
        char_length(filename) BETWEEN 1 AND 255
    ),
    CONSTRAINT storage_objects_content_type_bounded CHECK (
        char_length(content_type) BETWEEN 1 AND 255
    ),
    CONSTRAINT storage_objects_size_valid CHECK (
        size_bytes IS NULL OR size_bytes >= 0
    ),
    CONSTRAINT storage_objects_sha256_valid CHECK (
        sha256 IS NULL OR sha256 ~ '^[0-9a-f]{64}$'
    ),
    CONSTRAINT storage_objects_local_path_bounded CHECK (
        local_path IS NULL
        OR (char_length(local_path) BETWEEN 1 AND 1024 AND local_path !~ '^/')
    ),
    CONSTRAINT storage_objects_key_bounded CHECK (
        object_key IS NULL OR char_length(object_key) BETWEEN 1 AND 1024
    ),
    CONSTRAINT storage_objects_status_bounded CHECK (
        char_length(status) BETWEEN 1 AND 32
    ),
    CONSTRAINT storage_objects_ready_valid CHECK (
        status <> 'ready'
        OR (
            size_bytes IS NOT NULL
            AND sha256 IS NOT NULL
            AND object_key IS NOT NULL
            AND verified_at IS NOT NULL
        )
    ),
    CONSTRAINT storage_objects_metadata_object CHECK (
        jsonb_typeof(metadata) = 'object'
        AND octet_length(metadata::text) <= 16384
    )
);

CREATE UNIQUE INDEX storage_objects_object_key_idx
    ON storage_objects (object_key)
    WHERE object_key IS NOT NULL AND deleted_at IS NULL;
CREATE UNIQUE INDEX storage_objects_local_path_idx
    ON storage_objects (user_id, local_path)
    WHERE local_path IS NOT NULL AND deleted_at IS NULL;
CREATE INDEX storage_objects_by_user_idx
    ON storage_objects (user_id, created_at DESC, id)
    WHERE deleted_at IS NULL;
CREATE INDEX storage_objects_by_job_idx
    ON storage_objects (user_id, job_id, created_at, id)
    WHERE job_id IS NOT NULL AND deleted_at IS NULL;

INSERT INTO schema_migrations (version, name)
VALUES (1, 'initial')
ON CONFLICT (version) DO NOTHING;

COMMIT;
