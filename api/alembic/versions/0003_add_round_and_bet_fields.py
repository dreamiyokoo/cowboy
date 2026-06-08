"""add round_number, bet amounts, multipliers

Revision ID: 0003
Revises: 0002
Create Date: 2026-06-07

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ラウンド番号（ゲーム内の連番）
    op.add_column("games", sa.Column("round_number", sa.Integer(), nullable=True))

    # 各選択肢へのベット総額（単位: 表示通りのチップ数 × 1000）
    op.add_column("games", sa.Column("bet_cowboy", sa.Integer(), nullable=True))
    op.add_column("games", sa.Column("bet_draw",   sa.Integer(), nullable=True))
    op.add_column("games", sa.Column("bet_bull",   sa.Integer(), nullable=True))

    # 払い戻し倍率（例: 2.02, 22.0）
    op.add_column("games", sa.Column("mult_cowboy", sa.Numeric(10, 2), nullable=True))
    op.add_column("games", sa.Column("mult_draw",   sa.Numeric(10, 2), nullable=True))
    op.add_column("games", sa.Column("mult_bull",   sa.Numeric(10, 2), nullable=True))


def downgrade() -> None:
    op.drop_column("games", "mult_bull")
    op.drop_column("games", "mult_draw")
    op.drop_column("games", "mult_cowboy")
    op.drop_column("games", "bet_bull")
    op.drop_column("games", "bet_draw")
    op.drop_column("games", "bet_cowboy")
    op.drop_column("games", "round_number")
