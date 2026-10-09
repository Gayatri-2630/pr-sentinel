"""
Small database helper functions -- the standard 'CRUD' layer that sits between
the webhook/pipeline code and the raw SQLAlchemy models.
"""
 
from datetime import datetime, timezone
 
from sqlalchemy import Integer, func
from sqlalchemy.orm import Session
 
from app import models
 
 
def get_or_create_installation(db: Session, github_installation_id: str, account_login: str) -> models.Installation:
    installation = (
        db.query(models.Installation)
        .filter(models.Installation.github_installation_id == str(github_installation_id))
        .first()
    )
    if installation:
        return installation
 
    installation = models.Installation(
        github_installation_id=str(github_installation_id),
        account_login=account_login,
    )
    db.add(installation)
    db.commit()
    db.refresh(installation)
    return installation
 
 
def get_or_create_repository(
    db: Session, installation_id: int, repo_full_name: str, default_branch: str
) -> models.Repository:
    repository = (
        db.query(models.Repository)
        .filter(models.Repository.repo_full_name == repo_full_name)
        .first()
    )
    if repository:
        return repository
 
    repository = models.Repository(
        installation_id=installation_id,
        repo_full_name=repo_full_name,
        default_branch=default_branch,
    )
    db.add(repository)
    db.commit()
    db.refresh(repository)
    return repository
 
 
def get_repository_by_id(db: Session, repository_id: int) -> models.Repository:
    return db.query(models.Repository).filter(models.Repository.id == repository_id).first()
 
 
def get_review_by_id(db: Session, review_id: int) -> models.Review:
    return db.query(models.Review).filter(models.Review.id == review_id).first()
 
 
def create_review(db: Session, repository_id: int, pr_number: int, head_sha: str) -> models.Review:
    """
    Create a review row in "pending" state -- this happens synchronously
    in the webhook handler, BEFORE the actual (slow) processing starts in
    the background. mark_review_started() flips it to "running" once the
    background task actually begins work.
    """
    review = models.Review(
        repository_id=repository_id,
        pr_number=pr_number,
        head_sha=head_sha,
        status="pending",
    )
    db.add(review)
    db.commit()
    db.refresh(review)
    return review
 
 
def mark_review_started(db: Session, review: models.Review) -> models.Review:
    """Called by the background task when it actually starts processing."""
    review.status = "running"
    review.started_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(review)
    return review
 
 
def mark_review_completed(db: Session, review: models.Review) -> models.Review:
    review.status = "completed"
    review.completed_at = datetime.now(timezone.utc)
    if review.started_at:
        delta = review.completed_at - review.started_at
        review.total_latency_ms = int(delta.total_seconds() * 1000)
    db.commit()
    db.refresh(review)
    return review
 
 
def mark_review_failed(db: Session, review: models.Review) -> models.Review:
    """
    Called when the background pipeline raises an unhandled exception --
    so a crashed review shows up clearly as "failed" in the database,
    rather than being stuck forever at "running" with no explanation.
    """
    review.status = "failed"
    review.completed_at = datetime.now(timezone.utc)
    if review.started_at:
        delta = review.completed_at - review.started_at
        review.total_latency_ms = int(delta.total_seconds() * 1000)
    db.commit()
    db.refresh(review)
    return review
 
 
def mark_repository_indexed(db: Session, repository: models.Repository, commit_sha: str) -> models.Repository:
    """Record that we've indexed this repo up to a specific commit."""
    repository.last_indexed_commit_sha = commit_sha
    repository.indexed_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(repository)
    return repository
 
 
def save_finding(db: Session, review_id: int, finding: dict) -> models.Finding:
    """Save one agent finding as a real row, linked back to its review."""
    finding_row = models.Finding(
        review_id=review_id,
        agent_type=finding.get("agent_type", "unknown"),
        file_path=finding.get("file_path", "unknown"),
        line_number=finding.get("line_number"),
        severity=finding.get("severity", "low"),
        message=finding.get("message", ""),
        verified=finding.get("verified", False),
        false_positive_flag=not finding.get("verified", False),
    )
    db.add(finding_row)
    db.commit()
    db.refresh(finding_row)
    return finding_row
 
 
def get_dashboard_stats(db: Session) -> dict:
    """
    Pull together the real numbers that have been quietly accumulating
    in the database this whole project -- per-agent latency, token/cost
    usage, and finding counts by severity and verification status. This
    is what the observability dashboard displays.
    """
    total_reviews = db.query(func.count(models.Review.id)).scalar() or 0
 
    completed_reviews = (
        db.query(func.avg(models.Review.total_latency_ms))
        .filter(models.Review.status == "completed")
        .scalar()
    )
    avg_review_latency_ms = round(completed_reviews) if completed_reviews else 0
 
    # Average latency and total tokens, grouped by agent -- this is
    # exactly the "which agent is slowest/most expensive?" question
    # we set out to answer back when we built LLM usage tracking.
    usage_by_agent = (
        db.query(
            models.LLMUsage.agent_type,
            func.avg(models.LLMUsage.latency_ms).label("avg_latency_ms"),
            func.sum(models.LLMUsage.input_tokens + models.LLMUsage.output_tokens).label("total_tokens"),
            func.count(models.LLMUsage.id).label("call_count"),
        )
        .group_by(models.LLMUsage.agent_type)
        .all()
    )
 
    # Findings grouped by agent and verification status -- this answers
    # "which agent produces the most false positives?"
    findings_by_agent = (
        db.query(
            models.Finding.agent_type,
            func.count(models.Finding.id).label("total_findings"),
            func.sum(func.cast(models.Finding.verified, Integer)).label("verified_count"),
        )
        .group_by(models.Finding.agent_type)
        .all()
    )
 
    findings_by_severity = (
        db.query(
            models.Finding.severity,
            func.count(models.Finding.id).label("count"),
        )
        .group_by(models.Finding.severity)
        .all()
    )
 
    return {
        "total_reviews": total_reviews,
        "avg_review_latency_ms": avg_review_latency_ms,
        "usage_by_agent": [
            {
                "agent_type": row.agent_type,
                "avg_latency_ms": round(row.avg_latency_ms) if row.avg_latency_ms else 0,
                "total_tokens": row.total_tokens or 0,
                "call_count": row.call_count,
            }
            for row in usage_by_agent
        ],
        "findings_by_agent": [
            {
                "agent_type": row.agent_type,
                "total_findings": row.total_findings,
                "verified_count": row.verified_count or 0,
                "false_positive_rate": round(
                    (1 - (row.verified_count or 0) / row.total_findings) * 100, 1
                ) if row.total_findings else 0,
            }
            for row in findings_by_agent
        ],
        "findings_by_severity": [
            {"severity": row.severity, "count": row.count}
            for row in findings_by_severity
        ],
    }
 
 
def save_llm_usage(db: Session, review_id: int, usage: dict) -> models.LLMUsage:
    """Save one LLM call's usage stats, linked back to its review."""
    usage_row = models.LLMUsage(
        review_id=review_id,
        agent_type=usage.get("agent_type", "unknown"),
        model=usage.get("model", "unknown"),
        input_tokens=usage.get("input_tokens", 0),
        output_tokens=usage.get("output_tokens", 0),
        cost_estimate=usage.get("cost_estimate", 0.0),
        latency_ms=usage.get("latency_ms"),
    )
    db.add(usage_row)
    db.commit()
    db.refresh(usage_row)
    return usage_row