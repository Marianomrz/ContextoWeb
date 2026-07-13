#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CONTEXTO — Cliente mínimo de Supabase (REST/PostgREST)
=========================================================
Sin SDK: igual que agent.py habla con la API de Anthropic por requests
directo, este módulo habla con Supabase por su API REST (PostgREST) — cero
dependencias nuevas. Lo usan juridica.py y resenas.py para leer envíos
pendientes (jur_submissions / resena_submissions) y actualizar su estado
después de dictaminarlos, reemplazando el flujo anterior de archivos .md en
blog/borradores/ y resenas/borradores/.

Usa SIEMPRE la service_role key (nunca la anon key) — esta corre en el
backend y necesita saltarse Row Level Security para leer/actualizar
cualquier fila, no solo insertar la propia.
"""

import os
from datetime import datetime, timezone

import requests

SUPABASE_URL = os.environ.get("SUPABASE_URL", "").rstrip("/")
SUPABASE_SERVICE_ROLE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")


def is_configured():
    return bool(SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY)


def _headers():
    return {
        "apikey": SUPABASE_SERVICE_ROLE_KEY,
        "Authorization": f"Bearer {SUPABASE_SERVICE_ROLE_KEY}",
        "Content-Type": "application/json",
    }


def fetch_pending(table):
    """Regresa la lista de filas con status='pending' de `table`, más
    antiguas primero (para procesar en orden de llegada). Lista vacía si
    Supabase no está configurado o si la petición falla — quien llame debe
    tratar eso igual que "no hay borradores pendientes", nunca como error
    fatal (mismo espíritu fail-closed: sin conexión, simplemente no se
    publica nada, se reintenta en el siguiente ciclo)."""
    if not is_configured():
        return []
    try:
        resp = requests.get(
            f"{SUPABASE_URL}/rest/v1/{table}",
            headers=_headers(),
            params={"status": "eq.pending", "order": "created_at.asc"},
            timeout=20,
        )
        resp.raise_for_status()
        return resp.json()
    except Exception:
        return []


def update_status(table, row_id, status, veredicto=None):
    """Marca una fila como 'published' o 'rejected' y guarda su veredicto
    (dict de quality_check, o None). No lanza excepción si falla — el peor
    caso es que la fila se reprocese en el siguiente ciclo (status sigue en
    'pending'), consistente con el resto del pipeline fail-closed."""
    if not is_configured():
        return False
    try:
        resp = requests.patch(
            f"{SUPABASE_URL}/rest/v1/{table}",
            headers={**_headers(), "Prefer": "return=minimal"},
            params={"id": f"eq.{row_id}"},
            json={
                "status": status,
                "veredicto": veredicto,
                "processed_at": datetime.now(tz=timezone.utc).isoformat(),
            },
            timeout=20,
        )
        resp.raise_for_status()
        return True
    except Exception:
        return False
