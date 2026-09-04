import hashlib
import hmac
import logging
import os
 
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, Header, HTTPException, Request
from sqlalchemy.orm import Session
 
from app import crud, models  # noqa: F401 -- models import registers tables on Base
from app.agents.orchestrator import run_all_agents
from app.code_indexer import ensure_repo_cloned, index_repository
from app.database import Base, engine, get_db
from app.github_api import get_pr_diff
from app.github_auth import get_installation_token
 
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
 
 
@app.post("/webhook")
async def github_webhook(
    request: Request,
    x_hub_signature_256: str | None = Header(default=None),
    x_github_event: str | None = Header(default=None),
    db: Session = Depends(get_db),
):
    raw_body = await request.body()
 
    if not verify_signature(raw_body, x_hub_signature_256):
        logger.warning("Webhook signature verification FAILED -- rejecting request")
        raise HTTPException(status_code=401, detail="Invalid signature")
 
    payload = await request.json()
    logger.info(f"Verified GitHub event received: {x_github_event}")
 
    if x_github_event == "pull_request":
        action = payload.get("action")
        if action in ("opened", "synchronize", "reopened"):
            pr = payload["pull_request"]
            repo = payload["repository"]
            installation_id = payload["installation"]["id"]
 
            logger.info(
                f"PR #{pr['number']} ({action}) on {repo['full_name']} "
                f"-- head sha {pr['head']['sha'][:8]}"
            )
 
            diff_text = get_pr_diff(
                installation_id=installation_id,
                repo_full_name=repo["full_name"],
                pr_number=pr["number"],
            )
 
            logger.info(f"Fetched diff, {len(diff_text)} characters:")
            logger.info(diff_text[:500])  # just the first 500 chars for now, to keep logs readable
 
            # Save everything to Postgres so this event has a permanent record.
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
            crud.mark_review_completed(db, review_row)
 
            logger.info(
                f"Saved review id={review_row.id} for PR #{pr['number']} "
                f"(latency: {review_row.total_latency_ms}ms)"
            )
 
            # Clone (or update) a local copy of the repo, so we have more
            # than just the diff to work with -- this is the foundation
            # for RAG context in the coming steps.
            token = get_installation_token(installation_id)
            local_repo_path = ensure_repo_cloned(
                repo_full_name=repo["full_name"],
                clone_url=repo["clone_url"],
                installation_token=token,
            )
            logger.info(f"Repo available locally at: {local_repo_path}")
 
            # Incremental indexing: only re-embed the codebase if it's
            # actually changed since we last indexed it. Comparing commit
            # SHAs is a cheap, reliable way to know "has anything changed?"
            head_sha = pr["head"]["sha"]
            if repository_row.last_indexed_commit_sha == head_sha:
                logger.info("Repo already indexed at this commit -- skipping re-indexing.")
            else:
                chunk_count = index_repository(repo["full_name"], local_repo_path)
                crud.mark_repository_indexed(db, repository_row, head_sha)
                logger.info(f"Indexed {chunk_count} code chunks for {repo['full_name']}.")
 
            # Run the actual AI analysis: all three agents on this diff.
            findings = run_all_agents(diff_text)
            logger.info(f"Agents produced {len(findings)} findings.")
 
            for finding in findings:
                crud.save_finding(db, review_id=review_row.id, finding=finding)
                verified_tag = "VERIFIED" if finding.get("verified") else "UNVERIFIED"
                logger.info(
                    f"  [{finding['agent_type'].upper()}] [{finding['severity'].upper()}] "
                    f"[{verified_tag}] {finding['file_path']}: {finding['message']}"
                )
 
            return {
                "status": "received",
                "pr_number": pr["number"],
                "action": action,
                "diff_length": len(diff_text),
                "review_id": review_row.id,
                "findings_count": len(findings),
            }
 
    return {"status": "ignored", "event": x_github_event}

def test_verification(user_id):
    query = "SELECT * FROM users WHERE id = " + user_id
    return query