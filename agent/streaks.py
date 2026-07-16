#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CONTEXTO — Rastreo de rachas por categoría (agregado 16 jul 2026)
===================================================================
Guarda, en agent/category_streak.json, cuántos ciclos SEGUIDOS lleva cada
categoría de noticias sin publicar nada. A propósito NO resetea por día
(a diferencia de agent/alert_state.json, que sí — ese archivo trackea
presupuesto diario, un concepto distinto). El objetivo es el mismo
problema real que vivió el proyecto los días previos ("sociedad"
dominando el contenido, tecnología/literatura en cero varios ciclos sin
que nadie lo notara hasta revisar el sitio a mano): avisar por Telegram
automáticamente cuando una categoría lleva demasiados ciclos en cero, en
vez de depender de que alguien lo note a simple vista.

Mismo patrón que agent/budget.py: funciones puras, sin llamadas de red — el
envío real a Telegram lo hace el paso correspondiente en
.github/workflows/agente.yml, igual que ya hace con
budget.budget_warning_needed().
"""
import json
from pathlib import Path

STREAK_FILE = Path(__file__).resolve().parent / "category_streak.json"

# Categorías de noticias reales — excluye "literatura": es una pieza al día
# por diseño propio (publish_daily_literature()), no un volumen donde tenga
# sentido medir "ciclos seguidos en cero".
NEWS_CATEGORIES = ("politica", "economia", "tecnologia", "sociedad", "internacional", "deportes")

# 24 ciclos ≈ un día completo con el cron actual (cada hora + respaldo a los
# 30 min). Bastante para no generar ruido por un hueco normal del pool de un
# ciclo, pero corto para detectar un hueco real como el que motivó esta
# función. Ajustable si en la práctica sale ruidoso o demasiado tardío.
ZERO_STREAK_ALERT_THRESHOLD = 24


def _load():
    try:
        data = json.loads(STREAK_FILE.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        data = {}
    data.setdefault("streaks", {})
    data.setdefault("alerted", {})
    for cat in NEWS_CATEGORIES:
        data["streaks"].setdefault(cat, 0)
        data["alerted"].setdefault(cat, False)
    return data


def _save(data):
    STREAK_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def update(published_categories):
    """Llamar UNA vez por ciclo desde agent.py, al final, con el set de
    categorías que sí publicaron algo nuevo este ciclo. Las que no
    publicaron suman 1 a su racha; las que sí publicaron vuelven a 0 y se
    limpia su bandera de aviso ya enviado (para que un futuro hueco nuevo
    SÍ vuelva a avisar)."""
    data = _load()
    for cat in NEWS_CATEGORIES:
        if cat in published_categories:
            data["streaks"][cat] = 0
            data["alerted"][cat] = False
        else:
            data["streaks"][cat] += 1
    _save(data)


def categories_needing_alert():
    """True la PRIMERA vez que una categoría cruza ZERO_STREAK_ALERT_THRESHOLD
    ciclos seguidos en cero — marca el aviso como ya enviado para no
    repetirlo cada ciclo (se reinicia solo cuando esa categoría vuelve a
    publicar). Devuelve [(categoria, racha), ...]."""
    data = _load()
    pending = []
    changed = False
    for cat in NEWS_CATEGORIES:
        streak = data["streaks"].get(cat, 0)
        if streak >= ZERO_STREAK_ALERT_THRESHOLD and not data["alerted"].get(cat):
            pending.append((cat, streak))
            data["alerted"][cat] = True
            changed = True
    if changed:
        _save(data)
    return pending
