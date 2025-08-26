# Apply schema to running DB (no data loss)

These scripts push `db/init.sql` (and `db/20_indexes.sql` if present) into the running Postgres container.

## Prereqs
- `docker compose` up and healthy.
- Files: `db/init.sql` (tables/seed) and optional `db/20_indexes.sql` (indexes).

## PowerShell (recommended)
```powershell
.\scripts\apply-db.ps1
```

## CMD
```
scripts\apply-db.bat
```

What it does:

- Lists current tables (\dt)
- Applies init.sql
- Applies 20_indexes.sql if present
- Lists tables again
