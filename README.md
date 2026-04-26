# News Classifier API

Flask API for news classification and summarization.

## Linux quick start

```bash
cd /path/to/ponamtky
chmod +x scripts/install-linux.sh scripts/run-linux.sh
./scripts/install-linux.sh
cp .env.example .env   # set OPENAI_API_KEY
./scripts/run-linux.sh
```

### Important Linux note

- Use `sudo` only for OS package installation (`apt`, Playwright deps).
- Do **not** run the server with `sudo`; run `./scripts/run-linux.sh` as your normal user.

## API

- Health: `GET /api/health`
- Classify: `POST /api/news-classifier/classify-news`
- Summarize: `POST /api/news-classifier/summarize-news`

