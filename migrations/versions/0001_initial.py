"""Initial case and immutable review snapshot storage."""
from alembic import op
import sqlalchemy as sa
revision="0001"
down_revision=None
branch_labels=None
depends_on=None

def upgrade():
    op.create_table("cases",sa.Column("id",sa.String(32),primary_key=True),sa.Column("revision",sa.Integer(),nullable=False),sa.Column("payload",sa.Text(),nullable=False),sa.Column("created_at",sa.String(40),nullable=False))
    op.create_table("review_runs",sa.Column("id",sa.String(32),primary_key=True),sa.Column("case_id",sa.String(32),nullable=False),sa.Column("revision",sa.Integer(),nullable=False),sa.Column("status",sa.String(32),nullable=False),sa.Column("payload",sa.Text(),nullable=False),sa.Column("created_at",sa.String(40),nullable=False))
    op.create_index("ix_review_runs_case_id","review_runs",["case_id"])

def downgrade():
    op.drop_table("review_runs")
    op.drop_table("cases")
