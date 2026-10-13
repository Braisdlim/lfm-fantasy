"""Presupuesto antes de recoger: API de control de Neon, sin despertar Postgres.

Reserva 500 MB de transferencia y 10 CU-h para navegación/intervención antes
del límite preventivo del proveedor. Un error de medición impide recoger.
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path

import httpx

HARD = {
    "data_transfer_bytes": 4_000_000_000,
    "compute_time_seconds": 288_000,
    "logical_size_bytes": 900_000_000,
}
SOFT = {
    "data_transfer_bytes": 3_500_000_000,
    "compute_time_seconds": 252_000,
    "synthetic_storage_size": 800_000_000,
}


def assess(project: dict) -> dict:
    """Falla cerrado ante métricas ausentes, inválidas o cuotas retiradas."""
    quotas = project.get("settings", {}).get("quota", {})
    reasons = []
    for name, ceiling in HARD.items():
        quota = quotas.get(name)
        if type(quota) is not int or not 0 < quota <= ceiling:
            reasons.append(f"Límite preventivo sin confirmar: {name}")
    usage = {}
    for name, ceiling in SOFT.items():
        value = project.get(name)
        if type(value) is not int or value < 0:
            reasons.append(f"Medición inválida: {name}")
        else:
            usage[name] = value
            if value >= ceiling:
                reasons.append(f"Reserva alcanzada: {name} ({value}/{ceiling})")
    # Una respuesta PATCH puede traer ceros y fechas 0001: solo aceptar un GET
    # con periodo corriente. No interpretar un contador ausente como consumo cero.
    try:
        start = datetime.fromisoformat(project["consumption_period_start"].replace("Z", "+00:00"))
        end = datetime.fromisoformat(project["consumption_period_end"].replace("Z", "+00:00"))
        if not start <= datetime.now(UTC) < end:
            reasons.append("Periodo de consumo no vigente")
    except (KeyError, ValueError, TypeError):
        reasons.append("Periodo de consumo inválido")
    return {
        "collect": not reasons,
        "reasons": reasons,
        "usage": usage,
        "soft_limits": SOFT,
        "hard_limits": quotas,
    }


def main() -> None:
    key, project_id = os.environ.get("NEON_API_KEY"), os.environ.get("NEON_PROJECT_ID")
    if not key or not project_id:
        raise SystemExit("Falta la credencial del control de consumo; recogida detenida")
    # No registrar cabeceras, credenciales ni el cuerpo completo de la cuenta.
    try:
        response = httpx.get(
            f"https://console.neon.tech/api/v2/projects/{project_id}",
            headers={"Authorization": f"Bearer {key}"},
            timeout=20,
        )
        response.raise_for_status()
        report = assess(response.json()["project"])
    except (httpx.HTTPError, KeyError, ValueError):
        raise SystemExit("No se pudo verificar el consumo de Neon; recogida detenida") from None
    report["checked_at"] = datetime.now(UTC).isoformat()
    Path("neon-usage.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))
    if output := os.environ.get("GITHUB_OUTPUT"):
        with Path(output).open("a", encoding="utf-8") as stream:
            stream.write(f"collect={str(report['collect']).lower()}\n")
    if summary := os.environ.get("GITHUB_STEP_SUMMARY"):
        with Path(summary).open("a", encoding="utf-8") as stream:
            stream.write("### Presupuesto Neon\n\n")
            stream.write(
                "Recogida permitida.\n"
                if report["collect"]
                else "**Recogida pausada para conservar margen.**\n"
            )
            stream.write("\n```json\n" + json.dumps(report, indent=2) + "\n```\n")
    if not report["collect"]:
        print("::warning::Recogida pausada: " + "; ".join(report["reasons"]))


if __name__ == "__main__":
    main()
