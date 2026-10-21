"""Add anonymous demo ownership and shared PostgreSQL request buckets."""

import sqlalchemy as sa

import app.models  # noqa: F401
from alembic import op
from app.core.database import Base

revision = "0004_demo_sessions"
down_revision = "0003_personalised_practice"
branch_labels = None
depends_on = None


OWNED_TABLES = (
    "job_posts",
    "questions",
    "content_generation_runs",
    "preparation_plans",
    "practice_sessions",
    "candidate_responses",
)


def upgrade():
    bind = op.get_bind()
    Base.metadata.create_all(bind=bind, checkfirst=True)
    inspector = sa.inspect(bind)
    for table in OWNED_TABLES:
        columns = {column["name"] for column in inspector.get_columns(table)}
        if "owner_session_id" not in columns:
            op.add_column(
                table,
                sa.Column(
                    "owner_session_id",
                    sa.Uuid(),
                    sa.ForeignKey("demo_visitor_sessions.id", ondelete="CASCADE"),
                    nullable=True,
                ),
            )
        indexes = {index["name"] for index in sa.inspect(bind).get_indexes(table)}
        index_name = f"ix_{table}_owner_session_id"
        if index_name not in indexes:
            op.create_index(index_name, table, ["owner_session_id"])

    indexes = {index["name"]: index for index in sa.inspect(bind).get_indexes("job_posts")}
    old_job_index = indexes.get("ix_job_posts_normalized_source_url")
    if old_job_index and old_job_index.get("unique"):
        op.drop_index("ix_job_posts_normalized_source_url", table_name="job_posts")
        op.create_index(
            "ix_job_posts_normalized_source_url",
            "job_posts",
            ["normalized_source_url"],
        )

    indexes = {
        index["name"]: index for index in sa.inspect(bind).get_indexes("candidate_responses")
    }
    if "ix_candidate_responses_submission_key" in indexes:
        op.drop_index(
            "ix_candidate_responses_submission_key", table_name="candidate_responses"
        )
    indexes = {
        index["name"] for index in sa.inspect(bind).get_indexes("candidate_responses")
    }
    if "ix_candidate_responses_owner_submission_key" not in indexes:
        op.create_index(
            "ix_candidate_responses_owner_submission_key",
            "candidate_responses",
            ["owner_session_id", "submission_key"],
            unique=True,
        )

    constraints = {
        constraint["name"]: constraint
        for constraint in sa.inspect(bind).get_unique_constraints("questions")
    }
    text_constraint = next(
        (
            name
            for name, constraint in constraints.items()
            if constraint.get("column_names") == ["question_text"]
        ),
        None,
    )
    if text_constraint:
        op.drop_constraint(text_constraint, "questions", type_="unique")


def downgrade():
    # Forward-only: removing ownership columns would weaken access controls and risk data loss.
    pass
