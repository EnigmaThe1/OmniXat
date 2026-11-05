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

No job is scheduled by this migration. Before staff routes are exposed,
configure a bounded periodic runner using this login, record counts only,
and alert on repeated execution failures. Qualify the browser and MFA flow
separately; see [Keycloak staff setup](KEYCLOAK_STAFF.md).

PostgreSQL 16 references reviewed 5 November 2026:
[function security](https://www.postgresql.org/docs/16/sql-createfunction.html)
and [row locking](https://www.postgresql.org/docs/16/sql-select.html#SQL-FOR-UPDATE-SHARE).
