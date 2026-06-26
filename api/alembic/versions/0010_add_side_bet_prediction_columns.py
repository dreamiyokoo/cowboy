"""add side bet prediction columns

Revision ID: 0010
Revises: 0009
Create Date: 2026-06-17
"""
from alembic import op
import sqlalchemy as sa

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None

SIDE_BET_COLS = [
    "pred_any_flash",
    "pred_any_pair",
    "pred_any_ace",
    "pred_win_high",
    "pred_win_two",
    "pred_win_sf",
    "pred_win_fh",
    "pred_win_four",
]


def upgrade() -> None:
    for col in SIDE_BET_COLS:
        op.add_column("games", sa.Column(col, sa.Float(), nullable=True))


def downgrade() -> None:
    for col in SIDE_BET_COLS:
        op.drop_column("games", col)
