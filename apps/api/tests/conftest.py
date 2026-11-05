import os
os.environ.setdefault("OMNIXAT_SESSION_SECRET", "test-signing-key-is-long-enough-and-not-real")
os.environ.setdefault("OMNIXAT_OWNER_PASSWORD", "test-only-owner-password-12345")
os.environ.setdefault("OMNIXAT_DATABASE_URL", "sqlite://")
