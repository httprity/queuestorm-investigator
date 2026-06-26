# RUNBOOK — QueueStorm Investigator

Operational guide for deploying and keeping the service alive during the judging window.

## 1. Prerequisites

- A GitHub repository (e.g. `queuestorm-investigator`) containing this project at its
  root (`app/`, `requirements.txt`, `Dockerfile`, …).
- A free [Render](https://render.com) account.

## 2. Deploy on Render (Web Service, free tier)

1. **New → Web Service**, connect the GitHub repo.
2. **Environment:** Python 3 (native runtime — no Docker needed; the `Dockerfile` is
   provided as an alternative).
3. **Build command:**
   ```
   pip install -r requirements.txt
   ```
4. **Start command:**
   ```
   uvicorn app.main:app --host 0.0.0.0 --port $PORT
   ```
   > `$PORT` is injected by Render — never hardcode a port.
5. **Health check path:** `/health`
6. **Instance type:** Free.
7. Click **Create Web Service** and wait for the first deploy to go green.

### Docker alternative

If deploying via Docker (Render → "Docker" environment), no build/start command is
needed — the `Dockerfile` already binds `0.0.0.0` and reads `$PORT`.

## 3. Keep-alive (defeat free-tier spin-down)

Render free instances sleep after ~15 minutes idle, adding cold-start latency. To keep it
warm during judging:

1. Go to [cron-job.org](https://cron-job.org) (free).
2. Create a job hitting `https://<your-app>.onrender.com/health`.
3. Schedule: **every 10 minutes**.
4. Method: `GET`, expected response: `200`.

Enable it shortly before the judging window opens; disable afterwards.

## 4. Verify from OUTSIDE (not just locally)

```bash
# Health
curl https://<your-app>.onrender.com/health
# -> {"status":"ok"}

# Full analysis
curl -X POST https://<your-app>.onrender.com/analyze-ticket \
  -H "Content-Type: application/json" \
  -d '{
        "ticket_id":"TKT-001",
        "complaint":"I sent 5000 taka to a wrong number around 2pm today. Please help me get my money back.",
        "transaction_history":[
          {"transaction_id":"TXN-9101","timestamp":"2026-04-14T14:08:22Z","type":"transfer","amount":5000,"counterparty":"+8801719876543","status":"completed"}
        ]
      }'
```

Confirm: `200`, valid JSON, correct enums, `relevant_transaction_id` present.

### Error-path smoke tests

```bash
# malformed JSON -> 400
curl -s -o /dev/null -w "%{http_code}\n" -X POST https://<app>/analyze-ticket -H "Content-Type: application/json" -d '{not json'
# missing complaint -> 400
curl -s -o /dev/null -w "%{http_code}\n" -X POST https://<app>/analyze-ticket -H "Content-Type: application/json" -d '{"ticket_id":"X"}'
# empty complaint -> 422
curl -s -o /dev/null -w "%{http_code}\n" -X POST https://<app>/analyze-ticket -H "Content-Type: application/json" -d '{"ticket_id":"X","complaint":"  "}'
```

## 5. Local regression before every push

```bash
python tests/test_samples.py    # must print ALL PASS: 10/10
```

## 6. Troubleshooting

| Symptom | Likely cause | Fix |
|---------|--------------|-----|
| First request after idle is slow | Free-tier cold start | Enable the cron-job.org keep-alive |
| `502` from Render | App not binding `$PORT` | Ensure start command uses `--port $PORT` |
| Deploy fails on build | Dependency pin issue | Check `requirements.txt`, re-deploy |
| `/health` slow | Heavy startup work | N/A here — startup is intentionally cheap |
