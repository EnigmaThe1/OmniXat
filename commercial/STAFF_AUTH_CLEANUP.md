# Staff authentication expiry cleanup

Migration 0011 adds an operator function to prune expired staff login attempts
and sessions. Expired records already fail authentication; this function
removes their residual rows. It does not revoke active sessions, change roles
or return login details.

Provision a dedicated maintenance login with database CONNECT and only these
additional grants (substitute your approved role name):

```sql
GRANT USAGE ON SCHEMA omnixat_staff_maintenance TO staff_auth_maintenance;
GRANT EXECUTE ON FUNCTION omnixat_staff_maintenance.prune_expired(integer)
TO staff_auth_maintenance;
```

As that login, run a single bounded transaction:

```sql
BEGIN;
SET LOCAL statement_timeout = '5s';
SELECT * FROM omnixat_staff_maintenance.prune_expired(100);
COMMIT;
```

The function uses the database statement time, processes the oldest eligible
records first using the existing expiry indexes, and skips locked rows so
another pass can retry them. The batch size is per table, defaults to 100 and
is capped at 500. Null or non-positive values remove nothing. The two counts
are the number deleted by that call, not the size of the remaining backlog.
A zero count can also mean eligible rows were locked. A failed or rolled-back
call does not commit deletions.

Keep the function owned by the trusted migration role. It uses fixed,
schema-qualified SQL and a restricted search path; execution is revoked from
PUBLIC. Do not grant the maintenance login direct authentication table access
or let the application login inherit the maintenance role.

## One-shot operator command

From `commercial/`, with the existing PostgreSQL requirements installed and
`OMNIXAT_STAFF_MAINTENANCE_DSN` provided by your secret manager:

```bash
python3 -m omnixat_core.staff_auth_cleanup --batch-size 100 --max-batches 4
```

The runner rejects privileged or mixed application logins and uses the restricted
function. Each batch is a separate transaction with a five-second statement
timeout. Defaults are shown above; the limits are 1–500 rows per table per call
and 1–10 calls per invocation. It stops early when both counts are below the
batch size. A short batch can leave locked records behind for another pass.

On success it prints JSON containing only the number of batches and deletion
counts. Configuration errors exit 2; database or grant failures exit 1 and
write a generic diagnostic to stderr. A later failure does not undo earlier
committed batches. Re-run safely and alert on repeated failures. Use a trusted
single-endpoint DSN and an external process deadline in the operator environment;
the connection and database statement timeouts are not a wall-clock guarantee.

No job is scheduled here. Before staff routes are exposed, configure the
periodic invocation, validate its alerts and qualify the browser/MFA flow
separately; see [Keycloak staff setup](KEYCLOAK_STAFF.md).

PostgreSQL 16 references reviewed 5 November 2026:
[function security](https://www.postgresql.org/docs/16/sql-createfunction.html)
and [row locking](https://www.postgresql.org/docs/16/sql-select.html#SQL-FOR-UPDATE-SHARE).
