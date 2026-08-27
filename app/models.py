from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    JSON,
    String,
    Text,
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.database import Base


class Installation(Base):
    """One row per GitHub account/org that has installed the app."""

    __tablename__ = "installations"

    id = Column(Integer, primary_key=True)
    github_installation_id = Column(String, unique=True, nullable=False)
    account_login = Column(String, nullable=False)
    installed_at = Column(DateTime(timezone=True), server_default=func.now())
    status = Column(String, default="active")  # active / suspended / removed

    repositories = relationship("Repository", back_populates="installation")


class Repository(Base):
    """One row per repo the app is watching."""

    __tablename__ = "repositories"

    id = Column(Integer, primary_key=True)
    installation_id = Column(Integer, ForeignKey("installations.id"))
    repo_full_name = Column(String, nullable=False, unique=True)  # e.g. "gayatri/my-repo"
    default_branch = Column(String, default="main")
    last_indexed_commit_sha = Column(String, nullable=True)
    indexed_at = Column(DateTime(timezone=True), nullable=True)

    installation = relationship("Installation", back_populates="repositories")
    reviews = relationship("Review", back_populates="repository")
    configurations = relationship("Configuration", back_populates="repository")


class Review(Base):
    """One row per PR review run (created each time a PR is opened/updated)."""

    __tablename__ = "reviews"

    id = Column(Integer, primary_key=True)
    repository_id = Column(Integer, ForeignKey("repositories.id"))
    pr_number = Column(Integer, nullable=False)
    head_sha = Column(String, nullable=False)
    status = Column(String, default="pending")  # pending / running / completed / failed
    started_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    total_latency_ms = Column(Integer, nullable=True)

    repository = relationship("Repository", back_populates="reviews")
    findings = relationship("Finding", back_populates="review")
    llm_usage = relationship("LLMUsage", back_populates="review")


class Finding(Base):
    """One row per issue an agent surfaces on a specific review."""

    __tablename__ = "findings"

    id = Column(Integer, primary_key=True)
    review_id = Column(Integer, ForeignKey("reviews.id"))
    agent_type = Column(String, nullable=False)  # security / logic / style
    file_path = Column(String, nullable=False)
    line_number = Column(Integer, nullable=True)
    severity = Column(String, nullable=True)  # low / medium / high / critical
    message = Column(Text, nullable=False)
    verified = Column(Boolean, default=False)  # passed the self-verification pass?
    false_positive_flag = Column(Boolean, default=False)  # for your eval/ablation later

    review = relationship("Review", back_populates="findings")


class LLMUsage(Base):
    """One row per LLM API call, for cost/latency tracking and observability."""

    __tablename__ = "llm_usage"

    id = Column(Integer, primary_key=True)
    review_id = Column(Integer, ForeignKey("reviews.id"))
    agent_type = Column(String, nullable=False)
    model = Column(String, nullable=False)
    input_tokens = Column(Integer, default=0)
    output_tokens = Column(Integer, default=0)
    cost_estimate = Column(Float, default=0.0)
    latency_ms = Column(Integer, nullable=True)
    timestamp = Column(DateTime(timezone=True), server_default=func.now())

    review = relationship("Review", back_populates="llm_usage")


class EvaluationRun(Base):
    """One row per benchmark run, for your Week 7 ablation study."""

    __tablename__ = "evaluation_runs"

    id = Column(Integer, primary_key=True)
    run_date = Column(DateTime(timezone=True), server_default=func.now())
    config = Column(String, nullable=False)  # llm_only / llm_rag / llm_rag_static
    precision = Column(Float, nullable=True)
    recall = Column(Float, nullable=True)
    f1 = Column(Float, nullable=True)
    notes = Column(Text, nullable=True)


class Configuration(Base):
    """Per-repo (or global, if repository_id is null) settings."""

    __tablename__ = "configuration"

    id = Column(Integer, primary_key=True)
    repository_id = Column(Integer, ForeignKey("repositories.id"), nullable=True)
    key = Column(String, nullable=False)
    value = Column(JSON, nullable=True)

    repository = relationship("Repository", back_populates="configurations")
