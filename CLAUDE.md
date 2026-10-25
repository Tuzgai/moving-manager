# Household Hub

Self-hosted FastAPI + SQLite + Jinja app for Stuart and Ashley to manage selling one house and buying another. See README.md for install/run.

## Deployment model — read this first

**Every push to `main` is deployed to production within ~5 minutes, automatically.** A timer on the home server (`dell-systemd-configs`, `deploy-projects.sh`) runs `git pull --ff-only`, and if the commit changed it runs `uv sync --frozen` and restarts the `household-hub` service. There is no staging environment and no review gate. The live DB holds real data for a real house purchase.

Consequences:
- Never push anything you haven't run the tests on (`uv run pytest`). A broken commit takes the app down until the next fix lands.
- Commit and push `uv.lock` with any dependency change. The server installs exactly what's locked (`--frozen`).
- Do not commit or push unless the user asks.

## Protecting the database

The live DB is `<data_dir>/db.sqlite` (default `~/.local/share/household-hub/db.sqlite`), in WAL mode. Nightly snapshots go to `backup_dir` (last 14). **Files and backups live in Dropbox; the live DB must never be placed there.**

`app.config.load()` reads `config.toml` + `config.local.toml`, and on the server the running service reads the same files you do. So by default, anything that loads config (running uvicorn, `scripts/seed.py`, a REPL calling `db.init(cfg.db_path)`) touches the **live** database. Treat the server checkout as prod.

**Safe dev runs:** set `HOUSEHOLD_HUB_SCRATCH_DIR` to a throwaway directory. It moves the DB (`<dir>/data`), files (`<dir>/files`) **and** backups (`<dir>/backups`) off the live paths; backups move too because the nightly job rotates old snapshots out of `backup_dir`. Always use it for manual runs, seeding and experiments, and on a different port than the service:

```bash
export HOUSEHOLD_HUB_SCRATCH_DIR=/tmp/hh-dev
uv run python scripts/seed.py
uv run uvicorn app.main:app --host 127.0.0.1 --port 8766
```

The variable is per-process, so it never affects the systemd service. Don't set it in `config.local.toml` or the service unit.

Hard rules:
- Never run `scripts/seed.py --force`, or delete/overwrite `db.sqlite`, its `-wal`/`-shm` files, the data dir, `files_root`, or `backup_dir`. Never run destructive SQL (`DROP`, `DELETE`/`UPDATE` without a tight `WHERE`) against the live DB.
- Don't run uvicorn, the seed script or any DB-touching code without `HOUSEHOLD_HUB_SCRATCH_DIR` set (see below), unless the task is explicitly about the live instance.
- Don't edit `config.toml` / `config.local.toml` `data_dir`, `files_root` or `backup_dir` without being asked. Changing them silently points prod at an empty DB.
- Never change `connect()` PRAGMAs (WAL, foreign_keys) casually.
- `ON DELETE CASCADE` is used widely (`items` → notes, offers, quotes, files links). Deleting an item deletes its children. Be deliberate with any new delete path and add a test.
- To experiment with real-shaped data, copy a snapshot from `backup_dir` to `$HOUSEHOLD_HUB_SCRATCH_DIR/data/db.sqlite` and run against that. In tests, use `tmp_path` and the `conn` fixture from `tests/conftest.py`, or the fake-config pattern in `tests/test_safety.py`.

## Migrations

`app/migrations/NNN_name.sql`, applied in order on **every app startup** (`db.migrate`). A deploy restart therefore runs new migrations against the live DB with no chance to intervene.

- Never edit or rename a migration that has been pushed. Add a new numbered file.
- Prefer additive changes (new tables/columns with defaults, new indexes). Avoid `DROP`, table rebuilds, or data rewrites unless the user explicitly approves a plan.
- `executescript` is not wrapped in one transaction: a migration that fails halfway leaves partial changes, is not stamped in `schema_migrations`, and will fail again on every restart. Keep each migration small and idempotent-safe, and wrap multi-statement changes in `BEGIN; ... COMMIT;`.
- Before pushing a migration, run it against a copy of a recent snapshot from `backup_dir` and run the tests. Tell the user to take a manual backup first (`curl -X POST http://127.0.0.1:8765/admin/backup`).
- Restores are manual: copying a snapshot over the live DB with the service stopped.

## Commands

```bash
uv sync                      # install (uv.lock is authoritative)
uv run pytest                # run before every push
HOUSEHOLD_HUB_SCRATCH_DIR=/tmp/hh-dev uv run uvicorn app.main:app --host 127.0.0.1 --port 8766   # dev; 8765 belongs to the service
```

Tests use temp DBs (`tmp_path`) and must never touch the real data dir. Keep it that way: no test may call `app_config.load()` unpatched against a real DB. `tests/test_safety.py` covers the seed guard.

## Layout

- `app/main.py` wiring and lifespan; `app/routes/` one module per screen; `app/repo/` all SQL lives here (routes don't write raw SQL); `app/templates/` Jinja; `app/jobs/backup.py` nightly SQLite `.backup` scheduler.
- Money is stored as integer cents. Files are stored on disk under `files_root`; `files.stored_path` is relative to it (`tests/test_files_paths.py` guards path traversal).
- `mockup/` holds design mockups only; not served.
- Access is Tailscale-only with no real auth (the user picker just sets a cookie). Bind to `127.0.0.1`, never `0.0.0.0`, and never suggest Tailscale Funnel.

## Conventions

- Match the surrounding code's style and comment density.
- Add or update tests with behaviour changes, especially anything that deletes or rewrites data.
- Infra (units, timers, deploy script, sudoers) lives in the separate `dell-systemd-configs` repo, not here. `deploy/household-hub.service` in this repo is an older user-unit sample and is not what the server runs.
