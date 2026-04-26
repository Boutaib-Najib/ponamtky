# Bare-metal deployment (Linux and Windows)

No Docker: install Python, dependencies, Playwright Firefox, then run a production WSGI server.

## Prerequisites

- **Python 3.10+** on the PATH
- **Linux:** `python3-venv` (Debian/Ubuntu: `sudo apt install python3 python3-venv python3-pip`)
- **Windows:** Python from [python.org](https://www.python.org/downloads/) with “Add python.exe to PATH”

## Linux

```bash
cd /path/to/ponamtky
chmod +x scripts/install-linux.sh scripts/run-linux.sh
./scripts/install-linux.sh
cp .env.example .env   # edit OPENAI_API_KEY
./scripts/run-linux.sh
```

`install-linux.sh` runs `sudo … playwright install-deps firefox` so the OS has libraries for headless Firefox.
`run-linux.sh` and `run-windows.ps1` also load environment variables from the repo-root `.env` automatically before starting the server.

Optional environment for `run-linux.sh`:

| Variable   | Default        | Meaning                    |
|-----------|----------------|----------------------------|
| `BIND`    | `0.0.0.0:5009` | Gunicorn bind address      |
| `WORKERS` | `1`            | Gunicorn workers (each = extra RAM + browsers) |
| `THREADS` | `8`            | Thread pool per worker     |
| `TIMEOUT` | `300`          | Request timeout (seconds)  |

### systemd (example)

Run as a dedicated user; adjust paths.

```ini
[Unit]
Description=news-classifier
After=network.target

[Service]
User=www-data
WorkingDirectory=/opt/ponamtky
EnvironmentFile=/opt/ponamtky/.env
ExecStart=/opt/ponamtky/.venv/bin/gunicorn --bind 127.0.0.1:5009 --workers 1 --threads 8 --timeout 300 app:app
Restart=on-failure

[Install]
WantedBy=multi-user.target
```

Put TLS and rate limiting in **nginx** (or Apache) in front; proxy to `127.0.0.1:5009`.

## Windows

Open **PowerShell** as a normal user (Playwright does not require Admin for `install firefox`; rarely `install-deps` may prompt for elevation).

```powershell
cd C:\path\to\ponamtky
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned -Force
.\scripts\install-windows.ps1
copy .env.example .env
notepad .env
.\scripts\run-windows.ps1
```

**Gunicorn does not run on Windows.** The project uses **Waitress** on Windows (`requirements.txt` installs it via `sys_platform == "win32"`).

Optional:

| Variable     | Default   | Meaning              |
|-------------|-----------|----------------------|
| `BIND_HOST` | `0.0.0.0` | Listen address       |
| `PORT`      | `5009`    | Port                 |

### Run as a Windows Service

Use [NSSM](https://nssm.cc/) or Task Scheduler to run:

`C:\path\to\ponamtky\.venv\Scripts\python.exe -m waitress --listen=0.0.0.0:5009 app:app`

with “Start in” set to the project directory.

## Verify

```bash
curl -s http://127.0.0.1:5009/api/health
```

## Security notes

- Do not commit `.env`; restrict permissions on the server (`chmod 600 .env` on Linux).
- Bind to `127.0.0.1` if a reverse proxy terminates TLS; use `0.0.0.0` only on trusted networks or behind a firewall.
