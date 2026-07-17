#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CONTEXTO — Salud del sistema: diagnóstico semanal (agregado 16 jul 2026)
============================================================================
Agente de SOLO LECTURA — nunca modifica código, nunca hace push, nunca
toca ningún archivo público del portal. Junta las bitácoras que los otros
agentes YA producen (agent/qc_log.json, agent/spend_log.json,
agent/category_streak.json) más el historial reciente de corridas de
GitHub Actions, calcula métricas reales, y le pide a un LLM (una sola
llamada por corrida, bolsa "moderation" — mismo criterio que jurídica/
reseñas: bajo volumen, no urgente, así que el modelo más caro/capaz sale
barato) que escriba un diagnóstico breve en español con recomendaciones
priorizadas. Publica el resultado como un Issue NUEVO de GitHub cada
corrida — esto es para Mariano, no para los lectores del portal.

Origen (conversación del 16 jul 2026): Mariano preguntó por un agente que
"fuera aprendiendo y mejorándose" solo. La respuesta fue que un agente que
reescribe código de producción SIN supervisión es demasiado riesgo para un
proyecto sin tests/CI real (ver README: "No hay build, framework, tests ni
linter") — así que esta primera versión SOLO diagnostica y sugiere, nunca
actúa. Si en el futuro se agrega una segunda fase que proponga cambios de
código, esa fase debe abrir un Pull Request para que un humano lo revise y
apruebe — nunca un push directo a main, ni siquiera desde este agente.

Ejecución independiente:
  export ANTHROPIC_API_KEY="..." GH_TOKEN="..."
  python agent/salud.py
  (GITHUB_REPOSITORY lo pone GitHub Actions solo; en local, expórtala a
  mano como "usuario/repo" si quieres probar la parte de GH Actions.)
"""
import json
import os
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

import budget
import llm_client

AGENT_DIR = Path(__file__).resolve().parent

QC_LOG_FILE = AGENT_DIR / "qc_log.json"
SPEND_LOG_FILE = AGENT_DIR / "spend_log.json"
STREAK_FILE = AGENT_DIR / "category_streak.json"
DIGEST_OUT_FILE = AGENT_DIR / "salud_ultimo.md"

# Ventana de análisis para el historial de GitHub Actions. Con el Cron Job
# de Render disparando agente.yml cada 20 min (agregado 16 jul 2026), 7
# días ya son cientos de corridas — per_page=100 puede no alcanzar a
# traerlas todas; se avisa en el digest cuando eso pasa (ver `truncated`
# en analyze_workflows), nunca se presenta como dato completo si no lo es.
WINDOW_DAYS = 7
WORKFLOWS = [
    "agente.yml", "moderacion.yml", "social.yml", "resumen-diario.yml", "salud.yml",
]

# Umbral propio, distinto del MIN_CRITERION=5.0 real de quality.py: aquí
# queremos avisar ANTES de que un criterio esté rozando el mínimo de
# rechazo, no solo cuando ya lo cruzó.
LOW_CRITERION_THRESHOLD = 5.5
# Igual de intención que ZERO_STREAK_ALERT_THRESHOLD=24 en streaks.py, pero
# a la mitad: este digest quiere señalar una racha que va para arriba antes
# de que dispare la alerta de Telegram, no repetir esa misma alerta.
STREAK_WARN_THRESHOLD = 12
WORKFLOW_SUCCESS_WARN_PCT = 80

KIND_LABELS = {
    "noticia": "Noticias", "literatura": "Literatura",
    "juridica": "Revista jurídica", "resena": "Reseñas de lectores",
}
CATEGORY_LABELS = {
    "politica": "Política", "economia": "Economía", "tecnologia": "Tecnología",
    "sociedad": "Sociedad", "internacional": "Internacional", "deportes": "Deportes",
}

DIAGNOSIS_SYSTEM_PROMPT = """\
Eres un ingeniero de confiabilidad revisando la operación semanal de Contexto, un portal de \
noticias con análisis de sesgo editorial que corre solo, sin backend tradicional, mantenido por \
una sola persona que no programa directamente (depende de un asistente de IA para los cambios de \
código, y ese asistente nunca hace push sin que la persona revise y corra el comando).

Te doy métricas reales ya calculadas — nunca datos crudos completos. Con eso, escribe en español \
(es-MX) un diagnóstico breve y honesto:

- Si todo está bien, dilo claramente y no inventes problemas para tener algo que reportar.
- Si algo se ve mal, nombra la causa más probable SOLO si los datos la sustentan. Si no alcanza \
información para saber por qué, dilo así en vez de adivinar.
- Cierra con 3 a 5 recomendaciones concretas y accionables, ordenadas por prioridad. Cada una debe \
decir QUÉ cambiar y POR QUÉ, con base en los números que te di — nunca una recomendación genérica \
que aplicaría a cualquier proyecto.
- Nunca sugieras nada que le dé más autonomía al sistema de la que ya tiene hoy (por ejemplo: no \
recomiendes quitar los topes de presupuesto, ni los pasos de control de calidad, ni el que los \
cambios de código pasen por revisión humana antes de llegar a producción).

Máximo 350 palabras. Sin encabezados markdown (##) — quien llama a esta función ya pone los \
encabezados alrededor de tu texto. Prosa normal, párrafos cortos, sin viñetas."""


def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


def load_json(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return default


# ---------------------------------------------------------------------------
# Control de calidad (agent/qc_log.json — misma bitácora que lee
# metodologia.js en el frontend, pero aquí se calcula en Python)
# ---------------------------------------------------------------------------

def analyze_qc():
    verdicts = load_json(QC_LOG_FILE, {}).get("verdicts", [])
    if not verdicts:
        return None

    by_kind = defaultdict(lambda: {"aprobados": 0, "rechazados": 0, "scores": defaultdict(list)})
    for v in verdicts:
        k = v.get("kind", "?")
        entry = by_kind[k]
        entry["aprobados" if v.get("approved") else "rechazados"] += 1
        for crit, val in (v.get("scores") or {}).items():
            if isinstance(val, (int, float)):
                entry["scores"][crit].append(val)

    total = len(verdicts)
    aprobados = sum(1 for v in verdicts if v.get("approved"))
    lines = [f"De las últimas {total} evaluaciones registradas, {aprobados} se aprobaron ({round(aprobados / total * 100)}%)."]
    for k, entry in by_kind.items():
        sub = entry["aprobados"] + entry["rechazados"]
        if not sub:
            continue
        pct = round(entry["aprobados"] / sub * 100)
        label = KIND_LABELS.get(k, k)
        low_crits = []
        for crit, vals in entry["scores"].items():
            avg = sum(vals) / len(vals)
            if avg < LOW_CRITERION_THRESHOLD:
                low_crits.append(f"{crit.replace('_', ' ')} ({avg:.1f}/10)")
        extra = f" — criterios bajos: {', '.join(low_crits)}" if low_crits else ""
        lines.append(f"  {label}: {entry['aprobados']}/{sub} aprobadas ({pct}%){extra}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Presupuesto (agent/spend_log.json — solo el día en curso, el archivo NO
# guarda historial de días anteriores, así que no hay forma honesta de
# mostrar una tendencia semanal con lo que existe hoy)
# ---------------------------------------------------------------------------

def analyze_budget():
    data = load_json(SPEND_LOG_FILE, {})
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if not data or data.get("date") != today:
        return "Sin datos de gasto para hoy todavía (spend_log.json no guarda historial de días anteriores, solo el día en curso — no es posible mostrar una tendencia semanal con lo que existe hoy)."
    lines = []
    for pool, cap in budget.DAILY_BUDGET_USD.items():
        spent = data.get("spent", {}).get(pool, 0.0)
        calls = data.get("calls", {}).get(pool, 0)
        pct = round(spent / cap * 100) if cap else 0
        lines.append(f"  Bolsa \"{pool}\": ${spent:.2f} de ${cap:.2f} gastados hoy ({pct}%), {calls} llamadas.")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Rachas de categorías (agent/category_streak.json)
# ---------------------------------------------------------------------------

def analyze_streaks():
    data = load_json(STREAK_FILE, {})
    streaks = data.get("streaks", {})
    if not streaks:
        return None
    lines = []
    for cat, n in sorted(streaks.items(), key=lambda kv: -kv[1]):
        if not n:
            continue
        label = CATEGORY_LABELS.get(cat, cat)
        flag = "  ⚠" if n >= STREAK_WARN_THRESHOLD else ""
        unidad = "ciclo" if n == 1 else "ciclos"
        lines.append(f"  {label}: {n} {unidad} seguidos sin publicar{flag}")
    return "\n".join(lines) if lines else None


# ---------------------------------------------------------------------------
# Confiabilidad de los workflows (API de GitHub Actions — sin SDK, mismo
# estilo que el resto del proyecto)
# ---------------------------------------------------------------------------

def analyze_workflows(gh_token, repo):
    if not gh_token or not repo:
        return None, ""

    since = (datetime.now(timezone.utc) - timedelta(days=WINDOW_DAYS)).strftime("%Y-%m-%dT%H:%M:%SZ")
    headers = {"Authorization": f"Bearer {gh_token}", "Accept": "application/vnd.github+json"}
    tally = {}
    truncated = False

    for wf in WORKFLOWS:
        url = f"https://api.github.com/repos/{repo}/actions/workflows/{wf}/runs"
        params = {"created": f">={since}", "per_page": 100}
        try:
            resp = requests.get(url, headers=headers, params=params, timeout=30)
            resp.raise_for_status()
            runs = resp.json().get("workflow_runs", [])
        except requests.RequestException as e:
            log(f"  ⚠ No se pudo leer el historial de {wf}: {e}")
            continue
        if len(runs) == 100:
            truncated = True
        total = fallidas = 0
        for r in runs:
            if r.get("status") != "completed":
                continue
            total += 1
            if r.get("conclusion") != "success":
                fallidas += 1
        if total:
            tally[wf] = (total, fallidas)

    if not tally:
        return None, ""

    lines = []
    for wf, (total, fallidas) in tally.items():
        exitosas = total - fallidas
        pct = round(exitosas / total * 100)
        flag = "  ⚠" if pct < WORKFLOW_SUCCESS_WARN_PCT else ""
        lines.append(f"  {wf}: {exitosas}/{total} corridas exitosas ({pct}%){flag}")
    note = " (muestra puede estar incompleta, límite de 100 corridas por workflow en esta consulta)" if truncated else ""
    return "\n".join(lines), note


def run():
    log("Recopilando métricas de las bitácoras existentes...")
    qc_summary = analyze_qc()
    budget_summary = analyze_budget()
    streaks_summary = analyze_streaks()
    workflows_summary, workflows_note = analyze_workflows(
        os.environ.get("GH_TOKEN"), os.environ.get("GITHUB_REPOSITORY"),
    )

    parts = []
    if qc_summary:
        parts.append("CONTROL DE CALIDAD (últimas 200 evaluaciones registradas):\n" + qc_summary)
    if budget_summary:
        parts.append("PRESUPUESTO DE HOY:\n" + budget_summary)
    if streaks_summary:
        parts.append("RACHAS DE CATEGORÍAS SIN PUBLICAR NADA:\n" + streaks_summary)
    if workflows_summary:
        parts.append(f"CONFIABILIDAD DE LOS WORKFLOWS (últimos {WINDOW_DAYS} días):\n" + workflows_summary)
    data_blob = "\n\n".join(parts)

    if not data_blob.strip():
        log("No hay datos suficientes todavía (¿primera corrida?) — se omite el ciclo.")
        return

    narrative = None
    api_key = llm_client.get_api_key()
    if not api_key:
        log(f"Sin {llm_client.api_key_env_name()} configurada — se omite el diagnóstico narrativo, se publican solo los números.")
    elif not budget.can_spend("moderation"):
        log('Bolsa "moderation" sin presupuesto disponible hoy — se omite el diagnóstico narrativo, se publican solo los números.')
    else:
        try:
            # Fable 5 (no Sonnet 5): mismo criterio que la pieza literaria y
            # el QC de jurídica/reseñas en quality.py — 1 llamada/semana es
            # volumen bajísimo, así que el modelo más caro/capaz sale
            # barato y el diagnóstico sale mejor razonado.
            text, usage, model_used = llm_client.call_llm(
                DIAGNOSIS_SYSTEM_PROMPT, data_blob, api_key,
                model="claude-fable-5", max_tokens=3000, effort="medium",
            )
            budget.record_usage(model_used, usage, pool="moderation")
            narrative = text.strip()
        except Exception as e:
            log(f"⚠ Falló la llamada al LLM para el diagnóstico: {e} — se publican solo los números.")

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    md = [f"# 📊 Salud del sistema — {today}\n"]
    md.append("## Diagnóstico\n")
    if narrative:
        md.append(narrative + "\n")
    else:
        md.append("_Sin análisis narrativo esta corrida (ver el log del workflow para el motivo) — abajo están los números crudos._\n")
    if qc_summary:
        md.append("## Control de calidad\n\n```\n" + qc_summary + "\n```\n")
    if budget_summary:
        md.append("## Presupuesto de hoy\n\n```\n" + budget_summary + "\n```\n")
    if streaks_summary:
        md.append("## Rachas de categorías\n\n```\n" + streaks_summary + "\n```\n")
    if workflows_summary:
        heading = f"## Confiabilidad de los workflows (últimos {WINDOW_DAYS} días){workflows_note}"
        md.append(heading + "\n\n```\n" + workflows_summary + "\n```\n")
    md.append(
        "---\n_Diagnóstico automático, de **solo lectura** — no modifica código ni "
        "hace push por sí solo. Revísalo con criterio antes de actuar._"
    )

    DIGEST_OUT_FILE.write_text("\n".join(md), encoding="utf-8")
    log(f"Digest escrito en {DIGEST_OUT_FILE}")


if __name__ == "__main__":
    run()
