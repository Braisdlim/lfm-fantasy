import os
from decimal import Decimal

import psycopg
import pytest

from lfm.db.backup import export_data, restore_data


@pytest.mark.skipif(not os.environ.get("TEST_POSTGRES_URL"), reason="Requiere Postgres de pruebas")
def test_backup_roundtrip_preserves_types_dependencies_and_sequences(tmp_path):
    url = os.environ["TEST_POSTGRES_URL"].replace("postgresql+psycopg://", "postgresql://")
    with psycopg.connect(url) as conn:
        conn.execute("CREATE TEMP TABLE backup_parent (id serial PRIMARY KEY, label text)")
        conn.execute(
            "CREATE TEMP TABLE backup_child (parent_id int REFERENCES backup_parent(id), "
            "amount numeric, payload jsonb)"
        )
        conn.execute("INSERT INTO backup_parent (id,label) VALUES (42,%s)", ("Niño\tcon salto\ny €",))
        conn.execute('INSERT INTO backup_child VALUES (42,1.23,\'{"clause": null, "active": true}\')')
        expected = conn.execute("SELECT * FROM backup_child").fetchall()
        target = tmp_path / "backup.zip"
        manifest = export_data(conn, target, tables=["backup_child", "backup_parent"])
        assert [t["name"] for t in manifest["tables"]] == ["backup_parent", "backup_child"]
        with pytest.raises(ValueError, match="no está vacía"):
            restore_data(conn, target)
        conn.execute("TRUNCATE backup_child,backup_parent")
        restore_data(conn, target)
        assert conn.execute("SELECT * FROM backup_child").fetchall() == expected
        assert conn.execute("SELECT amount FROM backup_child").fetchone()[0] == Decimal("1.23")
        assert conn.execute("SELECT label FROM backup_parent").fetchone()[0] == "Niño\tcon salto\ny €"
        assert (
            conn.execute("INSERT INTO backup_parent (label) VALUES ('next') RETURNING id").fetchone()[0] == 43
        )
        with pytest.raises(ValueError, match="credenciales"):
            export_data(conn, tmp_path / "forbidden.zip", tables=["auth_tokens"])
