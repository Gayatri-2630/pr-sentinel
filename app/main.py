import hashlib
import hmac
import logging
import os
 
from dotenv import load_dotenv
from fastapi import BackgroundTasks, Depends, FastAPI, Header, HTTPException, Request
from sqlalchemy.orm import Session
 
from app import crud, models  # pylint: disable=unused-import  # noqa: F401 -- models import registers tables on Base
from app.database import Base, engine, get_db
from app.review_pipeline import process_pr_event
 
load_dotenv()
 
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("pr-sentinel")
 
GITHUB_WEBHOOK_SECRET = os.getenv("GITHUB_WEBHOOK_SECRET")
 
app = FastAPI(title="PR Sentinel", version="0.1.0")
 
# Week 1: create tables directly on startup. We'll switch to proper Alembic
# migrations once the schema stabilizes -- fine as a starting point.
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
 
    # constant-time comparison -- avoids timing attacks on the signature check
    return hmac.compare_digest(expected_signature, signature_header)
 
 
@app.get("/health")
def health():
    return {"status": "ok"}
 
 
@app.get("/reviews/{review_id}")
def get_review_status(review_id: int, db: Session = Depends(get_db)):
    """
    Job-status endpoint: lets you check on a review's progress without
    needing to watch server logs. Genuinely useful now that reviews run
    in the background instead of blocking the webhook response.
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
 
            # Only the fast, essential DB writes happen synchronously here.
            # Everything slow (diff fetch, cloning, indexing, AI agents,
            # static analysis) is handed off to the background task below.
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
 
            # Respond to GitHub immediately -- the slow work above runs
            # AFTER this response is sent, not before it.
            return {
                "status": "queued",
                "pr_number": pr["number"],
                "action": action,
                "review_id": review_row.id,
                "check_status_at": f"/reviews/{review_row.id}",
            }
 
    return {"status": "ignored", "event": x_github_event}
 