"""add card_image column to games

Revision ID: 0005
Revises: 0004
Create Date: 2026-06-09

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0005"
down_revision: Union[str, None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # オープンカードのクロップ画像（base64 JPEG, data URL形式）
    op.add_column("games", sa.Column("card_image", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("games", "card_image")
