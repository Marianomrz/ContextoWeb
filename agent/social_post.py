#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CONTEXTO — Auto-post a redes sociales (agregado 16 jul 2026)
================================================================
Publica automáticamente cada nota nueva en X (Twitter) e Instagram. Mismo
estilo que el resto del proyecto: REST directo con `requests`, sin SDK
(`tweepy`, `python-instagram`, etc.) — coherente con
agent/supabase_client.py y agent/llm_client.py.

X (Twitter) usa OAuth 1.0a de una sola pierna (firma HMAC-SHA1 por
solicitud, sin flujo de autorización interactivo) porque POST /2/tweets
solo acepta user-context auth — no hay forma de publicar con un token de
solo-app. Se implementa a mano (RFC 5849) en vez de traer una librería
nueva: son ~30 líneas de firma, no justifica una dependencia nueva para
un solo endpoint.

Instagram usa la Graph API de Meta: requiere una cuenta de Instagram
Business/Creator vinculada a una Página de Facebook, y SOLO acepta
publicar con una imagen (no hay "solo texto" en Instagram) — se usa el
arte OG por categoría que build_pages.py ya genera
(assets/og/og-<categoria>.png), servido desde SITE_BASE_URL. El flujo son
dos llamadas: crear el contenedor de medio, luego publicarlo.

Ninguna de las dos funciones lanza excepción por un fallo de red/API —
regresan (ok: bool, detalle: str) para que el llamador decida qué
registrar, mismo criterio permisivo que el resto del proyecto con
servicios externos opcionales (Telegram, Supabase).
"""
import base64
import hashlib
import hmac
import json
import time
import urllib.parse
import uuid

import requests

X_API_URL = "https://api.twitter.com/2/tweets"
X_TIMEOUT = 20

IG_GRAPH_BASE = "https://graph.facebook.com/v21.0"
IG_TIMEOUT = 30


# ---------------------------------------------------------------------------
# X (Twitter) — OAuth 1.0a firmado a mano
# ---------------------------------------------------------------------------

def _oauth_quote(value):
    """Percent-encoding RFC 3986: solo A-Z a-z 0-9 - . _ ~ sin escapar —
    distinto del default de Python (que además deja "/" sin escapar)."""
    return urllib.parse.quote(str(value), safe="~")


def _oauth1_header(method, url, api_key, api_secret, access_token, access_token_secret):
    """Arma el header Authorization: OAuth para una request sin parámetros
    de query/body en la firma (nuestro único uso, POST JSON a /2/tweets no
    lleva query string). Ver RFC 5849 sección 3.4."""
    oauth_params = {
        "oauth_consumer_key": api_key,
        "oauth_nonce": uuid.uuid4().hex,
        "oauth_signature_method": "HMAC-SHA1",
        "oauth_timestamp": str(int(time.time())),
        "oauth_token": access_token,
        "oauth_version": "1.0",
    }
    param_string = "&".join(
        f"{_oauth_quote(k)}={_oauth_quote(v)}" for k, v in sorted(oauth_params.items())
    )
    base_string = "&".join([
        method.upper(), _oauth_quote(url), _oauth_quote(param_string),
    ])
    signing_key = f"{_oauth_quote(api_secret)}&{_oauth_quote(access_token_secret)}"
    signature = base64.b64encode(
        hmac.new(signing_key.encode(), base_string.encode(), hashlib.sha1).digest()
    ).decode()
    oauth_params["oauth_signature"] = signature
    header = "OAuth " + ", ".join(
        f'{_oauth_quote(k)}="{_oauth_quote(v)}"' for k, v in sorted(oauth_params.items())
    )
    return header


def post_to_x(text, api_key, api_secret, access_token, access_token_secret):
    """Publica `text` (ya recortado a 280 caracteres por el llamador) como
    un tweet nuevo. Regresa (ok, detalle)."""
    try:
        auth_header = _oauth1_header(
            "POST", X_API_URL, api_key, api_secret, access_token, access_token_secret
        )
        resp = requests.post(
            X_API_URL,
            headers={"Authorization": auth_header, "Content-Type": "application/json"},
            data=json.dumps({"text": text}),
            timeout=X_TIMEOUT,
        )
        if resp.status_code in (200, 201):
            return True, resp.json().get("data", {}).get("id", "")
        return False, f"HTTP {resp.status_code}: {resp.text[:200]}"
    except requests.RequestException as exc:
        return False, f"error de red: {exc}"


# ---------------------------------------------------------------------------
# Instagram (Graph API) — contenedor de medio + publicar
# ---------------------------------------------------------------------------

def post_to_instagram(image_url, caption, ig_user_id, access_token):
    """Publica una imagen con pie de foto en la cuenta de Instagram Business/
    Creator vinculada a `ig_user_id`. Dos llamadas: crear el contenedor
    (asíncrono del lado de Meta, por eso el pequeño reintento con espera) y
    publicarlo. Regresa (ok, detalle)."""
    try:
        create = requests.post(
            f"{IG_GRAPH_BASE}/{ig_user_id}/media",
            data={"image_url": image_url, "caption": caption, "access_token": access_token},
            timeout=IG_TIMEOUT,
        )
        if create.status_code != 200:
            return False, f"crear contenedor falló — HTTP {create.status_code}: {create.text[:200]}"
        creation_id = create.json().get("id")
        if not creation_id:
            return False, f"crear contenedor no devolvió id: {create.text[:200]}"

        # Meta procesa la imagen de forma asíncrona antes de poder publicar
        # el contenedor — un solo reintento corto cubre el caso normal sin
        # alargar demasiado el ciclo del workflow (timeout de 15 min).
        for intento in range(3):
            publish = requests.post(
                f"{IG_GRAPH_BASE}/{ig_user_id}/media_publish",
                data={"creation_id": creation_id, "access_token": access_token},
                timeout=IG_TIMEOUT,
            )
            if publish.status_code == 200:
                return True, publish.json().get("id", "")
            if intento < 2:
                time.sleep(5)
        return False, f"publicar falló — HTTP {publish.status_code}: {publish.text[:200]}"
    except requests.RequestException as exc:
        return False, f"error de red: {exc}"
