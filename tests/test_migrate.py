"""El separador de sentencias del esquema."""

from lfm.db import migrate


def test_splits_plain_statements():
    assert migrate.statements("CREATE TABLE a (i INT); CREATE TABLE b (i INT);") == [
        "CREATE TABLE a (i INT)",
        "CREATE TABLE b (i INT)",
    ]


def test_a_semicolon_inside_a_comment_does_not_split_the_statement():
    """El fallo real del 2026-09-09: Postgres recibió media frase en castellano como sentencia."""
    sql = """
-- la web pinta la foto vigente; aquí se conserva el histórico
CREATE TABLE log (i INT);
"""
    assert migrate.statements(sql) == ["CREATE TABLE log (i INT)"]


def test_a_semicolon_inside_a_string_does_not_split_either():
    sql = "INSERT INTO t VALUES ('hola; adiós'); SELECT 1;"
    assert migrate.statements(sql) == ["INSERT INTO t VALUES ('hola; adiós')", "SELECT 1"]


def test_escaped_quotes_inside_a_string_are_survived():
    sql = "INSERT INTO t VALUES ('d''Artagnan; uno'); SELECT 2;"
    assert migrate.statements(sql) == ["INSERT INTO t VALUES ('d''Artagnan; uno')", "SELECT 2"]


def test_block_comments_are_dropped():
    assert migrate.statements("/* uno; dos */ SELECT 1;") == ["SELECT 1"]


def test_a_trailing_statement_without_semicolon_still_counts():
    assert migrate.statements("SELECT 1;\nSELECT 2") == ["SELECT 1", "SELECT 2"]


def test_comments_only_produce_nothing():
    assert migrate.statements("-- solo un comentario; con punto y coma\n") == []


def test_the_real_schema_parses_and_every_statement_is_ddl():
    """Ninguna sentencia puede empezar por prosa: eso es que un comentario se ha colado."""
    stmts = migrate.statements(migrate.SCHEMA.read_text(encoding="utf-8"))
    assert len(stmts) > 20
    # DELETE/UPDATE: limpiezas idempotentes de datos (p. ej. los ceros del backfill, 2026-09-20)
    permitidos = ("CREATE", "ALTER", "DROP", "INSERT", "COMMENT", "DO", "GRANT", "DELETE", "UPDATE")
    malas = [s[:60] for s in stmts if not s.upper().startswith(permitidos)]
    assert not malas, f"sentencias que no son DDL: {malas}"
