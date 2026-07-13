#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CONTEXTO — Revista Jurídica (blog de distribución gratuita)
============================================================
Pipeline editorial para artículos escritos por humanos:

  1. El autor manda su artículo por el formulario de revista.html (guarda
     una fila en la tabla `jur_submissions` de Supabase, status='pending';
     ver agent/supabase_client.py). Hasta el 10 jul 2026 esto era un correo
     que Mariano copiaba a mano a blog/borradores/*.md — ese flujo manual
     quedó retirado (ver AUDITORIA-PRELANZAMIENTO.md, sección 2.4); los
     archivos .md viejos en blog/borradores/, blog/publicados/ y
     blog/rechazados/ son solo respaldo histórico, ya no se leen.
  2. El agente lo analiza (resumen tipo abstract + áreas del derecho).
  3. El consejo editorial (quality.py, rúbrica jurídica con moderación)
     decide: aprobado → se publica en blog.json y obtiene página propia;
     inapropiado → la fila en Supabase pasa a status='rejected' con su
     veredicto en la columna `veredicto`.

Filosofía de fallos: FAIL-CLOSED. Si la API (de Anthropic o de Supabase)
falla, el envío queda con status='pending' y se reintenta en el siguiente
ciclo — un filtro de moderación jamás publica nada sin revisión (al
contrario que las noticias, donde un fallo técnico publica con advertencia).

Ejecución independiente:
  export ANTHROPIC_API_KEY="..."
  export SUPABASE_URL="..." SUPABASE_SERVICE_ROLE_KEY="..."
  python agent/juridica.py
(agent.py también lo invoca en cada ciclo.)
"""

import json
import re
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from quality import quality_check
import budget       # tope de gasto diario compartido
import llm_client   # interruptor Anthropic ⇄ Inception Labs/Mercury
import supabase_client

BASE_DIR = Path(__file__).resolve().parent.parent
BLOG_JSON = BASE_DIR / "blog.json"
QC_LOG_FILE = Path(__file__).resolve().parent / "qc_log.json"
SUPABASE_TABLE = "jur_submissions"

ANALYSIS_MODEL = "claude-sonnet-5"
# Nota: si LLM_PROVIDER=inception (ver agent/llm_client.py), este nombre se
# IGNORA y el análisis usa Mercury — cambio temporal mientras se prueba el
# pipeline.

JUR_ANALYSIS_PROMPT = """Eres el secretario de redacción de la Revista Jurídica
del portal "Contexto". Recibes un artículo jurídico y produces su ficha
editorial en JSON:

- "summary": abstract de 2-3 frases con tus propias palabras (qué problema
  aborda el artículo y qué aporta).
- "areas": 2-4 etiquetas cortas de área jurídica (p. ej. "Derecho constitucional",
  "Amparo", "Derechos humanos", "Derecho laboral").
- "minutos_lectura": entero, estimado a ~200 palabras por minuto.

Responde SOLO con el objeto JSON, sin markdown."""


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
    """Normaliza una fila de Supabase (jur_submissions) a la misma forma
    {titulo, autor, body_md} que antes producía parse_draft() sobre el .md
    — así analyze_draft/md_to_html/strip_md no necesitaron cambiar."""
    return {
        "titulo": str(row.get("titulo", ""))[:160],
        "autor": str(row.get("autor") or "Redacción")[:80],
        "body_md": str(row.get("body_md", "")),
    }


_INLINE_RULES = [
    (re.compile(r"\*\*(.+?)\*\*"), r"<strong>\1</strong>"),
    (re.compile(r"(?<!\*)\*([^*]+)\*(?!\*)"), r"<em>\1</em>"),
    (re.compile(r"\[([^\]]+)\]\((https?://[^)\s]+)\)"),
     r'<a href="\2" rel="noopener noreferrer" target="_blank">\1</a>'),
]


def _esc(text):
    # Escapa también comillas (agregado 10 jul 2026, revisión de seguridad):
    # sin esto, un body_md malicioso con un enlace tipo
    # `[x](https://evil.com" onmouseover="alert(1))` podría, en teoría,
    # cerrar el atributo href="" del <a> generado por _INLINE_RULES y
    # agregar un atributo/evento propio. La regex del enlace ya excluye
    # espacios en la URL (\s), pero escapar comillas cierra el hueco de raíz
    # en vez de depender solo de esa exclusión.
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&#39;")
    )


def _inline(text):
    out = _esc(text)
    for rx, repl in _INLINE_RULES:
        out = rx.sub(repl, out)
    return out


def md_to_html(md):
    """Conversor Markdown mínimo y sin dependencias: encabezados, párrafos,
    listas, citas, negritas/cursivas y enlaces. Todo lo demás es texto plano
    escapado (seguridad primero: el borrador es entrada externa)."""
    blocks = re.split(r"\n\s*\n", md.strip())
    html_parts = []
    for block in blocks:
        lines = [l.rstrip() for l in block.splitlines()]
        first = lines[0] if lines else ""
        if first.startswith("### "):
            html_parts.append(f"<h4>{_inline(first[4:])}</h4>")
            rest = "\n".join(lines[1:]).strip()
            if rest:
                html_parts.append(f"<p>{_inline(rest)}</p>")
        elif first.startswith("## "):
            html_parts.append(f"<h3>{_inline(first[3:])}</h3>")
            rest = "\n".join(lines[1:]).strip()
            if rest:
                html_parts.append(f"<p>{_inline(rest)}</p>")
        elif first.startswith("# "):
            html_parts.append(f"<h2>{_inline(first[2:])}</h2>")
            rest = "\n".join(lines[1:]).strip()
            if rest:
                html_parts.append(f"<p>{_inline(rest)}</p>")
        elif all(l.lstrip().startswith(("- ", "* ")) for l in lines if l.strip()):
            items = "".join(
                f"<li>{_inline(l.lstrip()[2:])}</li>" for l in lines if l.strip()
            )
            html_parts.append(f"<ul>{items}</ul>")
        elif all(l.lstrip().startswith(">") for l in lines if l.strip()):
            quote = " ".join(l.lstrip().lstrip(">").strip() for l in lines if l.strip())
            html_parts.append(f"<blockquote>{_inline(quote)}</blockquote>")
        else:
            html_parts.append(f"<p>{_inline(' '.join(l for l in lines if l.strip()))}</p>")
    return "\n".join(html_parts)


def strip_md(md):
    """Texto plano aproximado (para el QC y el conteo de palabras)."""
    text = re.sub(r"^---.*?---", "", md, flags=re.DOTALL)
    text = re.sub(r"[#>*\-\[\]()]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


# ---------------------------------------------------------------------------
# ANÁLISIS EDITORIAL (Sonnet 5)
# ---------------------------------------------------------------------------

def analyze_draft(draft, api_key):
    if not budget.can_spend("moderation"):
        log(f"  💰 Presupuesto diario de moderación agotado — «{draft['titulo'][:50]}…» queda pendiente")
        return None  # fail-closed: se reintenta en un ciclo posterior
    user = (f"Título: {draft['titulo']}\nAutor: {draft['autor']}\n\n"
            f"Texto:\n{strip_md(draft['body_md'])[:8000]}")
    try:
        text, usage, model_used = llm_client.call_llm(
            system=JUR_ANALYSIS_PROMPT,
            user_content=user,
            api_key=api_key,
            model=ANALYSIS_MODEL,
            max_tokens=3000,
            effort="medium",
        )
        budget.record_usage(model_used, usage, "moderation")
        data = json.loads(re.sub(r"```(?:json)?|```", "", text).strip())
    except Exception as exc:
        log(f"  ⚠ Análisis jurídico falló (queda pendiente): {exc}")
        return None
    data["areas"] = [str(a)[:40] for a in list(data.get("areas", []))[:4]]
    try:
        data["minutos_lectura"] = max(1, int(data.get("minutos_lectura", 1)))
    except (TypeError, ValueError):
        data["minutos_lectura"] = max(1, len(strip_md(draft["body_md"]).split()) // 200)
    return data


# ---------------------------------------------------------------------------
# PIPELINE: procesar envíos pendientes (Supabase, jur_submissions)
# ---------------------------------------------------------------------------

def process_drafts(api_key, qc_log=None):
    """Procesa todo lo pendiente en jur_submissions (Supabase). Regresa
    (publicados, rechazados, pendientes). Si se recibe qc_log (lista), los
    veredictos se anexan ahí (agent.py la persiste); si no, se cargan/
    guardan aquí. fetch_pending() ya filtra por status='pending', así que
    no hace falta llevar un set de "ya publicados" — lo que ya se procesó
    no vuelve a aparecer."""
    own_log = qc_log is None
    if own_log:
        qc_log = load_json(QC_LOG_FILE, {"verdicts": []}).get("verdicts", [])

    blog = load_json(BLOG_JSON, {"articles": []})
    published = blog.get("articles", [])
    pub_count = rej_count = pend_count = 0

    rows = supabase_client.fetch_pending(SUPABASE_TABLE)
    if rows:
        log(f"Revista jurídica: {len(rows)} envío(s) pendiente(s)")

    for row in rows:
        draft = draft_from_row(row)
        if not draft["body_md"].strip():
            log(f"  ⚠ Envío vacío, se omite: {row.get('id')}")
            pend_count += 1
            continue

        log(f"  → Analizando artículo: {draft['titulo'][:60]}")
        analysis = analyze_draft(draft, api_key)
        if analysis is None:
            pend_count += 1
            continue  # fail-closed: reintento en el siguiente ciclo

        candidate = {
            "title": draft["titulo"],
            "author": draft["autor"],
            "summary": str(analysis.get("summary", "")),
            "areas": analysis["areas"],
            "body_text": strip_md(draft["body_md"]),
        }
        qc = quality_check(candidate, api_key, kind="juridica")
        if qc.get("error"):
            log(f"  ⚠ QC jurídico no disponible (queda pendiente): {qc['error'][:80]}")
            pend_count += 1
            continue  # fail-closed

        qc_log.append({
            "at": datetime.now(tz=timezone.utc).isoformat(),
            "title": draft["titulo"][:100],
            "kind": "juridica",
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

        # Marca el estado en Supabase ANTES de tocar blog.json y solo
        # publica si ese marcado tuvo éxito (revisión de seguridad 10 jul
        # 2026): si el PATCH falla (blip de red) después de publicar, la fila
        # quedaría 'pending' y el siguiente ciclo la re-analizaría (gasta
        # tokens) y la re-publicaría → entrada duplicada con el mismo id. Al
        # marcar primero y comprobar el retorno, un fallo simplemente deja el
        # envío pendiente para un reintento limpio, sin duplicar.
        nuevo_estado = "published" if qc["approved"] else "rejected"
        if not supabase_client.update_status(SUPABASE_TABLE, row["id"], nuevo_estado, veredicto):
            log(f"  ⚠ No se pudo marcar el envío en Supabase ({nuevo_estado}) — "
                f"queda pendiente, se reintenta el próximo ciclo: {draft['titulo'][:50]}")
            pend_count += 1
            continue

        if qc["approved"]:
            published.insert(0, {
                "id": row["id"],
                "title": draft["titulo"],
                "author": draft["autor"],
                "summary": candidate["summary"],
                "areas": candidate["areas"],
                "minutos_lectura": analysis["minutos_lectura"],
                "published_at": datetime.now(tz=timezone.utc).isoformat(),
                "body_html": md_to_html(draft["body_md"]),
                "qc": {"overall": qc["overall"]},
            })
            pub_count += 1
            log(f"  ✓ Aprobado y publicado (QC {qc['overall']}/10): {draft['titulo'][:60]}")
        else:
            rej_count += 1
            log(f"  ✗ Retirado por el consejo editorial ({qc['overall']}/10): "
                f"{draft['titulo'][:60]} — {qc.get('observacion_global', '')[:80]}")

    if pub_count or rej_count:
        save_json(BLOG_JSON, {
            "generated_at": datetime.now(tz=timezone.utc).isoformat(),
            "articles": published,
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
    log(f"Revista: {pub} publicados, {rej} retirados, {pend} pendientes")
    import build_pages
    build_pages.build_all()


if __name__ == "__main__":
    main()
