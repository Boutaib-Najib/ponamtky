## News Classifier API

Flask HTTP API that can:

- **Summarize** a document (from URL, raw text, or uploaded PDF/TXT)
- **Classify** a document into **category** and optionally **scenario**

It is designed to be **config-driven**:

- LLM providers/services are defined in `config/configNewsClassifier.json`
- Prompt templates are Jinja2 files in the folder configured by `PROMPTS_PATH`

## Quick start (Linux)

```bash
cd /path/to/ponamtky
chmod +x scripts/install-linux.sh scripts/run-linux.sh
./scripts/install-linux.sh
cp .env.example .env
nano .env  # set OPENAI_API_KEY and PROMPTS_PATH (absolute path to ./prompts)
./scripts/run-linux.sh
```

Then verify:

```bash
curl -s http://127.0.0.1:5009/api/health
```

### Linux: important note about sudo/root

- **Use `sudo` only** for OS package installation (`apt`) and Playwright OS dependencies.
- **Do not run the server with `sudo`**. Playwright Firefox can fail if `$HOME` is not owned by the current user.

## Requirements

### Runtime requirements

- **Python 3.10+**
- **Playwright + Firefox** (installed by the install scripts)

### Python dependencies

Defined in `requirements.txt` (installed by `pip install -r requirements.txt`).

## Configuration model

### `config/configNewsClassifier.json`

This file defines:

- **providers[]**: one entry per logical provider (e.g. `openai`, `mistral`, `my-internal-gateway`)
  - **services[]**: e.g. `completion` and `embedding`
  - each service can have its own **key**, **url**, **model**, **timeouts**
- **usages[]**: maps product use-cases (`summary`, `title`, `categoryClassification`, `scenarioClassification`)
  to a provider + service + prompt template.

This project uses an **OpenAI-compatible client** under the hood; “provider” means “a configured OpenAI-compatible endpoint”.

## Environment variables

The server reads environment variables from the repo-root `.env` (loaded by the run scripts).

### Required

- **`OPENAI_API_KEY`**: API key used by providers that reference `ENV:OPENAI_API_KEY` in config.
- **`PROMPTS_PATH`**: absolute path to the prompts folder (e.g. `/path/to/ponamtky/prompts`).

### Optional

- **`MAX_UPLOAD_MB`** (default `20`): maximum multipart upload size (applies to `read=3` upload flow).
- **`PROMPTS_AUTO_RELOAD`** (default `true`): if `true`, Jinja reloads changed templates automatically.

### Optional (Linux runner / Gunicorn)

Used by `scripts/run-linux.sh`:

- **`BIND`** (default `0.0.0.0:5009`)
- **`WORKERS`** (default `1`)
- **`THREADS`** (default `8`)
- **`TIMEOUT`** (default `300`)

### Optional (Windows runner / Waitress)

Used by `scripts/run-windows.ps1`:

- **`BIND_HOST`** (default `0.0.0.0`)
- **`PORT`** (default `5009`)

## Prompt template reload behavior

- Prompt templates are `.jinja2` files loaded from `PROMPTS_PATH`.
- By default, **auto-reload is enabled**.
- When a `.jinja2` file changes, the server picks up the new version on the **next request** using that template (no restart required).
- Disable by setting `PROMPTS_AUTO_RELOAD=false`.

## HTTP API

Base prefix: `/api/news-classifier`

### `GET /api/health`

Returns:

```json
{"status":"ok"}
```

### Common request fields (summarize + classify)

#### `provider` (optional)

- **Type**: string
- **Behavior**:
  - If omitted: defaults to provider **`openai`**
  - If provided and unknown/unavailable: **404** with an error payload

#### `read` (required)

How the document content is provided:

- `1` = from URL (`url` required)
- `2` = from text (`text` required)
- `3` = upload (`multipart/form-data` with `file` required)

### `POST /api/news-classifier/summarize-news`

#### JSON example (`read=2`)

```json
{
  "read": 2,
  "text": "…document…",
  "provider": "openai"
}
```

#### Response shape

- **Success** (`returnStatus=0`):
  - `title`: string (may be empty)
  - `summary`: string
- **Error**: `returnStatus != 0` and `errorMessage` is set

#### Return status values

- `0`: ok
- `1`: invalid/missing input (`errorMessage` contains a code like `MISSING_URL`, `INVALID_READ`, etc.)
- `4`: summarization failed (`ERR_SUMMARIZING`)

### `POST /api/news-classifier/classify-news`

Classifies the document summary into category and/or scenario.

#### `policy` (optional)

Classification depth:

- `0` = category only
- `1` = scenario only (**requires `category`**)
- `2` = category + scenario (default)

#### JSON example (`read=1`, default policy=2)

```json
{
  "read": 1,
  "url": "https://example.com/article",
  "provider": "openai"
}
```

#### JSON example (`policy=1` scenario-only)

```json
{
  "read": 2,
  "text": "…document…",
  "policy": 1,
  "category": "CONDUCT",
  "provider": "openai"
}
```

#### Response shape

- **Success** (`returnStatus=0`)
  - `category`: string (or `NOT_RELEVANT`, or `null` in edge cases)
  - `scenario`: string (when applicable)
- **Error**: `returnStatus != 0` with `errorMessage`

#### Return status values

- `0`: ok
- `1`: invalid/missing input (`INVALID_POLICY`, `MISSING_CATEGORY`, `MISSING_URL`, `INVALID_READ`, …)
- `4`: summarization failed (`ERR_SUMMARIZING`)
- `5`: classification failed (`ERR_CLASSIFYING` / other internal error codes)

### Upload flow (`read=3`)

Use `multipart/form-data`:

- field **`file`**: `.pdf` or `.txt`
- plus other fields as regular form fields (e.g. `read`, `policy`, `provider`)

Notes:

- Max upload size is controlled by `MAX_UPLOAD_MB`.

## Installation guides (self-serve)

### Linux (bare metal)

Use:

- `scripts/install-linux.sh` (creates venv, installs deps, installs Playwright + Firefox)
- `scripts/run-linux.sh` (loads `.env`, starts Gunicorn)

See also: `docs/BARE_METAL.md`.

### Windows (bare metal)

Use:

- `scripts/install-windows.ps1` (creates venv, installs deps, installs Playwright + Firefox)
- `scripts/run-windows.ps1` (loads `.env`, starts Waitress)

### Docker

Build and run:

```bash
docker build -t ponamtky .
docker run --rm -p 5009:5009 --env-file .env ponamtky
```

## Troubleshooting

### `OPENAI_API_KEY is not set`

- Ensure `.env` contains `OPENAI_API_KEY=...`
- Ensure you started the server via the run scripts (they load `.env`)

### `.env: line X: $'\\r': command not found`

Your `.env` has Windows CRLF line endings. The Linux run script strips `\\r`, but you can also fix the file:

```bash
sed -i 's/\r$//' .env
```

### Playwright error: “Firefox is unable to launch if $HOME isn’t owned…”

You started the server as root (e.g. via `sudo`). Stop it and rerun **without sudo**:

```bash
./scripts/run-linux.sh
```

