# PR Sentinel — Week 1 scaffold

An AI-powered GitHub PR review agent. This is the Week 1 foundation: a GitHub App
that receives verified webhook events, and a Postgres schema ready to track
installations, repos, reviews, findings, LLM usage, and evaluation runs.

## Setup

1. **Create a virtual environment and install dependencies**
   ```bash
   python -m venv venv
   source venv/bin/activate   # on Windows: venv\Scripts\activate
   pip install -r requirements.txt
   ```

2. **Start Postgres locally with Docker**
   ```bash
   docker compose up -d
   ```

3. **Set up your environment file**
   ```bash
   cp .env.example .env
   ```
   Fill in `GITHUB_WEBHOOK_SECRET` (the one you set when creating the GitHub App)
   and `GITHUB_APP_ID`. `DATABASE_URL` already matches the docker-compose defaults.

4. **Run the app**
   ```bash
   uvicorn app.main:app --reload --port 8000
   ```
   Visit http://localhost:8000/health — you should see `{"status": "ok"}`.

5. **Forward GitHub webhooks to your local machine**

   GitHub can't reach `localhost` directly, so we use smee.io as a relay:
   ```bash
   npm install --global smee-client
   smee -u https://smee.io/YOUR_CHANNEL_ID -t http://localhost:8000/webhook
   ```
   (Replace the URL with the one from your smee.io channel, and make sure
   that same URL is set as your GitHub App's webhook URL.)

6. **Test it**

   Open a pull request on the test repo where you installed the app. You
   should see log lines in your terminal showing the verified event coming
   in — that's Week 1, done.

## What's here vs. what's next

- ✅ FastAPI app with GitHub webhook signature verification (HMAC-SHA256)
- ✅ Full Postgres schema (installations, repositories, reviews, findings,
  llm_usage, evaluation_runs, configuration) via SQLAlchemy models
- ✅ Secrets kept out of git (.env, .gitignore, no committed keys)
- ⬜ Fetching the actual PR diff via the GitHub API (Week 1, next task)
- ⬜ AST-aware chunking + embeddings (Week 2)
- ⬜ Multi-agent analysis layer (Week 3)
- ⬜ Hybrid static analysis + prompt-injection hardening (Week 4)
- ⬜ Async processing, Docker deploy, CI/CD (Week 5)
- ⬜ Observability dashboard (Week 6)
- ⬜ Evaluation + ablation study (Week 7)
- ⬜ Docs, diagrams, demo video (Week 8)
Incremental indexing verification test.