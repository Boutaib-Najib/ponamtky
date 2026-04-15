# Basic Flask API

This is a minimal Flask API running in a Python virtual environment.

## Setup

1. **Create & activate virtualenv (if not already):**

   ```bash
   cd /Users/najib/Desktop/ponamtky
   python3 -m venv .venv
   source .venv/bin/activate
   ```

2. **Install dependencies:**

   ```bash
   pip install -r requirements.txt
   ```

## Run the API

With the virtual environment activated:

```bash
python app.py
```

The server will start on `http://127.0.0.1:5000`.

### Example endpoints

- `GET /health` → basic health check
- `GET /hello` → returns a simple greeting JSON

