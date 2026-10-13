"""HTML crudo completo, comprimido sin pérdida para almacenamiento y copias."""

import base64
import gzip
import hashlib
import io
from collections.abc import Callable

from sqlalchemy import text

MAX_HTML_BYTES = 64 * 1024 * 1024


def pack_html(html: str) -> dict:
    body = html.encode("utf-8")
    return {
        "format": "html-gzip-v1",
        "html_gzip_base64": base64.b64encode(gzip.compress(body, mtime=0)).decode("ascii"),
        "html_sha256": hashlib.sha256(body).hexdigest(),
    }


def store_html(conn, html: str) -> dict:
    """Una copia binaria por contenido, manteniendo cada captura y su fecha."""
    body = html.encode("utf-8")
    digest = hashlib.sha256(body).hexdigest()
    conn.execute(
        text(
            "INSERT INTO raw_html_blobs (sha256, body) VALUES (:sha256, :body) "
            "ON CONFLICT (sha256) DO NOTHING"
        ),
        {"sha256": digest, "body": gzip.compress(body, mtime=0)},
    )
    return {"format": "html-gzip-ref-v1", "html_sha256": digest}


def unpack_html(payload: dict, *, load_blob: Callable[[str], bytes] | None = None) -> str:
    if "html" in payload:
        return payload["html"]  # Compatibilidad con capturas anteriores.
    if payload.get("format") == "html-gzip-ref-v1":
        if load_blob is None:
            from lfm.db.session import engine

            with engine().connect() as conn:
                compressed = conn.execute(
                    text("SELECT body FROM raw_html_blobs WHERE sha256=:sha256"),
                    {"sha256": payload["html_sha256"]},
                ).scalar_one()
        else:
            compressed = load_blob(payload["html_sha256"])
    elif payload.get("format") == "html-gzip-v1":
        compressed = base64.b64decode(payload["html_gzip_base64"], validate=True)
    else:
        raise ValueError("Formato de HTML desconocido")
    with gzip.GzipFile(fileobj=io.BytesIO(compressed)) as stream:
        body = stream.read(MAX_HTML_BYTES + 1)
    if len(body) > MAX_HTML_BYTES:
        raise ValueError("HTML demasiado grande")
    if hashlib.sha256(body).hexdigest() != payload["html_sha256"]:
        raise ValueError("HTML sin integridad verificable")
    return body.decode("utf-8")
