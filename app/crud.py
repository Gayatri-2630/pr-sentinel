"""
Small database helper functions -- the standard 'CRUD' layer that sits between
the webhook handler and the raw SQLAlchemy models. Keeping this separate from
main.py keeps the webhook handler focused on "what happened" rather than
"how do I save it."
"""
 
from datetime import datetime, timezone
 
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
    db.refresh(installation)  # pulls back the auto-generated id, so we can use it right away
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
 
 
def create_review(db: Session, repository_id: int, pr_number: int, head_sha: str) -> models.Review:
    review = models.Review(
        repository_id=repository_id,
        pr_number=pr_number,
        head_sha=head_sha,
        status="running",
        started_at=datetime.now(timezone.utc),
    )
    db.add(review)
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
    )
    db.add(finding_row)
    db.commit()
    db.refresh(finding_row)
    return finding_row
 
 
def mark_review_completed(db: Session, review: models.Review) -> models.Review:
    review.status = "completed"
    review.completed_at = datetime.now(timezone.utc)
    if review.started_at:
        # started_at is stored timezone-aware, so this subtraction is safe
        delta = review.completed_at - review.started_at
        review.total_latency_ms = int(delta.total_seconds() * 1000)
    db.commit()
    db.refresh(review)
    return review