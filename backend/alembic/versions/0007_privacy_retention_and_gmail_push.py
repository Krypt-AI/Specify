"""privacy retention and gmail push

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-26 23:10:00
"""
from alembic import op
import sqlalchemy as sa

revision = '0007'
down_revision = '0006'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('email_messages', sa.Column('body_purged_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('gmail_sync_states', sa.Column('watch_expires_at', sa.DateTime(timezone=True), nullable=True))
    # Tones such as "friendly and professional" are longer than the original column allowed.
    with op.batch_alter_table('email_drafts') as batch:
        batch.alter_column('tone', existing_type=sa.String(length=16), type_=sa.String(length=40), existing_nullable=False)


def downgrade() -> None:
    with op.batch_alter_table('email_drafts') as batch:
        batch.alter_column('tone', existing_type=sa.String(length=40), type_=sa.String(length=16), existing_nullable=False)
    with op.batch_alter_table('gmail_sync_states') as batch:
        batch.drop_column('watch_expires_at')
    with op.batch_alter_table('email_messages') as batch:
        batch.drop_column('body_purged_at')
