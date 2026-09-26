from alembic import op
from app.db import Base
revision='001'
down_revision=None

def upgrade():
    Base.metadata.create_all(op.get_bind())
    op.execute("ALTER TABLE records ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE records FORCE ROW LEVEL SECURITY")
    op.execute("CREATE POLICY tenant_isolation ON records USING (org_id = current_setting('app.org_id', true)) WITH CHECK (org_id = current_setting('app.org_id', true))")
    op.execute("""CREATE FUNCTION prevent_history_change() RETURNS trigger AS $$
    BEGIN
      IF OLD.kind IN ('audit','override','assessment','approval','fact') OR (OLD.kind='policy' AND OLD.data->>'status'='published') THEN
        RAISE EXCEPTION 'Immutable history cannot be changed';
      END IF;
      IF TG_OP='DELETE' THEN RETURN OLD; END IF;
      RETURN NEW;
    END; $$ LANGUAGE plpgsql""")
    op.execute('CREATE TRIGGER immutable_history BEFORE UPDATE OR DELETE ON records FOR EACH ROW EXECUTE FUNCTION prevent_history_change()')

def downgrade():
    op.execute('DROP TABLE records'); op.execute('DROP FUNCTION prevent_history_change()')
