"""allow error result

Revision ID: 0008
Revises: 0007
Create Date: 2026-06-12

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0008"
down_revision: Union[str, None] = "0007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Drop existing check constraint and create updated one
    op.drop_constraint("ck_games_result", "games", type_="check")
    op.create_check_constraint(
        "ck_games_result",
        "games",
        "result IN ('cowboy', 'draw', 'bull', 'error')"
    )


def downgrade() -> None:
    # Revert check constraint back to original values
    # Note: If there are any rows with result='error', this downgrade will fail unless they are deleted or modified.
    op.drop_constraint("ck_games_result", "games", type_="check")
    op.create_check_constraint(
        "ck_games_result",
        "games",
        "result IN ('cowboy', 'draw', 'bull')"
    )
