#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CONTEXTO — Auto-post a redes sociales: orquestador (agregado 16 jul 2026)
============================================================================
Publica la nota más reciente de articles.json que todavía no se haya
posteado, en X y/o Instagram (cada plataforma es independiente: si solo
configuraste las claves de una, la otra simplemente se omite — mismo
patrón "si faltan credenciales, se omite sin error" que ya usa el
proyecto con Telegram/Supabase). Un solo post por plataforma por corrida
— con el cron propio de este workflow, se pone al día solo en corridas
sucesivas sin generar una ráfaga de posts si acumula varias notas.

Corre en su propio workflow (.github/workflows/social.yml), desacoplado
de agente.yml a propósito (mismo criterio que moderacion.yml/
resumen-diario.yml): así una racha de posts fallidos no bloquea ni
retrasa la publicación de noticias, que es lo prioritario.

Estado persistido en agent/social_posted.json (¿qué ids ya se postearon
en cada red?) — el workflow lo comitea, igual que seen_urls.json/
qc_log.json, para que sobreviva entre corridas (cada corrida de Actions es
un checkout nuevo, sin disco persistente).

No republica texto de la fuente original (regla de derechos de autor del
proyecto): el texto del post usa el título y el resumen que YA escribió el
agente con sus propias palabras, nunca el cuerpo de la nota original.

Ejecución independiente:
  export X_API_KEY="..." X_API_SECRET="..." X_ACCESS_TOKEN="..." X_ACCESS_TOKEN_SECRET="..."
  export IG_USER_ID="..." IG_ACCESS_TOKEN="..."
  export SITE_BASE_URL="https://tu-dominio"
  python agent/social.py
"""
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import build_pages          # reusa og_image_path() para la imagen de Instagram
import social_post

BASE_DIR = Path(__file__).resolve().parent.parent
ARTICLES_JSON = BASE_DIR / "articles.json"
SOCIAL_STATE_FILE = Path(__file__).resolve().parent / "social_posted.json"

SITE_BASE_URL = os.environ.get("SITE_BASE_URL", "").rstrip("/")

X_MAX_CHARS = 280
X_LINK_RESERVED = 24   # t.co siempre cuenta como ~23 chars + 1 espacio, sin importar el largo real


def log(msg):
    stamp = datetime.now().strftime("%H:%M:%S")
    print(f"[{stamp}] {msg}", flush=True)


def load_json(path, default):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def save_json(path, data):
    Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def pick_candidate(articles, already_posted):
    """La nota más reciente que no esté en `already_posted` (set de ids).
    Nunca elige piezas de mano libre (editorial_pick): son ensayos/
    recomendaciones sin fuente externa, de otro tono al resto del feed —
    se dejan fuera del auto-post a propósito, no todo lo que se publica en
    el portal encaja en una red social."""
    ordered = sorted(
        (a for a in articles if a.get("id") and not a.get("editorial_pick")),
        key=lambda a: str(a.get("published_at", "")), reverse=True,
    )
    for a in ordered:
        if a["id"] not in already_posted:
            return a
    return None


def compose_x_text(article, page_url):
    title = article.get("title", "")
    budget_chars = X_MAX_CHARS - X_LINK_RESERVED
    if len(title) > budget_chars:
        title = title[:budget_chars - 1].rstrip() + "…"
    return f"{title} {page_url}".strip()


def compose_instagram_caption(article, page_url):
    cat_label = build_pages.CATEGORY_LABELS.get(article.get("category", ""), "General")
    parts = [
        article.get("title", ""),
        "",
        article.get("summary", ""),
        "",
        f"Espectro editorial y fuentes completas en el enlace de la bio o en:\n{page_url}",
        "",
        f"#{cat_label.replace(' ', '')} #Contexto #NoticiasConPerspectiva",
    ]
    return "\n".join(p for p in parts if p is not None)


def run():
    if not SITE_BASE_URL:
        log("⚠ SITE_BASE_URL no definida — se omite el ciclo completo (los enlaces/imágenes necesitan URL absoluta).")
        return

    x_configured = all(os.environ.get(k) for k in (
        "X_API_KEY", "X_API_SECRET", "X_ACCESS_TOKEN", "X_ACCESS_TOKEN_SECRET"))
    ig_configured = all(os.environ.get(k) for k in ("IG_USER_ID", "IG_ACCESS_TOKEN"))

    if not x_configured and not ig_configured:
        log("Ninguna red social tiene credenciales configuradas — se omite el ciclo (ver README, sección auto-post).")
        return

    articles = load_json(ARTICLES_JSON, {"articles": []}).get("articles", [])
    state = load_json(SOCIAL_STATE_FILE, {"posted_x": [], "posted_instagram": []})
    posted_x = set(state.get("posted_x", []))
    posted_ig = set(state.get("posted_instagram", []))

    if x_configured:
        candidate = pick_candidate(articles, posted_x)
        if not candidate:
            log("X: nada nuevo que postear.")
        else:
            page_url = f"{SITE_BASE_URL}/articulo/{candidate['id']}.html"
            text = compose_x_text(candidate, page_url)
            ok, detail = social_post.post_to_x(
                text,
                os.environ["X_API_KEY"], os.environ["X_API_SECRET"],
                os.environ["X_ACCESS_TOKEN"], os.environ["X_ACCESS_TOKEN_SECRET"],
            )
            if ok:
                log(f"  ✓ X: publicado ({candidate['title'][:60]}) — tweet id {detail}")
                posted_x.add(candidate["id"])
            else:
                log(f"  ✗ X: falló ({candidate['title'][:60]}) — {detail}")
    else:
        log("X: X_API_KEY/X_API_SECRET/X_ACCESS_TOKEN/X_ACCESS_TOKEN_SECRET no configurados — se omite.")

    if ig_configured:
        candidate = pick_candidate(articles, posted_ig)
        if not candidate:
            log("Instagram: nada nuevo que postear.")
        else:
            page_url = f"{SITE_BASE_URL}/articulo/{candidate['id']}.html"
            image_url = f"{SITE_BASE_URL}/{build_pages.og_image_path(candidate)}"
            caption = compose_instagram_caption(candidate, page_url)
            ok, detail = social_post.post_to_instagram(
                image_url, caption, os.environ["IG_USER_ID"], os.environ["IG_ACCESS_TOKEN"],
            )
            if ok:
                log(f"  ✓ Instagram: publicado ({candidate['title'][:60]}) — media id {detail}")
                posted_ig.add(candidate["id"])
            else:
                log(f"  ✗ Instagram: falló ({candidate['title'][:60]}) — {detail}")
    else:
        log("Instagram: IG_USER_ID/IG_ACCESS_TOKEN no configurados — se omite.")

    save_json(SOCIAL_STATE_FILE, {
        "posted_x": sorted(posted_x)[-500:],
        "posted_instagram": sorted(posted_ig)[-500:],
    })


if __name__ == "__main__":
    run()
    sys.exit(0)
