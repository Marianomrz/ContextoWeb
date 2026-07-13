#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CONTEXTO — Reseñas de lectores ("Correo del lector")
======================================================
Pipeline editorial para testimonios reales enviados por lectores:

  1. El lector manda su reseña por el formulario de index.html (guarda una
     fila en la tabla `resena_submissions` de Supabase, status='pending';
     ver agent/supabase_client.py). Hasta el 10 jul 2026 esto era un correo
     que Mariano copiaba a mano a resenas/borradores/*.md — ese flujo
     manual quedó retirado (mismo cambio que en la Revista Jurídica); los
     archivos .md viejos en resenas/borradores/, resenas/publicadas/ y
     resenas/rechazadas/ son solo respaldo histórico, ya no se leen.
  2. El consejo editorial (quality.py, rúbrica de reseñas con moderación)
     decide: aprobada → se publica en testimonios.json y el frontend la
     renderiza en "Correo del lector" (ver renderLetters en app.js);
     inapropiada → la fila en Supabase pasa a status='rejected' con su
     veredicto en la columna `veredicto`.

Filosofía de fallos: FAIL-CLOSED, igual que la revista jurídica — una
reseña pública atribuida a una persona con nombre jamás se publica sin
pasar por moderación, ni siquiera por un error técnico de la API (al
contrario que las noticias, donde un fallo técnico publica con advertencia).

Ejecución independiente:
  export ANTHROPIC_API_KEY="..."
  export SUPABASE_URL="..." SUPABASE_SERVICE_ROLE_KEY="..."
  python agent/resenas.py
(agent.py también lo invoca en cada ciclo.)
"""

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from quality import quality_check
import llm_client   # interruptor Anthropic ⇄ Inception Labs/Mercury
import supabase_client

BASE_DIR = Path(__file__).resolve().parent.parent
TESTIMONIOS_JSON = BASE_DIR / "testimonios.json"
QC_LOG_FILE = Path(__file__).resolve().parent / "qc_log.json"
SUPABASE_TABLE = "resena_submissions"

# tope de reseñas vivas en el portal (las más recientes primero) — mismo
# criterio que MAX_ARTICLES_KEPT en agent.py, para no dejar crecer el JSON sin fin
MAX_TESTIMONIOS_KEPT = 30


def log(msg):
    stamp = datetime.now().strftime("%H:%M:%S")
    print(f"[{stamp}] {msg}", flush=True)


def load_json(path, default):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def save_json(path, data):
    Path(path).write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def draft_from_row(row):
    """Normaliza una fila de Supabase (resena_submissions) a la misma forma
    {nombre, ocupacion, texto} que antes producía parse_draft() sobre el .md."""
    nombre = str(row.get("nombre") or "Lector anónimo").strip()[:80]
    ocupacion = str(row.get("ocupacion") or "").strip()[:80]
    texto = str(row.get("texto", "")).strip()[:600]
    return {"nombre": nombre, "ocupacion": ocupacion, "texto": texto}


def process_drafts(api_key, qc_log=None):
    """Procesa todo lo pendiente en resena_submissions (Supabase). Regresa
    (publicadas, rechazadas, pendientes). Si se recibe qc_log (lista), los
    veredictos se anexan ahí (agent.py la persiste); si no, se cargan/
    guardan aquí. fetch_pending() ya filtra por status='pending', así que
    no hace falta llevar un set de "ya publicadas"."""
    own_log = qc_log is None
    if own_log:
        qc_log = load_json(QC_LOG_FILE, {"verdicts": []}).get("verdicts", [])

    data = load_json(TESTIMONIOS_JSON, {"testimonios": []})
    published = data.get("testimonios", [])
    pub_count = rej_count = pend_count = 0

    rows = supabase_client.fetch_pending(SUPABASE_TABLE)
    if rows:
        log(f"Reseñas de lectores: {len(rows)} envío(s) pendiente(s)")

    for row in rows:
        draft = draft_from_row(row)
        if not draft["texto"]:
            log(f"  ⚠ Reseña vacía, se omite: {row.get('id')}")
            pend_count += 1
            continue

        log(f"  → Moderando reseña de: {draft['nombre'][:60]}")
        qc = quality_check(draft, api_key, kind="resena")
        if qc.get("error"):
            log(f"  ⚠ QC de reseña no disponible (queda pendiente): {qc['error'][:80]}")
            pend_count += 1
            continue  # fail-closed: reintento en el siguiente ciclo

        qc_log.append({
            "at": datetime.now(tz=timezone.utc).isoformat(),
            "title": f"Reseña de {draft['nombre']}"[:100],
            "kind": "resena",
            "approved": qc["approved"],
            "overall": qc["overall"],
            "scores": qc["scores"],
            "observacion": qc.get("observacion_global", ""),
            "error": None,
        })

        veredicto = {
            "overall": qc["overall"],
            "scores": qc["scores"],
            "razones": qc["razones"],
            "observacion": qc.get("observacion_global", ""),
        }

        # Marca el estado en Supabase ANTES de tocar testimonios.json y solo
        # publica si tuvo éxito (mismo criterio que juridica.py, revisión de
        # seguridad 10 jul 2026): evita reseñas duplicadas si el PATCH falla
        # después de publicar. Fallo → queda pendiente para reintento limpio.
        nuevo_estado = "published" if qc["approved"] else "rejected"
        if not supabase_client.update_status(SUPABASE_TABLE, row["id"], nuevo_estado, veredicto):
            log(f"  ⚠ No se pudo marcar la reseña en Supabase ({nuevo_estado}) — "
                f"queda pendiente, se reintenta el próximo ciclo: {draft['nombre']}")
            pend_count += 1
            continue

        if qc["approved"]:
            published.insert(0, {
                "id": row["id"],
                "nombre": draft["nombre"],
                "ocupacion": draft["ocupacion"],
                "texto": draft["texto"],
                "published_at": datetime.now(tz=timezone.utc).isoformat(),
                "qc": {"overall": qc["overall"]},
            })
            pub_count += 1
            log(f"  ✓ Reseña aprobada y publicada (QC {qc['overall']}/10): {draft['nombre']}")
        else:
            rej_count += 1
            log(f"  ✗ Reseña retirada por el consejo editorial ({qc['overall']}/10): "
                f"{draft['nombre']} — {qc.get('observacion_global', '')[:80]}")

    if pub_count or rej_count:
        published = published[:MAX_TESTIMONIOS_KEPT]
        save_json(TESTIMONIOS_JSON, {
            "generated_at": datetime.now(tz=timezone.utc).isoformat(),
            "testimonios": published,
        })
    if own_log:
        save_json(QC_LOG_FILE, {"verdicts": qc_log[-200:]})

    return pub_count, rej_count, pend_count


def main():
    api_key = llm_client.get_api_key()
    if not api_key:
        sys.exit(
            f"Define la variable de entorno {llm_client.api_key_env_name()} antes de "
            f"ejecutar (proveedor activo: {llm_client.PROVIDER}, ver agent/llm_client.py)."
        )
    if not supabase_client.is_configured():
        log("  ⚠ SUPABASE_URL/SUPABASE_SERVICE_ROLE_KEY no definidas — no hay de dónde "
            "leer envíos pendientes, este ciclo no hace nada (no es un error fatal).")
    pub, rej, pend = process_drafts(api_key)
    log(f"Reseñas: {pub} publicadas, {rej} retiradas, {pend} pendientes")


if __name__ == "__main__":
    main()
