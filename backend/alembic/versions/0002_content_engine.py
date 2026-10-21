"""Add structured catalogue, reusable content, and persisted plan items."""

import sqlalchemy as sa

import app.models  # noqa: F401
from alembic import op
from app.core.database import Base

revision = "0002_content_engine"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def _columns(table_name):
    return {column["name"] for column in sa.inspect(op.get_bind()).get_columns(table_name)}


def _add_missing(table_name, columns):
    existing = _columns(table_name)
    for column in columns:
        if column.name not in existing:
            op.add_column(table_name, column)


def upgrade():
    _add_missing(
        "job_posts",
        [
            sa.Column("normalized_source_url", sa.String(2048), nullable=True),
            sa.Column("responsibilities", sa.JSON(), nullable=True),
            sa.Column("qualifications", sa.JSON(), nullable=True),
            sa.Column("competencies", sa.JSON(), nullable=True),
            sa.Column("tools_technologies", sa.JSON(), nullable=True),
            sa.Column("last_verified_at", sa.DateTime(timezone=True), nullable=True),
        ],
    )
    _add_missing(
        "job_post_versions",
        [
            sa.Column("role_title", sa.String(240), nullable=True),
            sa.Column("company_name", sa.String(200), nullable=True),
            sa.Column("content_hash", sa.String(64), nullable=True),
        ],
    )
    _add_missing("job_skills", [sa.Column("extraction_method", sa.String(40), nullable=True)])
    _add_missing(
        "questions",
        [
            sa.Column("stable_key", sa.String(160), nullable=True),
            sa.Column("category", sa.String(60), nullable=True),
            sa.Column("competencies", sa.JSON(), nullable=True),
            sa.Column(
                "primary_skill_id",
                sa.Uuid(),
                sa.ForeignKey("skills.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column("reference_answer", sa.Text(), nullable=True),
            sa.Column("common_mistakes", sa.JSON(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        ],
    )
    _add_missing(
        "learning_modules",
        [
            sa.Column("stable_key", sa.String(160), nullable=True),
            sa.Column("learning_objectives", sa.JSON(), nullable=True),
            sa.Column("core_concepts", sa.JSON(), nullable=True),
            sa.Column("examples", sa.Text(), nullable=True),
            sa.Column("common_mistakes", sa.JSON(), nullable=True),
            sa.Column("practical_exercises", sa.JSON(), nullable=True),
            sa.Column("revision_checklist", sa.JSON(), nullable=True),
            sa.Column("prerequisites", sa.JSON(), nullable=True),
        ],
    )
    _add_missing("preparation_plans", [sa.Column("content_coverage", sa.JSON(), nullable=True)])

    # Existing rows receive deterministic keys before the indexes are created.
    op.execute(
        sa.text(
            "UPDATE questions SET stable_key = 'legacy-' || CAST(id AS VARCHAR) WHERE stable_key IS NULL"
        )
    )
    op.execute(
        sa.text("UPDATE questions SET category = 'technical_fundamentals' WHERE category IS NULL")
    )
    op.execute(sa.text("UPDATE questions SET competencies = '[]' WHERE competencies IS NULL"))
    op.execute(sa.text("UPDATE questions SET reference_answer = '' WHERE reference_answer IS NULL"))
    op.execute(sa.text("UPDATE questions SET common_mistakes = '[]' WHERE common_mistakes IS NULL"))
    op.execute(
        sa.text("UPDATE questions SET created_at = CURRENT_TIMESTAMP WHERE created_at IS NULL")
    )
    op.execute(
        sa.text("UPDATE questions SET updated_at = CURRENT_TIMESTAMP WHERE updated_at IS NULL")
    )
    op.execute(
        sa.text(
            "UPDATE learning_modules SET stable_key = 'legacy-' || CAST(id AS VARCHAR) WHERE stable_key IS NULL"
        )
    )
    op.execute(
        sa.text(
            "UPDATE preparation_plans SET content_coverage = '{}' WHERE content_coverage IS NULL"
        )
    )
    op.execute(
        sa.text(
            "UPDATE job_posts SET last_verified_at = imported_at WHERE last_verified_at IS NULL"
        )
    )

    # create_all only creates tables that did not exist in the original revision;
    # it leaves existing user data and table definitions untouched.
    Base.metadata.create_all(bind=op.get_bind(), checkfirst=True)

    inspector = sa.inspect(op.get_bind())
    existing_indexes = {index["name"] for index in inspector.get_indexes("job_posts")}
    if "ix_job_posts_normalized_source_url" not in existing_indexes:
        op.create_index(
            "ix_job_posts_normalized_source_url",
            "job_posts",
            ["normalized_source_url"],
            unique=True,
        )
    existing_indexes = {
        index["name"] for index in sa.inspect(op.get_bind()).get_indexes("questions")
    }
    if "ix_questions_stable_key" not in existing_indexes:
        op.create_index("ix_questions_stable_key", "questions", ["stable_key"], unique=True)
    existing_indexes = {
        index["name"] for index in sa.inspect(op.get_bind()).get_indexes("learning_modules")
    }
    if "ix_learning_modules_stable_key" not in existing_indexes:
        op.create_index(
            "ix_learning_modules_stable_key", "learning_modules", ["stable_key"], unique=True
        )


def downgrade():
    # Deliberately non-destructive: the catalogue tables may contain user plans/content.
    # Rollback is handled by a forward repair migration if needed.
    pass
