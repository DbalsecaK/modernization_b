"""Database layer shared by the API, the model gateway and the workers. Tenant-scoped queries go through
`scoped_connection` (RLS variables set). The Alembic migrations in apps/api are the source of truth."""
