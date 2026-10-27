"""
The actual PR review pipeline -- runs as a background task AFTER the webhook
handler has already responded 200 to GitHub.
"""
 
import logging
import time
 
from app import crud
from app.agents.orchestrator import run_all_agents
from app.code_indexer import ensure_repo_cloned, index_repository
from app.database import SessionLocal
from app.github_api import get_pr_diff
from app.github_auth import get_installation_token
from app.llm_client import get_and_clear_usage_log
from app.pr_comment import post_review_comment
from app.security_filters import redact_secrets
 
logger = logging.getLogger("pr-sentinel")
 
 
def process_pr_event(
    review_id: int,
    repository_id: int,
    installation_id: str,
    repo_full_name: str,
    clone_url: str,
    default_branch: str,  # pylint: disable=unused-argument
    pr_number: int,
    head_sha: str,
) -> None:
    """
    Does all the slow work for one PR review. Uses its OWN database session,
    because the request-scoped one is closed once the HTTP response is sent.
    Logs how long each phase takes, so latency can be attributed to a cause.
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
 
        t0 = time.perf_counter()
        token = get_installation_token(installation_id)
        local_repo_path = ensure_repo_cloned(
            repo_full_name=repo_full_name,
            clone_url=clone_url,
            installation_token=token,
            pr_number=pr_number,
            head_sha=head_sha,
        )
        checkout_s = time.perf_counter() - t0
        logger.info("[review %s] Checked out PR head %s at: %s", review_id, head_sha[:8], local_repo_path)
 
        t1 = time.perf_counter()
        repository_row = crud.get_repository_by_id(db, repository_id)
        if repository_row.last_indexed_commit_sha == head_sha:
            logger.info("[review %s] Already indexed at this commit -- skipping re-indexing.", review_id)
        else:
            chunk_count = index_repository(repo_full_name, local_repo_path)
            crud.mark_repository_indexed(db, repository_row, head_sha)
            logger.info("[review %s] Indexed %s code chunks.", review_id, chunk_count)
        index_s = time.perf_counter() - t1
 
        t2 = time.perf_counter()
        findings, ai_status = run_all_agents(diff_text, repo_path=local_repo_path)
        analysis_s = time.perf_counter() - t2
        logger.info("[review %s] Analysis produced %s findings.", review_id, len(findings))
 
        logger.info(
            "[review %s] Phase timings: checkout %.1fs | indexing %.1fs | analysis %.1fs",
            review_id, checkout_s, index_s, analysis_s,
        )
        logger.info("[review %s] AI analysis status:", review_id)
        for agent_name, status in ai_status.items():
            symbol = "OK" if status == "ok" else "UNAVAILABLE"
            logger.info("  [%s] %s: %s", symbol, agent_name, status)
 
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
 
        # Show the results to the people using the PR. A failure here (for
        # example a missing permission) must never fail the review itself.
        try:
            post_review_comment(
                installation_id=installation_id,
                repo_full_name=repo_full_name,
                pr_number=pr_number,
                review_id=review_id,
                findings=findings,
                ai_status=ai_status,
            )
            logger.info("[review %s] Posted summary comment on PR #%s.", review_id, pr_number)
        except Exception as comment_error:  # pylint: disable=broad-exception-caught
            logger.error("[review %s] Could not post PR comment: %s", review_id, comment_error)
 
        crud.mark_review_completed(db, review_row)
        logger.info("[review %s] Pipeline completed successfully.", review_id)
 
    except Exception as e:  # pylint: disable=broad-exception-caught
        logger.error("[review %s] Pipeline failed: %s", review_id, e)
        try:
            review_row = crud.get_review_by_id(db, review_id)
            crud.mark_review_failed(db, review_row)
        except Exception as inner_e:  # pylint: disable=broad-exception-caught
            logger.error("[review %s] Additionally failed to mark review as failed: %s", review_id, inner_e)
    finally:
        db.close()