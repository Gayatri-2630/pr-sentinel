"""
The actual PR review pipeline -- runs as a background task, AFTER the
webhook handler has already responded 200 to GitHub. Separated from
main.py so the webhook layer stays focused purely on "receive and
acknowledge quickly," while this module owns "do the actual, slow work."
"""
 
import logging
 
from app import crud
from app.agents.orchestrator import run_all_agents
from app.code_indexer import ensure_repo_cloned, index_repository
from app.database import SessionLocal
from app.github_api import get_pr_diff
from app.github_auth import get_installation_token
from app.llm_client import get_and_clear_usage_log
from app.security_filters import redact_secrets
 
logger = logging.getLogger("pr-sentinel")
 
 
def process_pr_event(
    review_id: int,
    repository_id: int,
    installation_id: str,
    repo_full_name: str,
    clone_url: str,
    default_branch: str,
    pr_number: int,
    head_sha: str,
) -> None:
    """
    Does all the slow work for one PR review: fetch diff, clone/index the
    repo, run AI agents + static analysis, save everything. Runs in the
    background, entirely separate from the HTTP request/response cycle.
 
    Uses its OWN fresh database session (SessionLocal(), not the
    request-scoped one from the webhook handler) -- that session gets
    closed the moment the HTTP response is sent, so reusing it here would
    fail once the background task actually runs.
    """
    db = SessionLocal()
    try:
        review_row = crud.get_review_by_id(db, review_id)
        crud.mark_review_started(db, review_row)
 
        diff_text = get_pr_diff(
            installation_id=installation_id,
            repo_full_name=repo_full_name,
            pr_number=pr_number,
        )
        diff_text = redact_secrets(diff_text)
        logger.info("[review %s] Fetched diff, %s characters.", review_id, len(diff_text))
 
        token = get_installation_token(installation_id)
        local_repo_path = ensure_repo_cloned(
            repo_full_name=repo_full_name,
            clone_url=clone_url,
            installation_token=token,
        )
        logger.info("[review %s] Repo available locally at: %s", review_id, local_repo_path)
 
        repository_row = crud.get_repository_by_id(db, repository_id)
 
        if repository_row.last_indexed_commit_sha == head_sha:
            logger.info("[review %s] Repo already indexed at this commit -- skipping re-indexing.", review_id)
        else:
            chunk_count = index_repository(repo_full_name, local_repo_path)
            crud.mark_repository_indexed(db, repository_row, head_sha)
            logger.info("[review %s] Indexed %s code chunks.", review_id, chunk_count)
 
        findings, ai_status = run_all_agents(diff_text, repo_path=local_repo_path)
        logger.info("[review %s] Agents produced %s findings.", review_id, len(findings))
 
        logger.info("=" * 50)
        logger.info("[review %s] AI analysis status:", review_id)
        for agent_name, status in ai_status.items():
            symbol = "OK" if status == "ok" else "UNAVAILABLE"
            logger.info("  [%s] %s: %s", symbol, agent_name, status)
        logger.info("Static analysis: bandit + pylint always attempted.")
        logger.info("=" * 50)
 
        for finding in findings:
            crud.save_finding(db, review_id=review_id, finding=finding)
            verified_tag = "VERIFIED" if finding.get("verified") else "UNVERIFIED"
            logger.info(
                "  [%s] [%s] [%s] %s: %s",
                finding["agent_type"].upper(), finding["severity"].upper(),
                verified_tag, finding["file_path"], finding["message"],
            )
 
        usage_records = get_and_clear_usage_log()
        for usage in usage_records:
            crud.save_llm_usage(db, review_id=review_id, usage=usage)
        total_tokens = sum(u["input_tokens"] + u["output_tokens"] for u in usage_records)
        logger.info("[review %s] Logged %s LLM calls, %s total tokens.", review_id, len(usage_records), total_tokens)
 
        crud.mark_review_completed(db, review_row)
        logger.info("[review %s] Pipeline completed successfully.", review_id)
 
    except Exception as e:  # pylint: disable=broad-exception-caught
        # A crashed background task has nowhere to report to except logs
        # and the database -- there's no HTTP response left to send an
        # error back through, since we already returned 200 to GitHub.
        logger.error("[review %s] Pipeline failed: %s", review_id, e)
        try:
            review_row = crud.get_review_by_id(db, review_id)
            crud.mark_review_failed(db, review_row)
        except Exception as inner_e:  # pylint: disable=broad-exception-caught
            logger.error("[review %s] Additionally failed to mark review as failed: %s", review_id, inner_e)
    finally:
        db.close()