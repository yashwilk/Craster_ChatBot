# Database & Migrations

SQLModel + Alembic. `alembic/env.py` excludes tables owned by external
systems (LangGraph checkpointer, mem0/pgvector) from autogenerate.

```bash
make migrate            # apply migrations
make migration m="add x"  # generate a new one
```
