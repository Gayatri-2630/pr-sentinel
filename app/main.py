import hashlib
import hmac
import logging
import os
 
from dotenv import load_dotenv
from fastapi import BackgroundTasks, Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session
 
from app import crud, models  # pylint: disable=unused-import  # noqa: F401 -- models import registers tables on Base
from app.database import Base, engine, get_db
from app.review_pipeline import process_pr_event
 
load_dotenv()
 
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("pr-sentinel")
 
GITHUB_WEBHOOK_SECRET = os.getenv("GITHUB_WEBHOOK_SECRET")
 
app = FastAPI(title="PR Sentinel", version="0.1.0")
 
Base.metadata.create_all(bind=engine)
 
 
def verify_signature(payload_body: bytes, signature_header: str | None) -> bool:
    """
    Verify the webhook actually came from GitHub, not a spoofed request.
    GitHub signs the raw request body with our webhook secret using HMAC-SHA256.
    We must compare against the RAW bytes, before any JSON parsing.
    """
    if not signature_header:
        return False
    if not GITHUB_WEBHOOK_SECRET:
        logger.warning("GITHUB_WEBHOOK_SECRET is not set -- refusing all webhooks")
        return False
 
    digest = hmac.new(
        GITHUB_WEBHOOK_SECRET.encode("utf-8"), msg=payload_body, digestmod=hashlib.sha256
    ).hexdigest()
    expected_signature = f"sha256={digest}"
    return hmac.compare_digest(expected_signature, signature_header)
 
 
@app.get("/health")
def health():
    return {"status": "ok"}
 
 
@app.get("/reviews/{review_id}")
def get_review_status(review_id: int, db: Session = Depends(get_db)):
    """
    Job-status endpoint: lets you check on a review's progress without
    needing to watch server logs.
    """
    review = crud.get_review_by_id(db, review_id)
    if not review:
        raise HTTPException(status_code=404, detail="Review not found")
 
    findings = [
        {
            "agent_type": f.agent_type,
            "severity": f.severity,
            "file_path": f.file_path,
            "line_number": f.line_number,
            "message": f.message,
            "verified": f.verified,
        }
        for f in review.findings
    ]
 
    return {
        "review_id": review.id,
        "pr_number": review.pr_number,
        "status": review.status,
        "started_at": review.started_at,
        "completed_at": review.completed_at,
        "total_latency_ms": review.total_latency_ms,
        "findings_count": len(findings),
        "findings": findings,
    }
 
 
@app.get("/dashboard/data")
def get_dashboard_data(db: Session = Depends(get_db)):
    """
    Returns aggregated stats (latency, token usage, false-positive rates)
    as JSON -- the data source for the observability dashboard page below.
    """
    return crud.get_dashboard_stats(db)
 
 
DASHBOARD_HTML = """
<!DOCTYPE html>
<html>
<head>
  <title>PR Sentinel -- Observability Dashboard</title>
  <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js"></script>
  <style>
    body { font-family: -apple-system, sans-serif; background: #0f1115; color: #e8e8e8; margin: 0; padding: 24px; }
    h1 { font-size: 22px; margin-bottom: 4px; }
    .note { background: #2a2010; border: 1px solid #5a4620; color: #d9bb6a; padding: 10px 14px; border-radius: 6px; font-size: 13px; margin-bottom: 20px; }
    .stats { display: flex; gap: 16px; margin-bottom: 24px; flex-wrap: wrap; }
    .stat-card { background: #1a1d24; border: 1px solid #2a2e38; border-radius: 8px; padding: 16px 20px; min-width: 140px; }
    .stat-card .label { font-size: 12px; color: #9098a8; }
    .stat-card .value { font-size: 24px; font-weight: 600; margin-top: 4px; }
    .charts { display: grid; grid-template-columns: 1fr 1fr; gap: 20px; }
    .chart-box { background: #1a1d24; border: 1px solid #2a2e38; border-radius: 8px; padding: 16px; }
    .chart-box h3 { margin: 0 0 12px 0; font-size: 14px; color: #c0c6d0; }
    @media (max-width: 800px) { .charts { grid-template-columns: 1fr; } }
  </style>
</head>
<body>
  <h1>PR Sentinel -- Observability Dashboard</h1>
  <div class="note">
    Note: these stats reflect the project's full history, including data from before a known fix
    (static analysis findings were briefly sent through LLM verification unnecessarily in earlier
    runs -- see the project's debug log for details). Recent runs correctly show 0% false positives
    for bandit/pylint, since those are now trusted directly as deterministic tools.
  </div>
 
  <div class="stats" id="summaryStats"></div>
 
  <div class="charts">
    <div class="chart-box"><h3>Avg LLM Latency by Agent (ms)</h3><canvas id="latencyChart"></canvas></div>
    <div class="chart-box"><h3>Total Tokens Used by Agent</h3><canvas id="tokensChart"></canvas></div>
    <div class="chart-box"><h3>False Positive Rate by Agent (%)</h3><canvas id="fpChart"></canvas></div>
    <div class="chart-box"><h3>Findings by Severity</h3><canvas id="severityChart"></canvas></div>
  </div>
 
  <script>
    async function loadDashboard() {
      const res = await fetch('/dashboard/data');
      const data = await res.json();
 
      document.getElementById('summaryStats').innerHTML = `
        <div class="stat-card"><div class="label">Total Reviews</div><div class="value">${data.total_reviews}</div></div>
        <div class="stat-card"><div class="label">Avg Review Latency</div><div class="value">${(data.avg_review_latency_ms / 1000).toFixed(1)}s</div></div>
      `;
 
      const colors = ['#5b8def', '#e8a33d', '#4caf7d', '#d9546e', '#9b7ede'];
 
      new Chart(document.getElementById('latencyChart'), {
        type: 'bar',
        data: {
          labels: data.usage_by_agent.map(a => a.agent_type),
          datasets: [{ data: data.usage_by_agent.map(a => a.avg_latency_ms), backgroundColor: colors }]
        },
        options: { plugins: { legend: { display: false } } }
      });
 
      new Chart(document.getElementById('tokensChart'), {
        type: 'bar',
        data: {
          labels: data.usage_by_agent.map(a => a.agent_type),
          datasets: [{ data: data.usage_by_agent.map(a => a.total_tokens), backgroundColor: colors }]
        },
        options: { plugins: { legend: { display: false } } }
      });
 
      new Chart(document.getElementById('fpChart'), {
        type: 'bar',
        data: {
          labels: data.findings_by_agent.map(a => a.agent_type),
          datasets: [{ data: data.findings_by_agent.map(a => a.false_positive_rate), backgroundColor: colors }]
        },
        options: { plugins: { legend: { display: false } } }
      });
 
      new Chart(document.getElementById('severityChart'), {
        type: 'doughnut',
        data: {
          labels: data.findings_by_severity.map(s => s.severity),
          datasets: [{ data: data.findings_by_severity.map(s => s.count), backgroundColor: colors }]
        }
      });
    }
    loadDashboard();
  </script>
</body>
</html>
"""
 
 
@app.get("/dashboard", response_class=HTMLResponse)
def get_dashboard_page():
    """The actual visual observability dashboard -- charts built on top of /dashboard/data."""
    return DASHBOARD_HTML
 
 
@app.post("/webhook")
async def github_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    x_hub_signature_256: str | None = Header(default=None),
    x_github_event: str | None = Header(default=None),
    db: Session = Depends(get_db),
):
    raw_body = await request.body()
 
    if not verify_signature(raw_body, x_hub_signature_256):
        logger.warning("Webhook signature verification FAILED -- rejecting request")
        raise HTTPException(status_code=401, detail="Invalid signature")
 
    payload = await request.json()
    logger.info("Verified GitHub event received: %s", x_github_event)
 
    if x_github_event == "pull_request":
        action = payload.get("action")
        if action in ("opened", "synchronize", "reopened"):
            pr = payload["pull_request"]
            repo = payload["repository"]
            installation_id = payload["installation"]["id"]
 
            logger.info(
                "PR #%s (%s) on %s -- head sha %s -- queuing for background processing",
                pr["number"], action, repo["full_name"], pr["head"]["sha"][:8],
            )
 
            installation_row = crud.get_or_create_installation(
                db,
                github_installation_id=installation_id,
                account_login=repo["owner"]["login"],
            )
            repository_row = crud.get_or_create_repository(
                db,
                installation_id=installation_row.id,
                repo_full_name=repo["full_name"],
                default_branch=repo.get("default_branch", "main"),
            )
            review_row = crud.create_review(
                db,
                repository_id=repository_row.id,
                pr_number=pr["number"],
                head_sha=pr["head"]["sha"],
            )
            logger.info("Created review id=%s with status 'pending' for PR #%s", review_row.id, pr["number"])
 
            background_tasks.add_task(
                process_pr_event,
                review_id=review_row.id,
                repository_id=repository_row.id,
                installation_id=installation_id,
                repo_full_name=repo["full_name"],
                clone_url=repo["clone_url"],
                default_branch=repo.get("default_branch", "main"),
                pr_number=pr["number"],
                head_sha=pr["head"]["sha"],
            )
 
            return {
                "status": "queued",
                "pr_number": pr["number"],
                "action": action,
                "review_id": review_row.id,
                "check_status_at": f"/reviews/{review_row.id}",
            }
 
    return {"status": "ignored", "event": x_github_event}
    # trigger scoped static analysis test
   import os
   password = "admin123"
   import pickle
   password = "hunter2"
