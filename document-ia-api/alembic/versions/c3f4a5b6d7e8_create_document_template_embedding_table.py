"""Create document_template_embedding table

Revision ID: c3f4a5b6d7e8
Revises: b1d2a3c4e5f6
Create Date: 2026-03-26 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c3f4a5b6d7e8"
down_revision: Union[str, Sequence[str], None] = "b1d2a3c4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


class Vector(sa.types.UserDefinedType):
    def __init__(self, dimensions: int):
        self.dimensions = dimensions

    def get_col_spec(self, **kwargs):
        return f"vector({self.dimensions})"


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "document_template_embedding",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "document_type_code",
            sa.String(length=100),
            nullable=False,
        ),
        sa.Column(
            "document_instance_id",
            sa.String(length=100),
            nullable=False,
        ),
        sa.Column("page_number", sa.Integer(), nullable=False),
        sa.Column("anonymized_text", sa.Text(), nullable=False),
        sa.Column("embedding", Vector(1024), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_index(
        "document_template_embedding_embedding_hnsw_idx",
        "document_template_embedding",
        ["embedding"],
        postgresql_using="hnsw",
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(
        "document_template_embedding_embedding_hnsw_idx",
        table_name="document_template_embedding",
    )
    op.drop_table("document_template_embedding")
