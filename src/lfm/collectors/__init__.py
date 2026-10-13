"""Colectores: cada módulo pide un endpoint, guarda el crudo y normaliza a tablas.

Contrato de cada colector:
    collect_<x>(client, conn, *, day) -> dict  (resumen: filas escritas, avisos)
El crudo lo guarda el cliente vía callback; aquí solo se normaliza.
"""
