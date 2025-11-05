BEGIN;

CREATE TABLE alembic_version (
    version_num VARCHAR(32) NOT NULL,
    CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num)
);

-- Running upgrade  -> 5876b08c4f42

CREATE TABLE event_store (
    id UUID NOT NULL,
    workflow_id VARCHAR(255) NOT NULL,
    execution_id VARCHAR(255) NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL,
    event_type VARCHAR(100) NOT NULL,
    event JSONB NOT NULL,
    version INTEGER NOT NULL,
    PRIMARY KEY (id),
    UNIQUE (workflow_id, execution_id, event_type, version)
);

COMMENT ON COLUMN event_store.id IS 'Unique identifier for the event';

COMMENT ON COLUMN event_store.workflow_id IS 'Workflow identifier';

COMMENT ON COLUMN event_store.execution_id IS 'Execution instance identifier';

COMMENT ON COLUMN event_store.created_at IS 'Event timestamp';

COMMENT ON COLUMN event_store.event_type IS 'Type of event (e.g., WorkflowExecutionStarted)';

COMMENT ON COLUMN event_store.event IS 'Event payload as JSON';

COMMENT ON COLUMN event_store.version IS 'Event version for optimistic locking';

CREATE INDEX idx_event_store_created_at ON event_store (created_at);

CREATE INDEX idx_event_store_execution_version ON event_store (execution_id, version);

CREATE INDEX idx_event_store_execution_workflow ON event_store (execution_id, workflow_id, created_at);

CREATE INDEX ix_event_store_created_at ON event_store (created_at);

CREATE INDEX ix_event_store_event_type ON event_store (event_type);

CREATE INDEX ix_event_store_execution_id ON event_store (execution_id);

CREATE INDEX ix_event_store_workflow_id ON event_store (workflow_id);

INSERT INTO alembic_version (version_num) VALUES ('5876b08c4f42') RETURNING alembic_version.version_num;

-- Running upgrade 5876b08c4f42 -> 9f3c1a2b7d84

DROP INDEX idx_event_store_execution_version;

ALTER TABLE event_store DROP COLUMN version CASCADE;

UPDATE alembic_version SET version_num='9f3c1a2b7d84' WHERE alembic_version.version_num = '5876b08c4f42';

-- Running upgrade 9f3c1a2b7d84 -> 19d1c6ddd15d

CREATE TABLE organization (
    id UUID NOT NULL,
    contact_email VARCHAR(255) NOT NULL,
    name VARCHAR(255) NOT NULL,
    platform_role VARCHAR(255) NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL,
    PRIMARY KEY (id)
);

COMMENT ON COLUMN organization.id IS 'Unique identifier for the organization';

COMMENT ON COLUMN organization.contact_email IS 'Contact email for the organization';

COMMENT ON COLUMN organization.name IS 'Name of the organization';

COMMENT ON COLUMN organization.platform_role IS 'Platform role one of PlatformAdmin or Standard';

COMMENT ON COLUMN organization.created_at IS 'organization creation datetime';

COMMENT ON COLUMN organization.updated_at IS 'organization update datetime';

CREATE TABLE api_key (
    id UUID NOT NULL,
    organization_id UUID NOT NULL,
    key_hash VARCHAR(255) NOT NULL,
    prefix VARCHAR(12) NOT NULL,
    status VARCHAR(255) NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL,
    PRIMARY KEY (id),
    CONSTRAINT fk_api_key_organization_id FOREIGN KEY(organization_id) REFERENCES organization (id) ON DELETE CASCADE
);

COMMENT ON COLUMN api_key.id IS 'Unique identifier of the api_key';

COMMENT ON COLUMN api_key.organization_id IS 'Id of the organization owning the api_key';

COMMENT ON COLUMN api_key.key_hash IS 'Hash of the api_key';

COMMENT ON COLUMN api_key.prefix IS 'Prefix of the api_key';

COMMENT ON COLUMN api_key.status IS 'Status of the api_key';

COMMENT ON COLUMN api_key.created_at IS 'api_key creation datetime';

COMMENT ON COLUMN api_key.updated_at IS 'api_key update datetime';

CREATE TABLE webhook (
    id UUID NOT NULL,
    organization_id UUID NOT NULL,
    url VARCHAR(2048) NOT NULL,
    encrypted_headers TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL,
    PRIMARY KEY (id),
    CONSTRAINT fk_webhook_organization_id FOREIGN KEY(organization_id) REFERENCES organization (id) ON DELETE CASCADE
);

COMMENT ON COLUMN webhook.id IS 'Unique identifier of the webhook';

COMMENT ON COLUMN webhook.organization_id IS 'Id of the organization owning the webhook';

COMMENT ON COLUMN webhook.url IS 'URL of the webhook';

COMMENT ON COLUMN webhook.encrypted_headers IS 'Encrypted headers for the webhook';

COMMENT ON COLUMN webhook.created_at IS 'webhook creation datetime';

COMMENT ON COLUMN webhook.updated_at IS 'webhook update datetime';

ALTER TABLE event_store ADD COLUMN organization_id UUID;

ALTER TABLE event_store ADD FOREIGN KEY(organization_id) REFERENCES organization (id) ON DELETE SET NULL;

COMMENT ON COLUMN event_store.organization_id IS 'Identifier of the organization associated with the event';

UPDATE alembic_version SET version_num='19d1c6ddd15d' WHERE alembic_version.version_num = '9f3c1a2b7d84';

-- Running upgrade 19d1c6ddd15d -> 4f4ecb83db27
