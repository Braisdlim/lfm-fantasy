from lfm.db.session import dsn


def test_dsn_forces_psycopg3_driver():
    # Neon entrega postgresql://...; sin sufijo SQLAlchemy buscaría psycopg2
    assert dsn("postgresql://u:p@h/db?sslmode=require") == "postgresql+psycopg://u:p@h/db?sslmode=require"
    assert dsn("postgres://u:p@h/db") == "postgresql+psycopg://u:p@h/db"
    assert dsn("postgresql+psycopg://u:p@h/db") == "postgresql+psycopg://u:p@h/db"
