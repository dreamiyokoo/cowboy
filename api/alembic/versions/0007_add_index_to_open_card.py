"""add index to open_card

Revision ID: 0007
Revises: 0006
Create Date: 2026-06-10

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0007"
down_revision: Union[str, None] = "0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index("idx_games_open_card", "games", ["open_card"])


def downgrade() -> None:
    op.drop_index("idx_games_open_card", table_name="games")
