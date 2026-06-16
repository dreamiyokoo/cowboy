"""add prediction columns

Revision ID: 0009
Revises: 0008
Create Date: 2026-06-16

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0009"
down_revision: Union[str, None] = "0008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("games", sa.Column("pred_cowboy",   sa.Float(),        nullable=True))
    op.add_column("games", sa.Column("pred_draw",     sa.Float(),        nullable=True))
    op.add_column("games", sa.Column("pred_bull",     sa.Float(),        nullable=True))
    op.add_column("games", sa.Column("pred_result",   sa.String(10),     nullable=True))
    op.add_column("games", sa.Column("model_version", sa.String(50),     nullable=True))


def downgrade() -> None:
    op.drop_column("games", "model_version")
    op.drop_column("games", "pred_result")
    op.drop_column("games", "pred_bull")
    op.drop_column("games", "pred_draw")
    op.drop_column("games", "pred_cowboy")
