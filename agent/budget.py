#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CONTEXTO — Presupuesto diario de la API
=========================================
Tope duro de gasto diario en la API de Anthropic, dividido en DOS bolsas
independientes — no una sola compartida — para que el volumen de una cola
nunca le quite presupuesto a la otra:

  "news"       → agent.py: análisis de noticias + pieza literaria + su QC
                 en quality.py (workflow agente.yml, cada hora). Es la cola
                 de mayor volumen desde el día uno, por eso tiene la
                 porción más grande del presupuesto.
  "moderation" → juridica.py + resenas.py + su QC en quality.py (workflow
                 moderacion.yml, cada 3 horas). Volumen bajo al inicio.

Cada llamada exitosa reporta su costo real (usa los `usage.input_tokens`/
`output_tokens` que regresa la API, no una estimación) contra la bolsa que
le corresponde en `agent/spend_log.json`; ambos contadores se reinician
solos al cambiar el día (UTC).

Cuando el presupuesto de una bolsa se agota, `can_spend(pool)` regresa
False para ESA bolsa únicamente — la otra sigue funcionando normal. Cada
punto de llamada (ver agent.py, quality.py, juridica.py) se detiene ANTES
de gastar, nunca a mitad de una respuesta. Las notas/artículos/reseñas que
no alcanzaron a procesarse NO se marcan como "vistas", así que se retoman
solas (mismo día si el presupuesto se liberara, o al día siguiente).

⚠ IMPORTANTE — mantener MODEL_PRICING actualizado:
  Sonnet 5 tiene precio de lanzamiento ($2/$10 por millón de tokens
  entrada/salida) solo hasta el 31 de agosto de 2026; después sube a
  $3/$15. Si no actualizas esta tabla ese día, el presupuesto calculado
  aquí subestimará el gasto real ~50%. Verifica siempre contra
  https://platform.claude.com/docs/en/about-claude/pricing
"""

import json
from datetime import datetime, timezone
from pathlib import Path

SPEND_LOG_FILE = Path(__file__).resolve().parent / "spend_log.json"

# Tope de gasto diario por bolsa, en dólares. Perilla de configuración —
# ajusta la proporción según cuánto volumen real veas en cada cola. El total
# por defecto es $5/día, repartido 80/20 a favor de noticias porque es la
# cola con más volumen desde el arranque.
DAILY_BUDGET_USD = {
    "news": 4.00,        # agente.yml: noticias + literatura
    "moderation": 1.00,  # moderacion.yml: revista jurídica + reseñas
}

# Techo absoluto: la SUMA de las dos bolsas de arriba nunca debe superar
# esto, sin importar cómo se repartan entre sí. Es un límite duro sobre el
# presupuesto general, no solo una referencia — si algún día subes una
# bolsa y la suma pasa de aquí, el módulo falla al importarse (mejor un
# error claro al arrancar el agente que gastar de más en silencio).
MAX_TOTAL_DAILY_BUDGET_USD = 7.00

assert sum(DAILY_BUDGET_USD.values()) <= MAX_TOTAL_DAILY_BUDGET_USD, (
    f"DAILY_BUDGET_USD suma ${sum(DAILY_BUDGET_USD.values()):.2f}/día, por "
    f"encima del techo MAX_TOTAL_DAILY_BUDGET_USD (${MAX_TOTAL_DAILY_BUDGET_USD:.2f}). "
    f"Baja alguna bolsa o sube el techo a propósito."
)

# $ por millón de tokens (entrada, salida). Ver advertencia arriba.
MODEL_PRICING = {
    "claude-sonnet-5": {"input": 2.00, "output": 10.00},
    "claude-fable-5": {"input": 10.00, "output": 50.00},
    # Inception Labs (Mercury) — activo cuando LLM_PROVIDER=inception (ver
    # agent/llm_client.py). Precio de platform.inceptionlabs.ai, cuenta
    # nueva trae 10M tokens gratis. Verificar contra docs.inceptionlabs.ai
    # si cambia.
    "mercury-2": {"input": 0.25, "output": 0.75},
}

_EMPTY_POOLS = {"news": 0.0, "moderation": 0.0}
ALERT_STATE_FILE = Path(__file__).resolve().parent / "alert_state.json"


def _today():
    return datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")


def _load():
    try:
        data = json.loads(SPEND_LOG_FILE.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        data = {}
    if data.get("date") != _today() or "spent" not in data:
        data = {"date": _today(), "spent": dict(_EMPTY_POOLS), "calls": {"news": 0, "moderation": 0}}
    return data


def _save(data):
    SPEND_LOG_FILE.write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def spent_today(pool="news"):
    """Cuánto se ha gastado hoy (UTC) en esa bolsa, en dólares."""
    return _load().get("spent", {}).get(pool, 0.0)


def can_spend(pool="news"):
    """False si esa bolsa ya alcanzó o superó su tope de hoy."""
    return spent_today(pool) < DAILY_BUDGET_USD.get(pool, 0.0)


def record_usage(model, usage, pool="news"):
    """Registra el costo real de una llamada exitosa, en la bolsa `pool`,
    a partir del campo `usage` que regresa la API de Anthropic
    ({"input_tokens": N, "output_tokens": M, ...}). Persiste de inmediato."""
    pricing = MODEL_PRICING.get(model)
    if not pricing or not usage:
        return spent_today(pool)
    input_tokens = usage.get("input_tokens", 0) or 0
    output_tokens = usage.get("output_tokens", 0) or 0
    cost = (
        input_tokens / 1_000_000 * pricing["input"]
        + output_tokens / 1_000_000 * pricing["output"]
    )
    data = _load()
    data["spent"][pool] = round(data["spent"].get(pool, 0.0) + cost, 6)
    data["calls"][pool] = data["calls"].get(pool, 0) + 1
    _save(data)
    return data["spent"][pool]


def _load_alert_state():
    try:
        data = json.loads(ALERT_STATE_FILE.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        data = {}
    if data.get("date") != _today() or "warned" not in data:
        data = {"date": _today(), "warned": {}}
    return data


def budget_warning_needed(pool, threshold=0.8):
    """True la PRIMERA vez en el día (UTC) que la bolsa `pool` cruza
    `threshold` (80% por defecto) de su tope diario. Marca el aviso como ya
    enviado en agent/alert_state.json para no repetirlo en cada ciclo — se
    reinicia solo al cambiar el día, igual que spend_log.json. No hace
    ninguna llamada a la API: solo compara números ya calculados por
    record_usage()."""
    data = _load_alert_state()
    cap = DAILY_BUDGET_USD.get(pool, 0.0)
    spent = spent_today(pool)
    if not data["warned"].get(pool) and cap > 0 and spent >= threshold * cap:
        data["warned"][pool] = True
        ALERT_STATE_FILE.write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return True
    return False
