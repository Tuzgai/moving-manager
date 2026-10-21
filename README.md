# Household Hub

Self-hosted web app for Stuart and Ashley to manage selling one house and buying another. Runs on a Linux laptop, reached over Tailscale.

## Install

Requires Python 3.11+ and [`uv`](https://docs.astral.sh/uv/).

```bash
uv sync
```

## Run

```bash
uv run uvicorn app.main:app --host 127.0.0.1 --port 8765
```

Then open `http://127.0.0.1:8765` locally, or over Tailscale (see below).

Config lives in `config.toml`; override per-machine with `config.local.toml` (gitignored).

## Seed sample data

```bash
uv run python scripts/seed.py
```

This wipes and reloads the DB with the data from the mockups so you can click around immediately.

## Tailscale

Serve the app over tailnet HTTPS (never public funnel):

```bash
sudo tailscale serve --bg --https=443 http://127.0.0.1:8765
```

Check it with `tailscale serve status`. Reach it from any tailnet device at `https://<machine>.<tailnet>.ts.net`.

## Run on boot (systemd --user)

```bash
mkdir -p ~/.config/systemd/user
cp deploy/household-hub.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now household-hub
loginctl enable-linger "$USER"   # keeps the service alive without a login session
```

Logs: `journalctl --user -u household-hub -f`.

## Backups

A nightly job runs `sqlite3 .backup` and writes a consistent snapshot to the configured `backup_dir`, keeping the last 14. Scheduled inside the app process at startup; no cron needed.

## Tests

```bash
uv run pytest
```
