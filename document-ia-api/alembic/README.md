# Database Migrations with Alembic

This directory contains the Alembic configuration and migration files for the Document IA API.

## Overview

Alembic is used to manage database schema changes in a version-controlled manner. All database schema changes should be managed through migrations rather than direct database modifications.

## Configuration

The Alembic configuration is set up to work with our existing database setup:

- **Database URL**: Dynamically built from environment variables
- **Models**: Automatically imports all models from `infra.database.models`
- **Target Metadata**: Uses the SQLAlchemy Base metadata

## Usage

### Using Alembic Directly

You can also use Alembic commands directly:

```bash
# Apply all pending migrations
poetry run alembic upgrade head

# Create a new migration (auto-generate from model changes)
poetry run alembic revision --autogenerate -m "Description of changes"

# Show current migration status
poetry run alembic current

# Show migration history
poetry run alembic history

# Downgrade to previous migration
poetry run alembic downgrade -1

# Dry run a migration for dev purposes
poetry run alembic upgrade head --sql > migration.sql
```

## Migration Workflow

1. **Make model changes**: Update your SQLAlchemy models in `infra/database/models/`
2. **Generate migration**: Run `poetry run alembic revision --autogenerate -m "Description"`
3. **Review migration**: Check the generated migration file in `versions/`
4. **Apply migration**: Run `poetry run alembic upgrade head`
5. **Commit changes**: Commit both model changes and migration files

## Important Notes

- **Always review auto-generated migrations** before applying them
- **Test migrations** on a development database first
- **Never edit migration files** after they've been applied to production
- **Use descriptive messages** for migration names
- **Backup your database** before running migrations in production

## Environment Variables

Make sure the following environment variables are set:

- `POSTGRES_HOST`
- `POSTGRES_PORT`
- `POSTGRES_DB`
- `POSTGRES_USER`
- `POSTGRES_PASSWORD`

## Troubleshooting

### Connection Issues

If you encounter connection issues, verify:
1. Database is running and accessible
2. Environment variables are correctly set
3. Database user has necessary permissions

### Migration Conflicts

If you have migration conflicts:
1. Check the migration history with `alembic history`
2. Resolve conflicts by editing migration files (before applying)
3. Use `alembic stamp` to mark the database at a specific revision if needed

### Rollback

To rollback a migration:
```bash
poetry run alembic downgrade -1
```

To rollback to a specific revision:
```bash
poetry run alembic downgrade <revision_id>
```
