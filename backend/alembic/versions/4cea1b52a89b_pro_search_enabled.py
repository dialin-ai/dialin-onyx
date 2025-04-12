"""pro_search_enabled

Revision ID: 4cea1b52a89b
Revises: cf90764725d8
Create Date: 2025-04-12 11:50:49.773637

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '4cea1b52a89b'
down_revision = 'cf90764725d8'
branch_labels = None
depends_on = None

def upgrade() -> None:
    # First check if table exists
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if 'persona' in inspector.get_table_names():
        # Then check if column exists
        columns = [column['name'] for column in inspector.get_columns('persona')]
        if 'pro_search_enabled' not in columns:
            op.add_column('persona', sa.Column('pro_search_enabled', sa.Boolean(), nullable=True))


def downgrade() -> None:
    op.drop_column('persona', 'pro_search_enabled')