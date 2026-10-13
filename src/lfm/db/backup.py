"""Copia portable de datos para Postgres 17, sin tokens de autenticación.

El fichero contiene el esquema, un manifiesto y COPY binario por tabla. Se
restaura solo sobre una base vacía y con la misma versión mayor de Postgres.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import zipfile
from datetime import UTC, datetime
from pathlib import Path

import psycopg
from psycopg import sql

from lfm.config import settings

SCHEMA = Path(__file__).with_name("schema.sql")


def export_data(conn, output: Path, *, tables: list[str] | None = None) -> dict:
    """La conexión debe estar dentro de una transacción REPEATABLE READ."""
    if tables is None:
        tables = [
            row[0]
            for row in conn.execute(
                "SELECT tablename FROM pg_tables WHERE schemaname='public' "
                "AND tablename <> 'auth_tokens' ORDER BY tablename"
            )
        ]
    if "auth_tokens" in tables:
        raise ValueError("No se exportan credenciales")
    manifest = {
        "format": 1,
        "created_at": datetime.now(UTC).isoformat(),
        "postgres_major": conn.info.server_version // 10000,
        "excluded_tables": ["auth_tokens"],
        "tables": [],
    }
    dependencies = {}
    for table in tables:
        dependencies[table] = {
            row[0]
            for row in conn.execute(
                "SELECT DISTINCT parent.relname FROM pg_constraint c "
                "JOIN pg_class parent ON parent.oid=c.confrelid "
                "WHERE c.contype='f' AND c.conrelid=to_regclass(%s)",
                (table,),
            )
            if row[0] in tables and row[0] != table
        }
    pending = set(tables)
    ordered = []
    while pending:
        ready = sorted(t for t in pending if not dependencies[t] & pending)
        if not ready:
            raise ValueError("Dependencias cíclicas: no se puede restaurar automáticamente")
        ordered.extend(ready)
        pending.difference_update(ready)
    partial = output.with_suffix(output.suffix + ".partial")
    try:
        with zipfile.ZipFile(partial, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.write(SCHEMA, "schema.sql")
            for table in ordered:
                columns = [
                    row[0]
                    for row in conn.execute(
                        "SELECT attname FROM pg_attribute WHERE attrelid=to_regclass(%s) "
                        "AND attnum>0 AND NOT attisdropped ORDER BY attnum",
                        (table,),
                    )
                ]
                count = conn.execute(
                    sql.SQL("SELECT count(*) FROM {}").format(sql.Identifier(table))
                ).fetchone()[0]
                query = sql.SQL("COPY {} ({}) TO STDOUT (FORMAT BINARY)").format(
                    sql.Identifier(table), sql.SQL(",").join(map(sql.Identifier, columns))
                )
                digest = hashlib.sha256()
                size = 0
                with archive.open(table + ".copy", "w") as dest:
                    with conn.cursor() as cursor, cursor.copy(query) as stream:
                        for chunk in stream:
                            digest.update(chunk)
                            size += len(chunk)
                            dest.write(chunk)
                manifest["tables"].append(
                    {
                        "name": table,
                        "columns": columns,
                        "rows": count,
                        "bytes": size,
                        "sha256": digest.hexdigest(),
                    }
                )
            archive.writestr("manifest.json", json.dumps(manifest, indent=2))
        partial.replace(output)
    finally:
        partial.unlink(missing_ok=True)
    return manifest


def restore_data(conn, backup: Path) -> dict:
    """Aplicar antes schema.sql; nunca sobrescribe una base con datos."""
    with zipfile.ZipFile(backup) as archive:
        manifest = json.loads(archive.read("manifest.json"))
        if manifest["format"] != 1 or manifest["postgres_major"] != conn.info.server_version // 10000:
            raise ValueError("Formato o versión de Postgres incompatible")
        for table in manifest["tables"]:
            name = table["name"]
            if name == "auth_tokens":
                raise ValueError("La copia no puede contener credenciales")
            if conn.execute(
                sql.SQL("SELECT EXISTS (SELECT 1 FROM {})").format(sql.Identifier(name))
            ).fetchone()[0]:
                raise ValueError("La base de destino no está vacía")
            digest = hashlib.sha256()
            with archive.open(name + ".copy") as source:
                while chunk := source.read(1024 * 1024):
                    digest.update(chunk)
            if digest.hexdigest() != table["sha256"]:
                raise ValueError("La copia no supera la comprobación de integridad")
        for table in manifest["tables"]:
            name = table["name"]
            query = sql.SQL("COPY {} ({}) FROM STDIN (FORMAT BINARY)").format(
                sql.Identifier(name), sql.SQL(",").join(map(sql.Identifier, table["columns"]))
            )
            with archive.open(name + ".copy") as source:
                with conn.cursor() as cursor, cursor.copy(query) as stream:
                    while chunk := source.read(1024 * 1024):
                        stream.write(chunk)
            for column in table["columns"]:
                sequence = conn.execute("SELECT pg_get_serial_sequence(%s,%s)", (name, column)).fetchone()[0]
                if sequence:
                    maximum = conn.execute(
                        sql.SQL("SELECT max({}) FROM {}").format(sql.Identifier(column), sql.Identifier(name))
                    ).fetchone()[0]
                    if maximum is not None:
                        conn.execute("SELECT setval(%s,%s,true)", (sequence, maximum))
            count = conn.execute(sql.SQL("SELECT count(*) FROM {}").format(sql.Identifier(name))).fetchone()[
                0
            ]
            if count != table["rows"]:
                raise ValueError("Número de registros restaurados incorrecto")
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument("command", choices=["export", "restore"])
    parser.add_argument("path", type=Path)
    args = parser.parse_args()
    url = settings.database_url.replace("postgresql+psycopg://", "postgresql://")
    with psycopg.connect(url) as conn:
        if args.command == "export":
            conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
            manifest = export_data(conn, args.path)
        else:
            manifest = restore_data(conn, args.path)
    print(
        json.dumps(
            {
                "tables": len(manifest["tables"]),
                "rows": sum(t["rows"] for t in manifest["tables"]),
                "created_at": manifest["created_at"],
            }
        )
    )


if __name__ == "__main__":
    main()
