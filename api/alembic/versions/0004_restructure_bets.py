"""restructure bets: 11 positions + 8 win flags

Revision ID: 0004
Revises: 0003
Create Date: 2026-06-07

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0004"
down_revision: Union[str, None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 旧カラムを削除
    op.drop_column("games", "winning_hand")
    op.drop_column("games", "mult_cowboy")
    op.drop_column("games", "mult_draw")
    op.drop_column("games", "mult_bull")
    op.drop_column("games", "bet_cowboy")
    op.drop_column("games", "bet_draw")
    op.drop_column("games", "bet_bull")

    # 上段3つ（メイン結果）のベット額
    op.add_column("games", sa.Column("bet_cowboy",   sa.Integer(), nullable=True))
    op.add_column("games", sa.Column("bet_draw",     sa.Integer(), nullable=True))
    op.add_column("games", sa.Column("bet_bull",     sa.Integer(), nullable=True))

    # 任意のハンド（左列）3種
    op.add_column("games", sa.Column("bet_any_flash", sa.Integer(), nullable=True))
    op.add_column("games", sa.Column("bet_any_pair",  sa.Integer(), nullable=True))
    op.add_column("games", sa.Column("bet_any_ace",   sa.Integer(), nullable=True))

    # 勝利ハンド（右列）5種
    op.add_column("games", sa.Column("bet_win_high",  sa.Integer(), nullable=True))
    op.add_column("games", sa.Column("bet_win_two",   sa.Integer(), nullable=True))
    op.add_column("games", sa.Column("bet_win_sf",    sa.Integer(), nullable=True))
    op.add_column("games", sa.Column("bet_win_fh",    sa.Integer(), nullable=True))
    op.add_column("games", sa.Column("bet_win_four",  sa.Integer(), nullable=True))

    # WIN フラグ（任意のハンド 3種）
    op.add_column("games", sa.Column("win_any_flash", sa.Boolean(), nullable=True))
    op.add_column("games", sa.Column("win_any_pair",  sa.Boolean(), nullable=True))
    op.add_column("games", sa.Column("win_any_ace",   sa.Boolean(), nullable=True))

    # WIN フラグ（勝利ハンド 5種）
    op.add_column("games", sa.Column("win_high",  sa.Boolean(), nullable=True))
    op.add_column("games", sa.Column("win_two",   sa.Boolean(), nullable=True))
    op.add_column("games", sa.Column("win_sf",    sa.Boolean(), nullable=True))
    op.add_column("games", sa.Column("win_fh",    sa.Boolean(), nullable=True))
    op.add_column("games", sa.Column("win_four",  sa.Boolean(), nullable=True))


def downgrade() -> None:
    for col in ["win_four", "win_fh", "win_sf", "win_two", "win_high",
                "win_any_ace", "win_any_pair", "win_any_flash",
                "bet_win_four", "bet_win_fh", "bet_win_sf", "bet_win_two", "bet_win_high",
                "bet_any_ace", "bet_any_pair", "bet_any_flash",
                "bet_bull", "bet_draw", "bet_cowboy"]:
        op.drop_column("games", col)

    op.add_column("games", sa.Column("bet_cowboy",   sa.Integer(), nullable=True))
    op.add_column("games", sa.Column("bet_draw",     sa.Integer(), nullable=True))
    op.add_column("games", sa.Column("bet_bull",     sa.Integer(), nullable=True))
    op.add_column("games", sa.Column("mult_cowboy",  sa.Numeric(10, 2), nullable=True))
    op.add_column("games", sa.Column("mult_draw",    sa.Numeric(10, 2), nullable=True))
    op.add_column("games", sa.Column("mult_bull",    sa.Numeric(10, 2), nullable=True))
    op.add_column("games", sa.Column("winning_hand", sa.SmallInteger(), nullable=True))
