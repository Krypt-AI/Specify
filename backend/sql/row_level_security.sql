-- Row-level security for Specify (PostgreSQL).
--
-- Signed-in requests connect as the restricted role specify_app (REQUEST_DATABASE_URL). Each
-- transaction sets app.current_user_id, and these policies only reveal that user's rows, so a
-- query that forgets its user filter still cannot read or change another user's data.
-- Background workers, migrations and sign-in use the owner role (DATABASE_URL), which is not
-- subject to these policies.
--
-- Run as the schema owner after `alembic upgrade head`; it is safe to run again after every
-- migration (new tables must be added to the lists below):
--   psql "$DATABASE_URL" -f sql/row_level_security.sql
-- Then give the role a password:
--   ALTER ROLE specify_app PASSWORD '<a long random password>';

DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'specify_app') THEN
        CREATE ROLE specify_app LOGIN;
    END IF;
END
$$;

-- The user the current transaction acts for; NULL (no rows visible) when it is not set.
CREATE OR REPLACE FUNCTION specify_current_user_id() RETURNS uuid
    LANGUAGE sql STABLE
AS $$ SELECT NULLIF(current_setting('app.current_user_id', true), '')::uuid $$;

GRANT USAGE ON SCHEMA public TO specify_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO specify_app;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO specify_app;
GRANT EXECUTE ON FUNCTION specify_current_user_id() TO specify_app;

DO $$
DECLARE
    owned_table text;
    child record;
BEGIN
    -- Requests never need the migration bookkeeping.
    IF to_regclass('alembic_version') IS NOT NULL THEN
        REVOKE ALL ON alembic_version FROM specify_app;
    END IF;

    -- The user's own account row.
    ALTER TABLE users ENABLE ROW LEVEL SECURITY;
    DROP POLICY IF EXISTS user_isolation ON users;
    CREATE POLICY user_isolation ON users TO specify_app
        USING (id = specify_current_user_id())
        WITH CHECK (id = specify_current_user_id());

    -- Tables with their own user_id column.
    FOREACH owned_table IN ARRAY ARRAY[
        'audit_logs', 'classification_feedback', 'classification_rules', 'companies',
        'draft_templates', 'duplicate_candidates', 'email_drafts', 'email_messages',
        'follow_up_tasks', 'integrations', 'labels', 'notifications', 'opportunities',
        'recruiter_contacts', 'sheets_connections', 'sync_jobs', 'user_decisions',
        'workflow_definitions', 'workflow_runs'
    ] LOOP
        EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY', owned_table);
        EXECUTE format('DROP POLICY IF EXISTS user_isolation ON %I', owned_table);
        EXECUTE format(
            'CREATE POLICY user_isolation ON %I TO specify_app '
            'USING (user_id = specify_current_user_id()) '
            'WITH CHECK (user_id = specify_current_user_id())',
            owned_table
        );
    END LOOP;

    -- Tables that belong to a user through their parent row.
    FOR child IN SELECT * FROM (VALUES
        ('email_message_groups', 'email_message_id', 'email_messages'),
        ('gmail_sync_states', 'integration_id', 'integrations'),
        ('sheet_row_states', 'connection_id', 'sheets_connections'),
        ('sheet_conflicts', 'connection_id', 'sheets_connections'),
        ('workflow_node_runs', 'workflow_run_id', 'workflow_runs')
    ) AS t(table_name, parent_column, parent_table) LOOP
        EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY', child.table_name);
        EXECUTE format('DROP POLICY IF EXISTS user_isolation ON %I', child.table_name);
        EXECUTE format(
            'CREATE POLICY user_isolation ON %1$I TO specify_app '
            'USING (EXISTS (SELECT 1 FROM %3$I p WHERE p.id = %1$I.%2$I AND p.user_id = specify_current_user_id())) '
            'WITH CHECK (EXISTS (SELECT 1 FROM %3$I p WHERE p.id = %1$I.%2$I AND p.user_id = specify_current_user_id()))',
            child.table_name, child.parent_column, child.parent_table
        );
    END LOOP;
END
$$;
