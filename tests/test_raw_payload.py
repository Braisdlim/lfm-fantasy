import os

import pytest
from sqlalchemy import create_engine, text

from lfm.db import raw_payload


def test_raw_html_roundtrip_keeps_every_byte_and_checks_integrity():
    html = "<html><p>Niño, balón y €</p>\n" + '<script>const repeated="data";</script>' * 1000 + "</html>"
    payload = raw_payload.pack_html(html)
    assert len(payload["html_gzip_base64"]) < len(html) / 10
    assert raw_payload.unpack_html(payload) == html
    assert raw_payload.unpack_html({"html": html}) == html
    with pytest.raises(ValueError, match="integridad"):
        raw_payload.unpack_html({**payload, "html_sha256": "0" * 64})


def test_raw_html_refuses_oversized_and_unknown_data(monkeypatch):
    monkeypatch.setattr(raw_payload, "MAX_HTML_BYTES", 10)
    with pytest.raises(ValueError, match="grande"):
        raw_payload.unpack_html(raw_payload.pack_html("x" * 11))
    with pytest.raises(ValueError, match="Formato"):
        raw_payload.unpack_html({"format": "unknown"})


@pytest.mark.skipif(not os.environ.get("TEST_POSTGRES_URL"), reason="requiere Postgres")
def test_binary_blob_deduplicates_and_roundtrips_in_postgres():
    engine = create_engine(os.environ["TEST_POSTGRES_URL"])
    try:
        with engine.begin() as conn:
            conn.execute(
                text("CREATE TEMP TABLE raw_html_blobs (sha256 text PRIMARY KEY, body bytea) ON COMMIT DROP")
            )
            html = "<html>Niño y €</html>" * 1000
            first = raw_payload.store_html(conn, html)
            assert raw_payload.store_html(conn, html) == first
            assert conn.execute(text("SELECT count(*) FROM raw_html_blobs")).scalar() == 1
            body = conn.execute(text("SELECT body FROM raw_html_blobs")).scalar_one()
            assert raw_payload.unpack_html(first, load_blob=lambda _: body) == html
            with pytest.raises(ValueError, match="integridad"):
                raw_payload.unpack_html({**first, "html_sha256": "0" * 64}, load_blob=lambda _: body)
    finally:
        engine.dispose()
