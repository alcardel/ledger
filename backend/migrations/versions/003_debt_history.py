from alembic import op
revision='003'
down_revision='002'
def upgrade():
    op.execute("""CREATE OR REPLACE FUNCTION prevent_history_change() RETURNS trigger AS $$
    BEGIN
      IF OLD.kind IN ('audit','override','assessment','approval','fact','bureau_report','debt_schedule') OR (OLD.kind='policy' AND OLD.data->>'status'='published') THEN
        RAISE EXCEPTION 'Immutable history cannot be changed';
      END IF;
      IF TG_OP='DELETE' THEN RETURN OLD; END IF;
      RETURN NEW;
    END; $$ LANGUAGE plpgsql""")
def downgrade():raise RuntimeError('Debt review history must remain immutable')
