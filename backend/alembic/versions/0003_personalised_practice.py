"""Add optional AI analysis and resumable practice session state."""

import sqlalchemy as sa

from alembic import op

revision = "0003_personalised_practice"
down_revision = "0002_content_engine"
branch_labels = None
depends_on = None


def _columns(table):
    return {column["name"] for column in sa.inspect(op.get_bind()).get_columns(table)}


def upgrade():
    if "ai_analysis" not in _columns("job_posts"):
        op.add_column("job_posts", sa.Column("ai_analysis", sa.JSON(), nullable=True))
    if "ai_analysis_fingerprint" not in _columns("job_posts"):
        op.add_column(
            "job_posts", sa.Column("ai_analysis_fingerprint", sa.String(64), nullable=True)
        )
    if "mode" not in _columns("practice_sessions"):
        op.add_column(
            "practice_sessions",
            sa.Column("mode", sa.String(32), nullable=False, server_default="guided_practice"),
        )
    if "current_position" not in _columns("practice_sessions"):
        op.add_column(
            "practice_sessions",
            sa.Column("current_position", sa.Integer(), nullable=False, server_default="0"),
        )
    if "question_queue" not in _columns("practice_sessions"):
        op.add_column("practice_sessions", sa.Column("question_queue", sa.JSON(), nullable=True))
        op.execute(
            sa.text(
                "UPDATE practice_sessions SET question_queue = '[]' WHERE question_queue IS NULL"
            )
        )
    if "completed_at" not in _columns("practice_sessions"):
        op.add_column(
            "practice_sessions",
            sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        )
    if "evaluation" not in _columns("candidate_responses"):
        op.add_column("candidate_responses", sa.Column("evaluation", sa.JSON(), nullable=True))
    if "evaluation_method" not in _columns("candidate_responses"):
        op.add_column(
            "candidate_responses", sa.Column("evaluation_method", sa.String(40), nullable=True)
        )
    if "submission_key" not in _columns("candidate_responses"):
        op.add_column(
            "candidate_responses", sa.Column("submission_key", sa.String(80), nullable=True)
        )
        op.create_index(
            "ix_candidate_responses_submission_key",
            "candidate_responses",
            ["submission_key"],
            unique=True,
        )


def downgrade():
    # Forward-only to preserve existing session history.
    pass
