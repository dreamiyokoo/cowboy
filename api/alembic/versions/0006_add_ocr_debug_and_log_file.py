"""add ocr_debug and log_file_name columns to games

Revision ID: 0006
Revises: 0005
Create Date: 2026-06-10

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0006"
down_revision: Union[str, None] = "0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("games", sa.Column("ocr_debug", sa.Text(), nullable=True))
    op.add_column("games", sa.Column("log_file_name", sa.String(length=100), nullable=True))


def downgrade() -> None:
    op.drop_column("games", "log_file_name")
    op.drop_column("games", "ocr_debug")
