# Local billing simulator event receipts

Migration 0006 and `SandboxEventReceiver` accept signed simulator snapshots for
an existing sandbox subscription. This internal function has no HTTP route,
provider integration, checkout, invoice, payment activation or subscription
state mutation.

The trusted caller constructs a receiver for one tenant with separate,
random sandbox key material (at least 32 bytes), an idle autocommit connection
and a trusted clock. Keep keys outside the repository and never reuse a live
provider credential. The envelope uses an integer Unix timestamp within five
minutes of the server clock, and a lowercase hexadecimal HMAC-SHA256 over:

```text
b"omnixat:sandbox:subscription-snapshot:v1:" + ascii(timestamp) + b"." + raw_body
```

The body is up to 2048 bytes of UTF-8 JSON, with exactly five string fields:
`tenant_id`, `event_id`, `subscription_id`, `price_version_id` (UUIDs) and
`state`. Allowed reported states are pending, trialing, trial_expired,
cancelled and active. The receiver checks the signature and rejects duplicate
keys, malformed bodies and a tenant different from its configuration before
database access. A new event must target that tenant's stored subscription.

Receipts compare the report with the pinned price and local state at receipt
time. The result is matched, price_mismatch or state_mismatch (price takes
precedence). A reported active state is never applied to the subscription.
The receipt stores IDs, body digest, comparison metadata and receive time,
without raw body, signature, key or credentials.

The tenant/event ID pair deduplicates delivery across connections. A correctly
signed exact-body replay returns the original receipt; changing any body byte
under that ID conflicts. After the signature window, the simulator must sign
the same body with a fresh timestamp. PostgreSQL's unique key and a separate
READ COMMITTED lookup reconcile competing inserts. There is no automatic
retry, event deletion, mutable snapshot projection, or claim of provider
compatibility or exactly-once external effects.

## Database grants

Apply migration 0006 as migration owner. Use a separate non-owner receiver
login: schema USAGE on omnixat_sandbox; SELECT on price_terms, subscriptions
and cancellations; SELECT and INSERT on event_receipts only. No insert rights
on subscription or cancellation tables, UPDATE/DELETE/TRUNCATE, ownership,
role switching, customer or billing schema access. The existing subscription
writer is refused as a receiver. Forced RLS and a tenant-bound subscription
foreign key scope receipts. Keep SQL connections trusted; row security using
server-set tenant context is not independent identity verification.

Primary references: [Python HMAC](https://docs.python.org/3.12/library/hmac.html)
and [PostgreSQL 16 transaction isolation](https://www.postgresql.org/docs/16/transaction-iso.html).
