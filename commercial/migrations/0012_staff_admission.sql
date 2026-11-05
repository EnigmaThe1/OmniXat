CREATE SCHEMA omnixat_staff_admission;
REVOKE ALL ON SCHEMA omnixat_staff_admission FROM PUBLIC;

CREATE TABLE omnixat_staff_admission.budgets (
    action text PRIMARY KEY,
    source_limit integer NOT NULL,
    total_limit integer NOT NULL CHECK (total_limit BETWEEN 1 AND 1000),
    minute_id bigint NOT NULL DEFAULT -1,
    admitted integer NOT NULL DEFAULT 0 CHECK (admitted >= 0),
    sources jsonb NOT NULL DEFAULT '{}'::jsonb,
    CHECK (source_limit BETWEEN 1 AND total_limit)
);
REVOKE ALL ON omnixat_staff_admission.budgets FROM PUBLIC;

INSERT INTO omnixat_staff_admission.budgets(action, source_limit, total_limit) VALUES
    ('login', 5, 60), ('callback', 10, 120), ('session', 60, 300), ('logout', 10, 60);

CREATE FUNCTION omnixat_staff_admission.admit(request_action text, source_key text)
RETURNS boolean
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
SET lock_timeout = '1s'
AS $$
DECLARE
    budget omnixat_staff_admission.budgets%ROWTYPE;
    current_minute bigint;
    source_count integer;
BEGIN
    IF source_key IS NULL OR length(source_key) <> 64 OR source_key ~ '[^0-9a-f]' THEN
        RETURN false;
    END IF;
    SELECT * INTO budget FROM omnixat_staff_admission.budgets
        WHERE action = request_action FOR UPDATE;
    IF NOT FOUND THEN
        RETURN false;
    END IF;

    current_minute := floor(extract(epoch FROM clock_timestamp()) / 60)::bigint;
    IF current_minute < budget.minute_id THEN
        RETURN false;
    ELSIF current_minute > budget.minute_id THEN
        budget.admitted := 0;
        budget.sources := '{}'::jsonb;
    END IF;
    source_count := COALESCE((budget.sources ->> source_key)::integer, 0);
    IF budget.admitted >= budget.total_limit OR source_count >= budget.source_limit THEN
        RETURN false;
    END IF;

    UPDATE omnixat_staff_admission.budgets
    SET minute_id = current_minute, admitted = budget.admitted + 1,
        sources = jsonb_set(budget.sources, ARRAY[source_key], to_jsonb(source_count + 1))
    WHERE action = request_action;
    RETURN true;
END;
$$;

REVOKE ALL ON FUNCTION omnixat_staff_admission.admit(text, text) FROM PUBLIC;
