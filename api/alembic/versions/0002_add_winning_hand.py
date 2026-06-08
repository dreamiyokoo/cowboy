"""add winning_hand column

Revision ID: 0002
Revises: 0001
Create Date: 2026-06-07

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 勝利ハンドタイプ (1〜3)。抽選の場合や読み取れない場合は NULL
    op.add_column(
        "games",
        sa.Column("winning_hand", sa.SmallInteger(), nullable=True),
    )
    op.create_check_constraint(
        "ck_games_winning_hand",
        "games",
        "winning_hand IS NULL OR winning_hand BETWEEN 1 AND 3",
    )


def downgrade() -> None:
    op.drop_constraint("ck_games_winning_hand", "games")
    op.drop_column("games", "winning_hand")
