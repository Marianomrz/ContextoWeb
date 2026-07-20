#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CONTEXTO — Generador de páginas estáticas por artículo
=======================================================
Lee articles.json y produce:
  - articulo/<id>.html   una página por nota, con Open Graph, Twitter Card
                         y JSON-LD (NewsArticle/Article) para SEO y para que
                         cada nota se comparta bien en redes.
  - sitemap.xml          índice para buscadores (requiere SITE_BASE_URL).

También poda las páginas de notas que ya salieron del portal.

No llama a ninguna API: es puro render. Se puede correr solo:
  SITE_BASE_URL="https://usuario.github.io/repo" python agent/build_pages.py
y agent.py lo invoca automáticamente al final de cada ciclo.
"""

import csv
import html
import io
import json
import os
import sys
from datetime import datetime, timezone
from email.utils import format_datetime  # stdlib — para fechas RFC 822 del RSS
from pathlib import Path
from zoneinfo import ZoneInfo  # stdlib desde Python 3.9 — sin dependencia nueva

# Fecha visible al lector (la de cada nota, en la ficha de la página) en
# hora de Ciudad de México, no UTC (14 jul 2026) — mismo criterio que
# agent.py/frontend. El sitemap.xml (build_sitemap, más abajo) se queda en
# UTC a propósito: es metadata para buscadores, no algo que lea una
# persona, no aplica la misma confusión de "qué día es".
MX_TZ = ZoneInfo("America/Mexico_City")

BASE_DIR = Path(__file__).resolve().parent.parent   # raíz del portal
ARTICLES_JSON = BASE_DIR / "articles.json"
# índice permanente de la hemeroteca (agent.py lo alimenta, nunca se
# recorta) — se usa aquí solo para NO podar la página de una nota que ya
# salió de articles.json (las MAX_ARTICLES_KEPT vivas) pero sigue en el
# archivo. Agregado 14 jul 2026 junto con el resto del fix de hemeroteca.
HEMEROTECA_JSON = BASE_DIR / "hemeroteca.json"
OUT_DIR = BASE_DIR / "articulo"
BLOG_JSON = BASE_DIR / "blog.json"
BLOG_OUT_DIR = BASE_DIR / "revista"
SITEMAP_FILE = BASE_DIR / "sitemap.xml"
RSS_FILE = BASE_DIR / "feed.xml"
RSS_MAX_ITEMS = 30   # mismo orden de magnitud que MAX_ARTICLES_KEPT — no tiene caso listar más de lo que ya vive en portada
HISTORICO_CSV_FILE = BASE_DIR / "historico.csv"

# URL pública del sitio (sin diagonal final). En GitHub Actions se calcula
# sola; en local puedes exportarla o dejarla vacía (se omiten las etiquetas
# que requieren URL absoluta).
SITE_BASE_URL = os.environ.get("SITE_BASE_URL", "").rstrip("/")

CATEGORY_LABELS = {
    "politica": "Política",
    "economia": "Economía",
    "tecnologia": "Tecnología",
    "sociedad": "Sociedad",
    "internacional": "Internacional",
    "deportes": "Deportes",
    "literatura": "Literatura",
}

STATIC_PAGES = [
    "index.html", "fuentes.html", "brujula.html", "glosario.html",
    "correcciones.html", "legal.html", "revista.html", "hemeroteca.html",
    "metodologia.html", "cuenta.html",
]

FONTS_URL = ("https://fonts.googleapis.com/css2?family=Fraunces:ital,opsz,wght@0,9..144,600;"
             "0,9..144,700;0,9..144,900;1,9..144,600&family=Source+Serif+4:ital,opsz,wght@0,8..60,400;"
             "0,8..60,500;0,8..60,600;0,8..60,700;1,8..60,400;1,8..60,600&family=Inter:wght@400;500;600"
             "&family=JetBrains+Mono:wght@400;500&display=swap")


def esc(value):
    return html.escape(str(value if value is not None else ""), quote=True)


def spectrum_percent(score):
    try:
        s = max(-100, min(100, int(score)))
    except (TypeError, ValueError):
        s = 0
    return (s + 100) / 2


def spectrum_verdict(score):
    try:
        s = int(score)
    except (TypeError, ValueError):
        s = 0
    if s <= -60:
        return "Marcadamente a la izquierda", "v-left"
    if s <= -25:
        return "Inclinada a la izquierda", "v-left"
    if s < 25:
        return "Cerca del centro", "v-center"
    if s < 60:
        return "Inclinada a la derecha", "v-right"
    return "Marcadamente a la derecha", "v-right"


def og_image_path(article):
    cat = article.get("category", "")
    candidate = BASE_DIR / "assets" / "og" / f"og-{cat}.png"
    if candidate.exists():
        return f"assets/og/og-{cat}.png"
    return "assets/og/og-default.png"


def json_ld(article, page_url, image_url):
    is_free = bool(article.get("editorial_pick"))
    data = {
        "@context": "https://schema.org",
        "@type": "Article" if is_free else "NewsArticle",
        "headline": article.get("title", "")[:110],
        "description": article.get("summary", ""),
        "datePublished": article.get("published_at", ""),
        "inLanguage": "es",
        "articleSection": CATEGORY_LABELS.get(article.get("category", ""), "General"),
        "author": {"@type": "Organization", "name": "Contexto"},
        "publisher": {"@type": "Organization", "name": "Contexto"},
    }
    if image_url:
        data["image"] = [image_url]
    if page_url:
        data["mainEntityOfPage"] = page_url
    if article.get("source_url"):
        data["isBasedOn"] = article["source_url"]
    payload = json.dumps(data, ensure_ascii=False)
    # el resultado se inserta dentro de <script type="application/ld+json">…
    # </script>: json.dumps NO escapa la secuencia "</script>", así que un
    # title/summary de un feed malicioso que la contenga podría cerrar el
    # <script> e inyectar HTML. Escapar < > & a su forma \uXXXX mantiene el
    # JSON válido y cierra ese hueco (revisión de seguridad 10 jul 2026).
    return payload.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")


def render_spectrum(article):
    if article.get("editorial_pick"):
        return """
      <div class="spectrum-block free-piece-block">
        <div class="spectrum-label-row">
          <span class="spectrum-label">Pieza de mano libre</span>
          <span class="free-piece-badge">Selección del día · redacción del agente</span>
        </div>
        <p class="spectrum-why">Esta pieza no analiza la cobertura de un medio: es una recomendación o ensayo breve escrito directamente por nuestro agente editorial. Aquí no hay espectro que medir — hay un punto de vista, y lo asumimos como propio.</p>
      </div>"""
    pct = spectrum_percent(article.get("bias_score"))
    verdict_text, verdict_cls = spectrum_verdict(article.get("bias_score"))
    reason = article.get("bias_reason", "")
    reason_html = f'<p class="spectrum-why">{esc(reason)}</p>' if reason else ""
    return f"""
      <div class="spectrum-block">
        <div class="spectrum-label-row">
          <span class="spectrum-label">Espectro editorial de esta cobertura</span>
          <span class="spectrum-verdict {verdict_cls}">{esc(verdict_text)}</span>
        </div>
        <div class="spectrum-track-wrap">
          <div class="spectrum-track" role="img" aria-label="Posición de la cobertura en el espectro: {esc(verdict_text)}">
            <div class="spectrum-marker" style="left:{pct}%"></div>
          </div>
          <div class="spectrum-ticks" aria-hidden="true">
            <span>Izquierda</span><span>Centro</span><span>Derecha</span>
          </div>
        </div>
        {reason_html}
      </div>"""


def share_button(page_url, title):
    """Botón de compartir: navigator.share nativo o copiar enlace (ver
    share.js). data-share-url puede quedar vacío si SITE_BASE_URL no está
    definida — el script cae a location.href en ese caso."""
    return f'''<button type="button" class="article-foot-btn" data-share
      data-share-url="{esc(page_url)}" data-share-title="{esc(title)}">
      <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M10 13a5 5 0 007.07 0l1.93-1.93a5 5 0 00-7.07-7.07L10.5 5.43"/><path d="M14 11a5 5 0 00-7.07 0L5 12.93a5 5 0 007.07 7.07l1.43-1.43"/></svg>
      <span class="share-label">Compartir</span>
    </button>'''


def fav_button(article_id):
    """Botón de favorito (Fase 2): la plantilla solo pinta el botón con
    data-fav; el estado y el clic los maneja favoritos.js (sesión de
    Supabase). Solo para notas de articles.json/hemeroteca — las páginas de
    la revista jurídica usan otro espacio de ids y no llevan favoritos."""
    return f'''<button type="button" class="fav-btn" data-fav="{esc(article_id)}" aria-pressed="false">
      <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true"><path d="M6 3h12a1 1 0 0 1 1 1v17l-7-4-7 4V4a1 1 0 0 1 1-1z"/></svg>
      <span class="fav-label">Guardar</span>
    </button>'''


def render_article_page(article):
    is_free = bool(article.get("editorial_pick"))
    cat = article.get("category", "")
    cat_label = CATEGORY_LABELS.get(cat, "General")
    title = article.get("title", "Sin título")
    summary = article.get("summary", "")
    page_url = f"{SITE_BASE_URL}/articulo/{article['id']}.html" if SITE_BASE_URL else ""
    image_rel = og_image_path(article)
    image_url = f"{SITE_BASE_URL}/{image_rel}" if SITE_BASE_URL else ""

    chips = "".join(
        f'<span class="focus-chip">{esc(t)}</span>'
        for t in (article.get("focus_tags") or [])
    )
    context_items = "".join(
        f'<li><strong>{esc(c.get("label"))}:</strong> {esc(c.get("text"))}</li>'
        for c in (article.get("context") or [])
        if isinstance(c, dict)
    )
    source_link = ""
    if article.get("source_url"):
        source_link = (
            f'<a class="article-foot-btn" href="{esc(article["source_url"])}" '
            f'target="_blank" rel="noopener noreferrer">'
            f'Leer nota original en {esc(article.get("source_name", "la fuente"))} ↗</a>'
        )
    published = article.get("published_at", "")
    try:
        _pub_dt = datetime.fromisoformat(str(published).replace("Z", "+00:00"))
        if _pub_dt.tzinfo is None:
            _pub_dt = _pub_dt.replace(tzinfo=timezone.utc)
        pretty_date = _pub_dt.astimezone(MX_TZ).strftime("%d·%m·%Y")
    except ValueError:
        pretty_date = ""

    canonical = f'<link rel="canonical" href="{esc(page_url)}">' if page_url else ""
    og_url = f'<meta property="og:url" content="{esc(page_url)}">' if page_url else ""
    og_image = ""
    if image_url:
        og_image = (
            f'<meta property="og:image" content="{esc(image_url)}">\n'
            f'<meta name="twitter:image" content="{esc(image_url)}">'
        )
    confidence = (
        "Redacción propia del agente" if is_free
        else f"Análisis editorial · confianza {esc(article.get('confidence', 'media'))}"
    )

    return f"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<script>(function(){{try{{var t=localStorage.getItem('contexto-theme');if(t==='light'||t==='dark')document.documentElement.dataset.theme=t;}}catch(e){{}}}})();</script>
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{esc(title)} — Contexto</title>
<meta name="description" content="{esc(summary)}">
{canonical}
<meta property="og:type" content="article">
<meta property="og:site_name" content="Contexto">
<meta property="og:title" content="{esc(title)}">
<meta property="og:description" content="{esc(summary)}">
<meta property="og:locale" content="es_MX">
{og_url}
{og_image}
<meta property="article:published_time" content="{esc(published)}">
<meta property="article:section" content="{esc(cat_label)}">
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:title" content="{esc(title)}">
<meta name="twitter:description" content="{esc(summary)}">
<link rel="icon" href="../assets/favicon.svg" type="image/svg+xml">
<link rel="apple-touch-icon" href="../assets/apple-touch-icon.png">
<link rel="manifest" href="../manifest.json">
{f'<link rel="alternate" type="application/rss+xml" title="Contexto" href="{SITE_BASE_URL}/feed.xml">' if SITE_BASE_URL else ""}
<meta name="theme-color" content="#F4F4F3" media="(prefers-color-scheme: light)">
<meta name="theme-color" content="#050506" media="(prefers-color-scheme: dark)">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Fraunces:ital,opsz,wght@0,9..144,600;0,9..144,700;0,9..144,900;1,9..144,600&family=Source+Serif+4:ital,opsz,wght@0,8..60,400;0,8..60,500;0,8..60,600;0,8..60,700;1,8..60,400;1,8..60,600&family=Inter:wght@400;500;600&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
<link rel="stylesheet" href="../styles.css">
<script type="application/ld+json">{json_ld(article, page_url, image_url)}</script>
</head>
<body>

<header class="mini-masthead">
  <a class="mini-masthead-brand" href="../index.html">Contexto</a>
  <span class="mini-masthead-note">cada noticia, con su ángulo a la vista</span>
</header>

<main class="page-article">
  <article class="article-card is-featured is-page" data-category="{esc(cat)}">
    <div class="article-art" aria-hidden="true"></div>
    <div class="article-head">
      <div class="article-meta-row">
        <span class="category-tag">{esc(cat_label)}</span>
        <time datetime="{esc(published)}">{esc(pretty_date)}</time>
        <span class="source-name">· vía {esc(article.get("source_name", "fuente externa"))}</span>
      </div>
      <h1 class="article-title">{esc(title)}</h1>
      <p class="article-dek">{esc(summary)}</p>
    </div>
    <button class="facts-only-toggle" type="button" aria-pressed="false" id="factsOnlyToggle" title="Ocultar espectro y análisis, mostrar solo el resumen">
      <svg viewBox="0 0 24 24" width="13" height="13" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7-10-7-10-7z"/><circle cx="12" cy="12" r="3"/></svg>
      <span class="facts-only-label">Solo hechos</span>
    </button>
    {render_spectrum(article)}
    <div class="article-analysis">
      <div class="analysis-col">
        <h2 class="analysis-col-title">{"Por qué lo elegimos hoy" if is_free else "Con qué foco se cuenta"}</h2>
        <p>{esc(article.get("focus_analysis", ""))}</p>
        {f'<div class="focus-chip-row">{chips}</div>' if chips else ""}
      </div>
      <div class="analysis-col">
        <h2 class="analysis-col-title">{"Para llegar más lejos" if is_free else "Contexto y trasfondo"}</h2>
        <ul class="context-list">{context_items}</ul>
      </div>
    </div>
    <div class="article-foot">
      {source_link}
      {share_button(page_url, title)}
      {fav_button(article["id"])}
      <span class="confidence-note"><span class="agent-avatar" aria-hidden="true"></span>{confidence}</span>
    </div>
  </article>
  <p class="back-home"><a href="../index.html">← Volver a la portada</a></p>
</main>

<footer class="site-footer">
  <div class="footer-inner">
    <p class="footer-brand">Contexto</p>
    <p class="footer-note">Un ejercicio de transparencia editorial.</p>
    <nav class="footer-nav" aria-label="Páginas del sitio">
      <a href="../index.html">Portada</a>
      <a href="../revista.html">Revista jurídica</a>
      <a href="../hemeroteca.html">Hemeroteca</a>
      {f'<a href="../feed.xml">RSS</a>' if SITE_BASE_URL else ""}
      <a href="../fuentes.html">Panel de fuentes</a>
      <a href="../brujula.html">Brújula editorial</a>
      <a href="../glosario.html">Glosario</a>
      <a href="../metodologia.html">Metodología en números</a>
      <a href="../cuenta.html">Mi cuenta</a>
      <a href="../correcciones.html">Correcciones</a>
      <a href="../legal.html">Legal y privacidad</a>
    </nav>
  </div>
</footer>

<script src="../share.js"></script>
<script type="module" src="../favoritos.js"></script>
<script>(function(){{
  var btn = document.getElementById('factsOnlyToggle');
  if (!btn) return;
  btn.addEventListener('click', function(){{
    var card = btn.closest('.article-card');
    var on = card.classList.toggle('is-facts-only');
    btn.setAttribute('aria-pressed', String(on));
    btn.querySelector('.facts-only-label').textContent = on ? 'Ver análisis completo' : 'Solo hechos';
  }});
}})();</script>
</body>
</html>
"""


def render_blog_page(entry):
    """Página estática de un artículo de la Revista Jurídica."""
    title = entry.get("title", "Sin título")
    summary = entry.get("summary", "")
    author = entry.get("author", "Redacción")
    page_url = f"{SITE_BASE_URL}/revista/{entry['id']}.html" if SITE_BASE_URL else ""
    canonical = f'<link rel="canonical" href="{esc(page_url)}">' if page_url else ""
    og_url = f'<meta property="og:url" content="{esc(page_url)}">' if page_url else ""
    og_image = ""
    if SITE_BASE_URL:
        og_image = (f'<meta property="og:image" content="{SITE_BASE_URL}/assets/og/og-default.png">\n'
                    f'<meta name="twitter:image" content="{SITE_BASE_URL}/assets/og/og-default.png">')
    published = entry.get("published_at", "")
    try:
        _pub_dt = datetime.fromisoformat(str(published).replace("Z", "+00:00"))
        if _pub_dt.tzinfo is None:
            _pub_dt = _pub_dt.replace(tzinfo=timezone.utc)
        pretty_date = _pub_dt.astimezone(MX_TZ).strftime("%d·%m·%Y")
    except ValueError:
        pretty_date = ""
    areas = "".join(f'<span class="focus-chip">{esc(a)}</span>' for a in entry.get("areas", []))
    ld = json.dumps({
        "@context": "https://schema.org",
        "@type": "ScholarlyArticle",
        "headline": title[:110],
        "description": summary,
        "datePublished": published,
        "inLanguage": "es",
        "author": {"@type": "Person", "name": author},
        "publisher": {"@type": "Organization", "name": "Contexto · Revista Jurídica"},
        **({"mainEntityOfPage": page_url} if page_url else {}),
    }, ensure_ascii=False)

    return f"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<script>(function(){{try{{var t=localStorage.getItem('contexto-theme');if(t==='light'||t==='dark')document.documentElement.dataset.theme=t;}}catch(e){{}}}})();</script>
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{esc(title)} — Revista Jurídica · Contexto</title>
<meta name="description" content="{esc(summary)}">
{canonical}
<meta property="og:type" content="article">
<meta property="og:site_name" content="Contexto · Revista Jurídica">
<meta property="og:title" content="{esc(title)}">
<meta property="og:description" content="{esc(summary)}">
<meta property="og:locale" content="es_MX">
{og_url}
{og_image}
<meta name="twitter:card" content="summary_large_image">
<link rel="icon" href="../assets/favicon.svg" type="image/svg+xml">
<link rel="apple-touch-icon" href="../assets/apple-touch-icon.png">
<link rel="manifest" href="../manifest.json">
<meta name="theme-color" content="#F4F4F3" media="(prefers-color-scheme: light)">
<meta name="theme-color" content="#050506" media="(prefers-color-scheme: dark)">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="{FONTS_URL}" rel="stylesheet">
<link rel="stylesheet" href="../styles.css">
<script type="application/ld+json">{ld}</script>
</head>
<body>

<header class="mini-masthead">
  <a class="mini-masthead-brand" href="../revista.html">Contexto</a>
  <span class="mini-masthead-note">revista jurídica · distribución gratuita</span>
</header>

<main class="page-content jur-article">
  <span class="section-eyebrow">Revista Jurídica</span>
  <h1>{esc(title)}</h1>
  <p class="jur-byline">Por <strong>{esc(author)}</strong>
    · <time datetime="{esc(published)}">{esc(pretty_date)}</time>
    · {int(entry.get("minutos_lectura", 1))} min de lectura</p>
  <div class="focus-chip-row">{areas}</div>
  <p class="page-lede">{esc(summary)}</p>
  <hr class="jur-rule">
  <div class="jur-body">
{entry.get("body_html", "")}
  </div>
  <p class="jur-note">Artículo revisado y aprobado por el consejo editorial
  automático de Contexto (calidad {esc(str(entry.get("qc", {}).get("overall", "—")))}/10).
  Su contenido es responsabilidad del autor y no constituye asesoría legal.</p>
  <div class="article-foot">
    {share_button(page_url, title)}
    <span class="confidence-note">Revista Jurídica · distribución gratuita</span>
  </div>
  <p class="back-home"><a href="../revista.html">← Volver a la revista</a></p>
</main>

<footer class="site-footer">
  <div class="footer-inner">
    <p class="footer-brand">Contexto</p>
    <p class="footer-note">Un ejercicio de transparencia editorial.</p>
    <nav class="footer-nav" aria-label="Páginas del sitio">
      <a href="../index.html">Portada</a>
      <a href="../revista.html">Revista jurídica</a>
      <a href="../hemeroteca.html">Hemeroteca</a>
      {f'<a href="../feed.xml">RSS</a>' if SITE_BASE_URL else ""}
      <a href="../fuentes.html">Panel de fuentes</a>
      <a href="../metodologia.html">Metodología en números</a>
      <a href="../cuenta.html">Mi cuenta</a>
      <a href="../correcciones.html">Correcciones</a>
      <a href="../legal.html">Legal y privacidad</a>
    </nav>
  </div>
</footer>

<script src="../share.js"></script>

</body>
</html>
"""


def build_sitemap(articles, blog_articles=()):
    if not SITE_BASE_URL:
        print("build_pages: SITE_BASE_URL no definida — se omite sitemap.xml")
        return
    now = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")
    urls = []
    for page in STATIC_PAGES:
        loc = SITE_BASE_URL + ("/" if page == "index.html" else f"/{page}")
        urls.append(f"  <url><loc>{esc(loc)}</loc><lastmod>{now}</lastmod></url>")
    for a in articles:
        lastmod = str(a.get("published_at", ""))[:10] or now
        urls.append(
            f"  <url><loc>{esc(SITE_BASE_URL)}/articulo/{esc(a['id'])}.html</loc>"
            f"<lastmod>{lastmod}</lastmod></url>"
        )
    for b in blog_articles:
        lastmod = str(b.get("published_at", ""))[:10] or now
        urls.append(
            f"  <url><loc>{esc(SITE_BASE_URL)}/revista/{esc(b['id'])}.html</loc>"
            f"<lastmod>{lastmod}</lastmod></url>"
        )
    SITEMAP_FILE.write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        + "\n".join(urls) + "\n</urlset>\n",
        encoding="utf-8",
    )
    # robots.txt necesita la URL absoluta del sitemap
    (BASE_DIR / "robots.txt").write_text(
        "# Contexto — portal de noticias con análisis de sesgo\n"
        "User-agent: *\nAllow: /\n\n"
        f"Sitemap: {SITE_BASE_URL}/sitemap.xml\n",
        encoding="utf-8",
    )


def build_rss(articles):
    """feed.xml — RSS 2.0 con las últimas RSS_MAX_ITEMS notas (no incluye
    revista jurídica ni reseñas, solo el pipeline principal de noticias/
    literatura). Igual que el sitemap, requiere SITE_BASE_URL para URLs
    absolutas — sin ella un lector RSS no puede resolver los enlaces.
    Agregada 16 jul 2026 a pedido del usuario (descubrimiento de contenido)."""
    if not SITE_BASE_URL:
        print("build_pages: SITE_BASE_URL no definida — se omite feed.xml")
        return
    # más recientes primero, igual que la portada
    ordered = sorted(articles, key=lambda a: str(a.get("published_at", "")), reverse=True)
    items = []
    for a in ordered[:RSS_MAX_ITEMS]:
        page_url = f"{SITE_BASE_URL}/articulo/{a['id']}.html"
        try:
            pub_dt = datetime.fromisoformat(str(a.get("published_at", "")).replace("Z", "+00:00"))
            if pub_dt.tzinfo is None:
                pub_dt = pub_dt.replace(tzinfo=timezone.utc)
            pub_rfc822 = format_datetime(pub_dt)
        except ValueError:
            continue
        cat_label = CATEGORY_LABELS.get(a.get("category", ""), "General")
        # description va en CDATA — el resumen es texto plano generado por el
        # agente (nunca cita textual de la fuente, ver regla de derechos de
        # autor), pero igual se envuelve en CDATA por si trae comillas/signos.
        items.append(
            "  <item>\n"
            f"    <title>{esc(a.get('title', 'Sin título'))}</title>\n"
            f"    <link>{esc(page_url)}</link>\n"
            f"    <guid isPermaLink=\"true\">{esc(page_url)}</guid>\n"
            f"    <pubDate>{pub_rfc822}</pubDate>\n"
            f"    <category>{esc(cat_label)}</category>\n"
            f"    <description><![CDATA[{a.get('summary', '')}]]></description>\n"
            "  </item>"
        )
    RSS_FILE.write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom">\n'
        "<channel>\n"
        "  <title>Contexto</title>\n"
        f"  <link>{esc(SITE_BASE_URL)}/</link>\n"
        "  <description>Noticias con análisis de sesgo editorial: espectro, enfoque y contexto de cada cobertura.</description>\n"
        "  <language>es-mx</language>\n"
        f'  <atom:link href="{esc(SITE_BASE_URL)}/feed.xml" rel="self" type="application/rss+xml" />\n'
        + "\n".join(items) + "\n"
        "</channel>\n</rss>\n",
        encoding="utf-8",
    )


def build_historico_csv(archive):
    """historico.csv — versión descargable del índice PERMANENTE de la
    hemeroteca (hemeroteca.json), pensada para quien quiera auditar el
    espectro editorial del propio portal con sus propios datos en vez de
    solo confiar en la palabra del sitio (pedido del usuario, 16 jul 2026).
    bias_score/source_name los guarda agent.py desde ese mismo día — entradas
    archivadas antes quedan con esas dos columnas vacías, no se rellenan
    retroactivamente (ver comentario en agent.py, run_cycle())."""
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["id", "title", "category", "source_name", "published_at", "bias_score"])
    for a in archive:
        writer.writerow([
            a.get("id", ""),
            a.get("title", ""),
            a.get("category", ""),
            a.get("source_name", ""),
            a.get("published_at", ""),
            a.get("bias_score") if a.get("bias_score") is not None else "",
        ])
    HISTORICO_CSV_FILE.write_text(buf.getvalue(), encoding="utf-8")


def build_all():
    """Genera todas las páginas de artículo, poda las viejas y el sitemap."""
    try:
        data = json.loads(ARTICLES_JSON.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError) as exc:
        print(f"build_pages: no pude leer articles.json ({exc})")
        return 0

    articles = [a for a in data.get("articles", []) if a.get("id")]
    OUT_DIR.mkdir(exist_ok=True)

    current = set()
    for a in articles:
        filename = f"{a['id']}.html"
        current.add(filename)
        (OUT_DIR / filename).write_text(render_article_page(a), encoding="utf-8")

    # protege del podado las páginas de notas que ya salieron de las
    # MAX_ARTICLES_KEPT vivas pero siguen en el índice permanente de la
    # hemeroteca — sin esto, el permalink de cualquier nota "archivada" se
    # borraba en el primer ciclo tras salir de la portada, aunque
    # hemeroteca.js siguiera enlazándolo. No hace falta regenerarlas (ya
    # se escribieron cuando la nota SÍ estaba en articles.json), solo no
    # tocarlas.
    archived_articles = []
    try:
        archived = json.loads(HEMEROTECA_JSON.read_text(encoding="utf-8"))
        archived_articles = archived.get("articles", [])
        for a in archived_articles:
            if a.get("id"):
                current.add(f"{a['id']}.html")
    except (FileNotFoundError, json.JSONDecodeError):
        pass

    # poda: páginas de notas que ya no viven en el portal NI en la hemeroteca
    removed = 0
    for old in OUT_DIR.glob("*.html"):
        if old.name not in current:
            old.unlink()
            removed += 1

    # revista jurídica: una página por artículo publicado en blog.json
    blog_data = {}
    try:
        blog_data = json.loads(BLOG_JSON.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        pass
    blog_articles = [b for b in blog_data.get("articles", []) if b.get("id")]
    BLOG_OUT_DIR.mkdir(exist_ok=True)
    blog_current = set()
    for b in blog_articles:
        filename = f"{b['id']}.html"
        blog_current.add(filename)
        (BLOG_OUT_DIR / filename).write_text(render_blog_page(b), encoding="utf-8")
    for old in BLOG_OUT_DIR.glob("*.html"):
        if old.name not in blog_current:
            old.unlink()
            removed += 1

    build_sitemap(articles, blog_articles)
    build_rss(articles)
    build_historico_csv(archived_articles)
    print(f"build_pages: {len(current)} páginas de notas + {len(blog_current)} "
          f"de revista generadas, {removed} podadas")
    return len(current)


if __name__ == "__main__":
    sys.exit(0 if build_all() >= 0 else 1)
