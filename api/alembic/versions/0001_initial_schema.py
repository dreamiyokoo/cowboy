"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-06-07

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("username", sa.String(64), nullable=False, unique=True),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )

    op.create_table(
        "games",
        sa.Column("id", sa.Integer(), primary_key=True),
        # 最初に開かれる1枚 (例: "AH", "KS", "10D")。読み取れない場合は NULL
        sa.Column("open_card", sa.String(10), nullable=True),
        # カウボーイ側ハンドタイプ (1〜3)
        sa.Column("cowboy_hand", sa.SmallInteger(), nullable=True),
        # ブル側ハンドタイプ (1〜3)
        sa.Column("bull_hand", sa.SmallInteger(), nullable=True),
        # 結果: cowboy=カウボーイ勝 / draw=抽選 / bull=ブル勝
        sa.Column("result", sa.String(10), nullable=False),
        sa.Column(
            "recorded_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint("result IN ('cowboy', 'draw', 'bull')", name="ck_games_result"),
        sa.CheckConstraint(
            "cowboy_hand IS NULL OR cowboy_hand BETWEEN 1 AND 3",
            name="ck_games_cowboy_hand",
        ),
        sa.CheckConstraint(
            "bull_hand IS NULL OR bull_hand BETWEEN 1 AND 3",
            name="ck_games_bull_hand",
        ),
    )
    op.create_index("idx_games_recorded_at", "games", ["recorded_at"])
    op.create_index("idx_games_result", "games", ["result"])


def downgrade() -> None:
    op.drop_index("idx_games_result", table_name="games")
    op.drop_index("idx_games_recorded_at", table_name="games")
    op.drop_table("games")
    op.drop_table("users")
