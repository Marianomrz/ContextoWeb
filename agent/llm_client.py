#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CONTEXTO — Cliente de LLM (interruptor Anthropic ⇄ Inception Labs/Mercury)
============================================================================
Agregado el 10 jul 2026: mientras se prueba el pipeline, Mariano quiere usar
Mercury (Inception Labs, tokens gratis para probar) en vez de Claude, para
no gastar crédito de Anthropic durante las pruebas — y poder volver a
Anthropic más adelante sin tocar agent.py/quality.py/juridica.py.

Interruptor: variable de entorno LLM_PROVIDER = "anthropic" (default, si no
está definida) o "inception". agent.py, quality.py y juridica.py NO
cambian: siguen pidiendo su modelo de Anthropic de siempre (p. ej.
ANALYSIS_MODEL = "claude-sonnet-5") — call_llm() ignora ese nombre y usa
Mercury cuando el proveedor activo es "inception".

⚠ Esto es un cambio TEMPORAL a propósito, no un reemplazo permanente. La
razón documentada en README.md ("Costo") de por qué agent.py usa Sonnet 5
para el volumen alto y Fable 5 solo para la pieza literaria (calidad donde
se nota, barato donde no) sigue siendo la arquitectura objetivo — Mercury
es un solo modelo genérico, más barato pero sin ese ajuste fino por tarea.
Para volver a Anthropic: quitar la variable LLM_PROVIDER (o ponerla en
"anthropic") donde corra el agente — agent/.env en local, o los secretos/
variables de los workflows de GitHub Actions.

Claves de API según proveedor (nunca las mezcles):
  - anthropic  → variable de entorno ANTHROPIC_API_KEY (console.anthropic.com)
  - inception  → variable de entorno INCEPTION_API_KEY (platform.inceptionlabs.ai
    → API Keys; cuenta nueva trae 10M tokens gratis, sin tarjeta)
"""

import os

import requests

PROVIDER = os.environ.get("LLM_PROVIDER", "anthropic").strip().lower()

INCEPTION_MODEL = "mercury-2"  # único modelo de chat que ofrece Inception hoy
ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"
INCEPTION_API_URL = "https://api.inceptionlabs.ai/v1/chat/completions"


def get_api_key():
    """Lee la variable de entorno correcta según el proveedor activo."""
    if PROVIDER == "inception":
        return os.environ.get("INCEPTION_API_KEY")
    return os.environ.get("ANTHROPIC_API_KEY")


def api_key_env_name():
    return "INCEPTION_API_KEY" if PROVIDER == "inception" else "ANTHROPIC_API_KEY"


def call_llm(system, user_content, api_key, model, max_tokens, effort="medium"):
    """Llama al proveedor activo (LLM_PROVIDER) y regresa SIEMPRE la misma
    forma: (text, usage, model_used).

    - `usage` normalizado a {"input_tokens": N, "output_tokens": M} sin
      importar el proveedor, para pasarlo tal cual a budget.record_usage().
    - `model_used` es el nombre real que respondió — pásalo tal cual a
      budget.record_usage() (budget.MODEL_PRICING ya tiene entrada para
      "mercury-2" además de los modelos de Anthropic).
    - `model` es el modelo de Anthropic que pediría el llamador (p. ej.
      "claude-sonnet-5"): se usa tal cual si el proveedor es Anthropic, y
      se IGNORA (se usa Mercury) si el proveedor es Inception — así los
      archivos que llaman a esta función no necesitan saber qué proveedor
      está activo. Sin excepciones por tarea a propósito (revisado 14 jul
      2026): mientras LLM_PROVIDER=inception esté activo, TODA llamada,
      incluida la pieza literaria, corre contra Mercury — el objetivo es
      $0 de gasto real mientras se prueba el pipeline. Si la calidad de
      alguna tarea no alcanza el mínimo del control de calidad, el ajuste
      es el umbral o el prompt de esa tarea, no una excepción de proveedor.
    """
    if PROVIDER == "inception":
        return _call_inception(system, user_content, api_key, max_tokens)
    return _call_anthropic(system, user_content, api_key, model, max_tokens, effort)


def _call_anthropic(system, user_content, api_key, model, max_tokens, effort):
    payload = {
        "model": model,
        "max_tokens": max_tokens,
        "output_config": {"effort": effort},
        "system": system,
        "messages": [{"role": "user", "content": user_content}],
    }
    headers = {
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }
    resp = requests.post(ANTHROPIC_API_URL, headers=headers, json=payload, timeout=90)
    resp.raise_for_status()
    data = resp.json()
    text = "".join(
        b.get("text", "") for b in data.get("content", []) if b.get("type") == "text"
    )
    usage = data.get("usage", {}) or {}
    normalized = {
        "input_tokens": usage.get("input_tokens", 0),
        "output_tokens": usage.get("output_tokens", 0),
    }
    return text, normalized, model


def _call_inception(system, user_content, api_key, max_tokens):
    payload = {
        "model": INCEPTION_MODEL,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user_content},
        ],
        "max_tokens": max_tokens,
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    resp = requests.post(INCEPTION_API_URL, headers=headers, json=payload, timeout=90)
    resp.raise_for_status()
    data = resp.json()
    choice = (data.get("choices") or [{}])[0]
    text = choice.get("message", {}).get("content", "") or ""
    usage = data.get("usage", {}) or {}
    normalized = {
        "input_tokens": usage.get("prompt_tokens", 0),
        "output_tokens": usage.get("completion_tokens", 0),
    }
    return text, normalized, INCEPTION_MODEL
