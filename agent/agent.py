#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CONTEXTO — Agente lector y publicador de noticias
==================================================
Flujo por ciclo:
  1. Lee los feeds RSS de las fuentes configuradas.
  2. Filtra notas ya publicadas (deduplicación por URL).
  3. Para cada nota nueva, pide a Claude un análisis estructurado:
     resumen propio, score de sesgo, enfoque editorial y contexto.
  4. Publica el resultado en articles.json (el portal lo consume tal cual).

IMPORTANTE — derechos de autor:
  El agente NUNCA republica el texto original. Genera un resumen breve
  con palabras propias, el análisis editorial, y enlaza a la fuente.

Ejecución:
  export ANTHROPIC_API_KEY="tu-clave"
  python agent.py                # un ciclo
  python agent.py --loop 1800    # ciclo cada 30 minutos (modo vigilante)
"""

import argparse
import hashlib
import json
import os
import re
import sys
import time
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo  # stdlib desde Python 3.9 — sin dependencia nueva

try:
    import feedparser
except ImportError:
    sys.exit("Falta feedparser. Instala con: pip install feedparser requests")

try:
    import requests
except ImportError:
    sys.exit("Falta requests. Instala con: pip install requests")

from quality import quality_check   # agente 2: control de calidad editorial
import build_pages                  # genera páginas estáticas por artículo + sitemap
import budget                       # tope de gasto diario compartido por los 4 agentes
import llm_client                   # interruptor Anthropic ⇄ Inception Labs/Mercury
# Nota: juridica.py y resenas.py YA NO se importan aquí — corren en su
# propio workflow (moderacion.yml), desacoplados del ciclo de noticias.

# ---------------------------------------------------------------------------
# CONFIGURACIÓN
# ---------------------------------------------------------------------------

BASE_DIR = Path(__file__).resolve().parent
OUTPUT_JSON = BASE_DIR.parent / "articles.json"   # el portal lee este archivo
# índice PERMANENTE, nunca se trunca (a diferencia de articles.json, que solo
# guarda las MAX_ARTICLES_KEPT notas vivas de la portada) — lo lee
# hemeroteca.js. Agregado 14 jul 2026: antes la hemeroteca leía articles.json
# directo, así que en realidad no era un archivo — cualquier nota que
# saliera de las MAX_ARTICLES_KEPT desaparecía también de "el archivo
# completo del portal". Solo guarda los campos que hemeroteca.js necesita
# (id/title/category/published_at), no el artículo completo.
HEMEROTECA_JSON = BASE_DIR.parent / "hemeroteca.json"
STATE_FILE = BASE_DIR / "seen_urls.json"          # deduplicación entre ciclos
QC_LOG_FILE = BASE_DIR / "qc_log.json"            # bitácora del control de calidad

# Huso horario editorial del portal (agregado 14 jul 2026): GitHub Actions
# corre en UTC y por defecto todo "hoy"/"fecha" en Python se calculaba con
# datetime.now() sin zona (=UTC ahí) — entre las 18:00 y medianoche hora
# CDMX eso ya cae del lado UTC del día siguiente. Todo lo que en este
# archivo signifique "el día de hoy" para un LECTOR (no el reinicio del
# presupuesto, que sigue en UTC a propósito, ver agent/budget.py) debe
# calcularse con MX_TZ, nunca con datetime.now() a secas ni con
# datetime.now(tz=timezone.utc).
MX_TZ = ZoneInfo("America/Mexico_City")

MESES_ES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio",
            "agosto", "septiembre", "octubre", "noviembre", "diciembre"]


def mx_date_str(dt=None):
    """Fecha (YYYY-MM-DD) en hora de Ciudad de México, a partir de un
    datetime aware o (por default) de ahora mismo."""
    d = (dt or datetime.now(tz=timezone.utc)).astimezone(MX_TZ)
    return d.strftime("%Y-%m-%d")

MAX_NEW_PER_CYCLE = 6      # META MÍNIMA de notas a publicar por ciclo — no un techo.
                           # Cambiado 14 jul 2026 a pedido del usuario: antes el ciclo
                           # se detenía apenas publicaba esta cantidad, aunque el pool
                           # trajera más candidatas buenas. Eso tenía un efecto
                           # colateral real: fresh (ver fetch_new_entries) se ordena por
                           # fecha ACROSS todas las fuentes, así que las categorías de
                           # bajo volumen (tecnologia, internacional) casi nunca llegaban
                           # a analizarse — las fuentes de alto volumen (política/
                           # economía) siempre ocupaban los primeros lugares del pool
                           # dentro del techo de intentos que existía antes. Ahora
                           # run_cycle() procesa TODO el pool `fresh` cada ciclo; el
                           # único límite real es el presupuesto diario
                           # (budget.can_spend), igual que en el resto del pipeline —
                           # esta constante solo se usa para el log informativo.
MAX_ARTICLES_KEPT = 30     # tope de notas vivas en el portal — bajado de 60 el 14 jul
                           # 2026 a pedido del usuario (la portada se sentía muy larga
                           # para llegar a la hemeroteca/brújula/etc. al fondo). Nada se
                           # pierde: lo que sale de aquí sigue para siempre en
                           # hemeroteca.json, solo deja de mostrarse en la portada. Con
                           # el techo de publicación por ciclo ya quitado (ver
                           # MAX_NEW_PER_CYCLE arriba), la portada rota más rápido que
                           # antes, así que 60 se habría sentido todavía más larga.

# IDs de notas de ejemplo/relleno que quedaron en articles.json desde una
# etapa temprana de desarrollo (antes de conectar el agente real) y nunca se
# limpiaron antes de salir a producción — descubierto 14 jul 2026 al ver que
# hemeroteca.json las archivó como si fueran reales (una incluso atribuye
# contenido inventado a El Economista vía isBasedOn en su página). Como
# published nunca borra nada salvo el recorte por MAX_ARTICLES_KEPT, y el
# conteo real+relleno no lo había superado todavía, seguían vivas. Se filtran
# aquí cada ciclo (de published Y del archivo permanente) para que se
# autolimpien de articles.json y hemeroteca.json solas, y build_pages.py las
# borre de articulo/ y del sitemap en el siguiente build_all().
EXCLUDED_IDS = {"ejemplo-001", "ejemplo-002", "ejemplo-003", "ejemplo-004", "ejemplo-005"}

# Dos modelos, según volumen y exigencia de cada tarea (nombres de
# Anthropic — mientras LLM_PROVIDER=inception esté activo, AMBOS se
# IGNORAN y todo corre con Mercury, ver nota abajo. Quedan documentados
# aquí porque son el objetivo real cuando se vuelva a Anthropic):
# - ANALYSIS_MODEL: corre decenas de veces al día (una por nota) — Sonnet 5
#   da calidad casi de Opus a precio de Sonnet, ideal para el volumen alto.
# - LITERATURE_MODEL: corre una sola vez al día (la pieza de mano libre) —
#   el volumen es mínimo, así que se pagaría el modelo más capaz.
ANALYSIS_MODEL = "claude-sonnet-5"
LITERATURE_MODEL = "claude-fable-5"
# Nota: si LLM_PROVIDER=inception (ver agent/llm_client.py), estos dos
# nombres se IGNORAN y ambas llamadas usan Mercury — es a propósito: el
# objetivo mientras se prueba el pipeline es $0 de gasto real, punto. Se
# intentó una excepción el 14 jul 2026 para forzar la pieza literaria por
# Anthropic (Mercury la rechazaba siempre, 0% de aprobación) — revertida
# el mismo día a pedido explícito del usuario: mientras se use Inception,
# TODO pasa por ahí, sin excepciones, aunque eso signifique ajustar el
# umbral de calidad o el prompt de escritura en vez de cambiar de modelo
# — ver el diagnóstico real (0% de aprobación, siempre floja en
# originalidad_creatividad/riqueza_estilo) en agent/qc_log.json y en
# 00-INDICE.md, vuelta 18-19, antes de tocar cualquiera de los dos.

# Fuentes: feeds RSS públicos. Ajusta o agrega los tuyos (p. ej. el periódico
# local de tu ciudad). Si un feed cambia de URL, solo edita esta lista.
# La justificación de cada fuente está en el README (sección "Panel de fuentes").
SOURCES = [
    # --- Núcleo original ---
    # El Universal y AM (León) traían URL de feed muerta (404) al 9 jul 2026;
    # corregidas tras verificar la nueva ruta con feedparser (contenido real,
    # no solo HTTP 200). Forbes México, Latinus y NYT en Español se retiraron
    # ese mismo día: Forbes bloquea su feed sin token, Latinus ya no expone
    # RSS real (la URL responde con el home en HTML), y NYT en Español está
    # discontinuado (403 en todo el sitio /es/ desde su cierre editorial).
    {"name": "El Economista",  "feed": "https://www.eleconomista.com.mx/rss/ultimas-noticias", "default_category": "economia"},
    {"name": "El Universal",   "feed": "https://www.eluniversal.com.mx/arc/outboundfeeds/rss/", "default_category": "politica"},
    {"name": "Periódico AM (León)", "feed": "https://www.am.com.mx/feed",                      "default_category": "sociedad"},

    # --- Investigación y verificación (alta credibilidad) ---
    # Animal Político retiró su RSS (404 en todas las rutas conocidas, 9 jul
    # 2026); Etcétera cubre un ángulo similar (medios y rendición de cuentas).
    {"name": "Aristegui Noticias", "feed": "https://editorial.aristeguinoticias.com/feed/",    "default_category": "politica"},
    {"name": "Etcétera",           "feed": "https://www.etcetera.com.mx/feed/",                 "default_category": "politica"},

    # --- Diarios de referencia con línea editorial conocida ---
    # (útil para el espectro: cubren los mismos hechos desde ángulos distintos)
    {"name": "La Jornada",   "feed": "https://www.jornada.com.mx/rss/edicion.xml?v=1",         "default_category": "politica"},
    {"name": "Reforma",      "feed": "https://www.reforma.com/rss/portada.xml",                "default_category": "politica"},
    {"name": "El Informador (GDL)", "feed": "https://www.informador.mx/rss/mexico.xml",        "default_category": "sociedad"},
    {"name": "Infobae México", "feed": "https://www.infobae.com/arc/outboundfeeds/rss/category/mexico/", "default_category": "sociedad"},

    # --- Economía y negocios ---
    {"name": "Expansión", "feed": "https://expansion.mx/rss", "default_category": "economia"},

    # --- Internacional de prestigio ---
    {"name": "BBC News Mundo", "feed": "https://feeds.bbci.co.uk/mundo/rss.xml",               "default_category": "internacional"},
    {"name": "El País América", "feed": "https://feeds.elpais.com/mrss-s/pages/ep/site/elpais.com/portada", "default_category": "internacional"},
    {"name": "DW Español",     "feed": "https://rss.dw.com/xml/rss-sp-all",                    "default_category": "internacional"},
    {"name": "France24 Español", "feed": "https://www.france24.com/es/rss",                    "default_category": "internacional"},
    # Agregada 14 jul 2026: el usuario notó que casi no salían notas de
    # internacional/tecnología pese a tener fuentes — verificado que el
    # feed sí respondía (contenido real, del día), la causa real era otra
    # (ver nota de MAX_NEW_PER_CYCLE más abajo). Euronews España, verificada
    # con feedparser antes de agregarla: muy alto volumen, actualiza varias
    # veces por hora, cobertura geopolítica real (no solo notas de agencia).
    {"name": "Euronews Español", "feed": "https://es.euronews.com/rss?level=theme&name=news",  "default_category": "internacional"},

    # --- Deportes ---
    # ESPN Deportes retiró su RSS (bloqueo/redirect en bucle, 9 jul 2026).
    {"name": "La Jornada Deportes", "feed": "https://www.jornada.com.mx/rss/deportes.xml?v=1",  "default_category": "deportes"},
    {"name": "Infobae Deportes",    "feed": "https://www.infobae.com/arc/outboundfeeds/rss/category/deportes/", "default_category": "deportes"},

    # --- Cultura y literatura (alimentan la sección, además de la pieza diaria) ---
    {"name": "Letras Libres",       "feed": "https://letraslibres.com/feed/",                   "default_category": "literatura"},
    {"name": "La Jornada Cultura",  "feed": "https://www.jornada.com.mx/rss/cultura.xml?v=1",   "default_category": "literatura"},

    # --- Tecnología (10 jul 2026: categoría sin ninguna fuente hasta ahora,
    # a pesar de existir en VALID_CATEGORIES — hueco real, no intencional) ---
    {"name": "Xataka",        "feed": "https://www.xataka.com/feedburner.xml", "default_category": "tecnologia"},
    {"name": "Hipertextual",  "feed": "https://hipertextual.com/feed",          "default_category": "tecnologia"},
    # Agregadas 14 jul 2026: Xataka/Hipertextual mezclan bastante cine/streaming
    # con tecnología real (el análisis categoriza por CONTENIDO, no por fuente,
    # así que esas notas de cine legítimamente no caen en "tecnologia" — no era
    # un bug de categorización). Genbeta y WWWhatsnew son más estrictamente de
    # software/apps/internet, para darle más peso real a la categoría. Ambas
    # verificadas con feedparser antes de agregarlas (contenido real, no solo
    # HTTP 200).
    {"name": "Genbeta",       "feed": "https://www.genbeta.com/feedburner.xml", "default_category": "tecnologia"},
    {"name": "WWWhatsnew",    "feed": "https://wwwhatsnew.com/feed/",           "default_category": "tecnologia"},

    # --- Más volumen / diversidad editorial (10 jul 2026, ver README →
    # Panel de fuentes para la justificación completa) ---
    {"name": "El Sol de México", "feed": "https://www.elsoldemexico.com.mx/rss", "default_category": "sociedad"},
]

VALID_CATEGORIES = {
    "politica", "economia", "tecnologia", "sociedad",
    "internacional", "deportes", "literatura",
}

# ---------------------------------------------------------------------------
# PROMPT DE ANÁLISIS
# ---------------------------------------------------------------------------

ANALYSIS_SYSTEM_PROMPT = """Eres el analista editorial del portal "Contexto".
Recibes el titular y el extracto de una noticia y produces un análisis en JSON.
A veces también recibes "Otras coberturas del mismo hecho" de otros medios —
úsalas como se indica en las reglas 3 y 6; si no vienen, ignora esa parte.

Reglas estrictas:
1. El campo "summary" debe ser un resumen de 1-2 frases ESCRITO CON TUS PROPIAS
   PALABRAS. Prohibido copiar frases del original NI de las coberturas de otros
   medios que se te den como referencia.
   NADA DE REFERENCIAS AMBIGUAS: el lector NO ha leído la nota original, así
   que nombra siempre el sujeto completo y su contexto. Mal: "la selección
   aseguró su boleto". Bien: "la selección mexicana de futbol varonil aseguró
   su boleto al Mundial". Aplica a equipos, instituciones, leyes, empresas y
   personas: primera mención siempre con nombre propio, país/ámbito y, si
   ayuda, el cargo ("la presidenta de México, ...", "la Ley de Amparo
   mexicana", "el Tribunal Supremo de España"). Lo mismo en "focus_analysis"
   y en cada "context".
2. "bias_score" es un entero de -100 (cobertura marcadamente de izquierda) a
   +100 (marcadamente de derecha). 0 = centro. Evalúa la COBERTURA (lenguaje,
   selección de fuentes, encuadre), no el tema en sí.
3. "bias_reason" explica en 1-2 frases QUÉ elementos concretos de la nota
   sustentan ese score (palabras cargadas, fuentes citadas, orden de la info).
   Si hay "Otras coberturas del mismo hecho", puedes usar cómo enmarcan el
   mismo hecho de forma distinta como evidencia adicional del score.
4. "focus_analysis": 1-2 frases sobre qué ángulo eligió el medio (económico,
   humano, institucional, de seguridad...) y qué ángulo quedó fuera.
5. "focus_tags": 2-3 etiquetas cortas (máx. 4 palabras cada una).
6. "context": exactamente 3 objetos {"label", "text"} con antecedentes, datos
   comparables o posturas de otros actores que ayuden a entender el trasfondo.
   Si recibiste "Otras coberturas del mismo hecho", al menos uno de los 3
   puntos debe reflejar una postura, dato o énfasis real que aparece en esas
   coberturas y no en la nota principal — así el contraste de fuentes es
   real, no inventado (nunca cites esas coberturas textual, solo úsalas como
   referencia para escribir el punto con tus propias palabras). Si no hay
   coberturas hermanas, usa solo hechos que conozcas con confianza; si no
   tienes contexto sólido, di algo verificable y general, nunca inventes
   cifras exactas.
7. "category": una de politica, economia, tecnologia, sociedad, internacional,
   deportes, literatura. En deportes y literatura el sesgo político suele ser
   cercano a 0; evalúa igual el encuadre (p. ej. triunfalismo, nacionalismo,
   favoritismo hacia un club o una editorial) y explícalo en bias_reason.
8. "confidence": "alta" si el extracto era sustancioso, "media" si era corto,
   "baja" si apenas había titular.

Responde SOLO con el objeto JSON, sin markdown, sin texto adicional."""


def build_user_prompt(entry, source_name, related=None):
    # Preferir el texto completo de la nota (fetch_article_text) sobre el
    # extracto corto del feed — con solo ~1500 caracteres de teaser, el QC
    # no tiene manera de calificar bien "contraste_fuentes" ni
    # "veracidad_precision" (ver hallazgo del 9-10 jul 2026 en qc_log.json:
    # 52/54 rechazos, contraste_fuentes promediando 3.6/10 por depender solo
    # del extracto). Si el fetch falla, cae de vuelta al extracto — nunca
    # bloquea el análisis.
    article_text = entry.get("article_text") or ""
    if article_text:
        label, text = "Texto de la nota original (para tu resumen propio, NUNCA la cites textual)", article_text
    else:
        label, text = "Extracto del feed (no se pudo leer la nota completa)", entry.get("summary_text", "")

    # coberturas hermanas (find_related_entries): material real de otros
    # medios sobre el MISMO hecho, para que "contraste_fuentes" se pueda
    # calificar con evidencia real en vez de depender solo del conocimiento
    # de fondo del modelo (ver bloque "CONTRASTE DE FUENTES" más arriba).
    related_block = ""
    if related:
        pieces = "\n\n".join(
            f"- {r['source_name']}: \"{r['title']}\" — {r.get('summary_text', '')[:400]}"
            for r in related
        )
        related_block = (
            "\n\nOtras coberturas del MISMO hecho, de otros medios (para comparar "
            "encuadre y qué fuentes citó cada quien — NUNCA las cites textual, son "
            "solo referencia para tu propio análisis):\n" + pieces
        )

    return (
        f"Fuente: {source_name}\n"
        f"Titular: {entry.get('title', '')}\n"
        f"Fecha: {entry.get('published', '')}\n"
        f"{label}:\n{text[:6000]}"
        f"{related_block}"
    )


def fetch_article_text(url, max_chars=6000, timeout=12):
    """Descarga la nota original y regresa su texto visible, para darle al
    análisis material real en vez de depender solo del extracto de ~1500
    caracteres que trae el feed. Esto NUNCA se republica — solo alimenta el
    resumen propio del modelo (la regla de derechos de autor sigue intacta:
    el modelo ya tiene prohibido copiar frases, ahora solo tiene más de
    dónde partir para resumir con precisión).

    Es una descarga simple (regex, sin dependencias nuevas) que no siempre
    va a extraer texto perfectamente limpio (puede colar algo de menú o
    pie de página) — es una mejora sobre el extracto del feed, no un
    scraper robusto. Si falla por lo que sea (timeout, bloqueo, paywall,
    contenido no-HTML), regresa cadena vacía y build_user_prompt cae de
    vuelta al extracto del feed sin interrumpir el ciclo."""
    try:
        resp = requests.get(
            url, timeout=timeout,
            headers={"User-Agent": "Mozilla/5.0 (compatible; ContextoBot/1.0)"},
        )
        resp.raise_for_status()
        html = resp.text
        # fuera scripts/estilos/nav/menús antes de desnudar las etiquetas,
        # o su texto (JS, CSS, links de navegación) contamina el resultado
        html = re.sub(
            r"<(script|style|nav|header|footer|aside|form)[^>]*>.*?</\1>",
            " ", html, flags=re.I | re.S,
        )
        text = strip_html(html)
        text = re.sub(r"\s+", " ", text).strip()
        return text[:max_chars]
    except Exception:
        return ""


# ---------------------------------------------------------------------------
# UTILIDADES
# ---------------------------------------------------------------------------

def log(msg):
    stamp = datetime.now().strftime("%H:%M:%S")
    print(f"[{stamp}] {msg}", flush=True)


def strip_html(text):
    return re.sub(r"<[^>]+>", " ", text or "").strip()


def load_json(path, default):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def save_json(path, data):
    Path(path).write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def entry_id(url):
    return hashlib.sha1(url.encode("utf-8")).hexdigest()[:12]


def safe_url(url):
    """Solo deja pasar http(s). Un feed RSS comprometido o malicioso podría
    entregar un `link` con esquema javascript:/data:/vbscript: que el
    frontend (y build_pages) renderizan dentro de un href — esc() escapa
    comillas pero NO neutraliza el esquema, así que `href="javascript:…"`
    seguiría siendo clicable. Si el esquema no es web, se descarta el enlace
    (la nota se publica sin botón "Leer original"). Revisión seg. 10 jul 2026."""
    u = str(url or "").strip()
    low = u.lower()
    return u if low.startswith("http://") or low.startswith("https://") else ""


# ---------------------------------------------------------------------------
# CONTRASTE DE FUENTES: agrupar candidatas del mismo hecho antes de analizar
# ---------------------------------------------------------------------------
# El QC calificaba "contraste_fuentes" muy bajo (~3.6-4.2/10, ver hallazgo
# del 9-10 jul 2026) porque el análisis solo veía UNA nota de UN medio — no
# importa cuánto texto se le dé (fetch_article_text arriba ayuda, pero solo
# hasta cierto punto), un artículo aislado rara vez cita voces diversas por
# sí solo. Este bloque busca, dentro del pool de candidatas del mismo ciclo,
# otras coberturas de OTROS medios sobre el mismo hecho (por superposición
# de palabras del titular — mismo criterio que "coberturas relacionadas" en
# app.js/findRelated, portado aquí para que frontend y backend detecten
# temas relacionados de la misma forma) y se las pasa al modelo como
# material real de comparación — nunca para citarlas textual, solo para que
# el análisis pueda señalar diferencias de encuadre con base en hechos, no
# en adivinar. Si no hay coberturas hermanas, el análisis sigue con una
# sola fuente, tal como antes.

STOPWORDS_ES = {
    "para", "como", "sobre", "entre", "desde", "hasta", "contra", "durante",
    "ante", "tras", "este", "esta", "estos", "estas", "aquel", "aquella",
    "que", "los", "las", "del", "por", "con", "una", "uno", "unos", "unas",
    "mas", "pero", "sus", "ser", "son", "fue", "han", "hay", "sin", "segun",
    "nueva", "nuevo", "tres", "anos", "dias", "tiene", "sera", "esto",
    # ruido de titular de noticias del día: aparecen en decenas de notas sin
    # relación temática real entre sí (fecha del día, gentilicio del país,
    # muletillas de "en vivo") — sin esto, "9 de julio" o "México" bastaban
    # para "emparentar" notas que no tienen nada que ver.
    "hoy", "vivo", "mexico", "mexicana", "mexicano", "mexicanos", "mexicanas",
    "enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
    "septiembre", "octubre", "noviembre", "diciembre", "alerta", "donde",
    "juega", "asi",
}

MAX_RELATED_SOURCES = 3   # techo de coberturas hermanas que se incluyen en el prompt


def title_tokens(title):
    """Normaliza un titular a un set de palabras significativas — mismo
    criterio que titleTokens() en app.js, para que 'temas relacionados' se
    detecten igual en frontend y backend. Excluye tokens puramente numéricos
    (años, días del mes: "2026", "09") — son ruido temporal, no señal de
    tema; sin esto, dos notas de la misma fecha sobre hechos distintos
    parecían "relacionadas" solo por compartir el año."""
    ascii_title = unicodedata.normalize("NFKD", title or "").encode("ascii", "ignore").decode("ascii")
    words = re.findall(r"[a-z0-9]+", ascii_title.lower())
    return {w for w in words if len(w) > 3 and not w.isdigit() and w not in STOPWORDS_ES}


def find_related_entries(entry, pool, max_related=MAX_RELATED_SOURCES):
    """Busca en `pool` otras candidatas de OTRA fuente que compartan ≥2
    palabras significativas del titular con `entry` — señal de que cubren
    el mismo hecho. Regresa hasta `max_related`, como MUCHO una por medio
    (si un medio republica/actualiza la misma nota varias veces —p. ej. un
    live-blog del Mundial— solo cuenta la de mayor superposición; llenar
    los 3 espacios con el mismo medio no suma nada a "contraste_fuentes",
    que mide diversidad real de voces), ordenadas por más palabras
    compartidas primero."""
    base = title_tokens(entry["title"])
    if not base:
        return []
    best_per_source = {}
    for other in pool:
        if other["link"] == entry["link"] or other["source_name"] == entry["source_name"]:
            continue
        overlap = len(base & title_tokens(other["title"]))
        if overlap < 2:
            continue
        current = best_per_source.get(other["source_name"])
        if current is None or overlap > current[0]:
            best_per_source[other["source_name"]] = (overlap, other)
    scored = list(best_per_source.values())
    scored.sort(key=lambda x: x[0], reverse=True)
    return [e for _, e in scored[:max_related]]


# ---------------------------------------------------------------------------
# PASO 1-2: LEER FEEDS Y DEDUPLICAR
# ---------------------------------------------------------------------------

def fetch_new_entries(seen_urls):
    """Recorre todos los feeds y regresa entradas aún no publicadas."""
    fresh = []
    for src in SOURCES:
        try:
            parsed = feedparser.parse(src["feed"])
            if parsed.bozo and not parsed.entries:
                log(f"  ⚠ Feed ilegible: {src['name']}")
                continue
            # 25 en vez de 10: leer más entradas del feed no cuesta nada (es
            # solo parseo de XML, no llama a la API) — lo que sí cuesta está
            # controlado aparte por MAX_NEW_PER_CYCLE y el presupuesto diario
            # (ver budget.py). Una ventana angosta aquí sí tiene costo: si una
            # fuente muy activa publica más de N notas entre un ciclo y el
            # siguiente, las que quedan fuera del top-N del feed se pierden en
            # silencio (nunca vuelven a aparecer como "recientes").
            for e in parsed.entries[:25]:
                url = e.get("link", "").strip()
                if not url or url in seen_urls:
                    continue
                fresh.append({
                    "source_name": src["name"],
                    "default_category": src["default_category"],
                    "title": strip_html(e.get("title", "")),
                    "summary_text": strip_html(e.get("summary", e.get("description", ""))),
                    "published": e.get("published", e.get("updated", "")),
                    "published_parsed": e.get("published_parsed"),
                    "link": url,
                })
            log(f"  ✓ {src['name']}: feed leído")
        except Exception as exc:
            log(f"  ⚠ Error con {src['name']}: {exc}")
    # más recientes primero
    fresh.sort(
        key=lambda x: time.mktime(x["published_parsed"]) if x["published_parsed"] else 0,
        reverse=True,
    )
    return fresh


# ---------------------------------------------------------------------------
# PASO 3: ANÁLISIS CON CLAUDE
# ---------------------------------------------------------------------------

def analyze_entry(entry, api_key, pool):
    """Llama a la API de Anthropic y regresa el análisis como dict, o None.
    Se detiene sin llamar a la API si ya se agotó el presupuesto diario.
    `pool` es el conjunto completo de candidatas del ciclo (fresh), usado
    para encontrar coberturas hermanas de otros medios (ver
    find_related_entries) — no cuesta una llamada extra, es búsqueda local."""
    if not budget.can_spend("news"):
        log(f"  💰 Presupuesto diario de noticias agotado — se omite «{entry['title'][:50]}…»")
        return None
    # leer la nota completa SOLO ahora (justo antes de gastar la llamada a
    # la API) — no al descubrir el candidato, para no pagar el costo de red
    # de fetches que después ni siquiera se llegan a analizar si el
    # presupuesto se agota a mitad de ciclo (budget.can_spend arriba)
    if "article_text" not in entry:
        entry["article_text"] = fetch_article_text(entry["link"])
        if not entry["article_text"]:
            log(f"    (no se pudo leer la nota completa, uso el extracto del feed)")
    related = find_related_entries(entry, pool)
    if related:
        fuentes = ", ".join(r["source_name"] for r in related)
        log(f"    (+{len(related)} cobertura(s) relacionada(s): {fuentes})")
    user_prompt = build_user_prompt(entry, entry["source_name"], related)
    try:
        # Sonnet 5 razona antes de responder y eso consume max_tokens; se
        # necesita holgura para que el JSON no salga truncado. Esfuerzo
        # medio: en Sonnet 5 equivale al nivel alto del modelo anterior —
        # buen balance calidad/costo para análisis por nota. (Si
        # LLM_PROVIDER=inception, call_llm ignora ANALYSIS_MODEL/effort y
        # usa Mercury — ver agent/llm_client.py.)
        text, usage, model_used = llm_client.call_llm(
            system=ANALYSIS_SYSTEM_PROMPT,
            user_content=user_prompt,
            api_key=api_key,
            model=ANALYSIS_MODEL,
            max_tokens=4000,
            effort="medium",
        )
        budget.record_usage(model_used, usage, "news")
        clean = re.sub(r"```(?:json)?|```", "", text).strip()
        data = json.loads(clean)
    except Exception as exc:
        log(f"  ⚠ Análisis falló para «{entry['title'][:50]}…»: {exc}")
        return None

    # saneamiento defensivo
    if data.get("category") not in VALID_CATEGORIES:
        data["category"] = entry["default_category"]
    try:
        data["bias_score"] = max(-100, min(100, int(data.get("bias_score", 0))))
    except (TypeError, ValueError):
        data["bias_score"] = 0
    data["focus_tags"] = list(data.get("focus_tags", []))[:3]
    data["context"] = [
        c for c in data.get("context", [])
        if isinstance(c, dict) and c.get("label") and c.get("text")
    ][:3]
    if data.get("confidence") not in {"alta", "media", "baja"}:
        data["confidence"] = "media"
    return data


LITERATURE_SYSTEM_PROMPT = """Eres el editor literario del portal "Contexto".
Una vez al día publicas una pieza de mano libre: tú eliges el tema con total
libertad. Puede ser una recomendación de libro (clásico o contemporáneo, de
cualquier país o género), un perfil breve de un autor o autora, una efeméride
literaria de la fecha, una reflexión sobre un género o movimiento, o una
conexión entre literatura y la vida cotidiana.

El tema Y el ángulo son enteramente tu decisión — libro, autor, época, país,
género, la conexión que se te ocurra: no hay tema obligatorio ni ángulo
prohibido. Lo único que sí importa es CÓMO lo escribes: antes de empezar,
decide en silencio (no lo muestres en la respuesta) una imagen o metáfora
concreta que sostenga toda la pieza — constrúyela, no la menciones de paso.

Reglas de escritura — esto es lo que más ha hecho rechazar piezas hasta
ahora (flojas en originalidad y riqueza de estilo, aunque bien estructuradas
y correctas), tómalas en serio:
1. Prohibido abrir con fórmulas gastadas: "X es un autor/a conocido/a
   por...", "Hoy quiero hablarles de...", "Pocos saben que...", "En el
   mundo de la literatura...". Abre con la imagen o el detalle concreto que
   decidiste antes de escribir, no con una presentación genérica.
2. Cada frase se gana su lugar: nada de relleno ("es interesante notar
   que...", "sin duda...", "cabe destacar..."). Vocabulario preciso y
   evocador, no ornamentado por ornamentar.
3. Usa al menos un recurso retórico real (metáfora, símil, paradoja,
   yuxtaposición) construido con cuidado, que cargue sentido — no
   decorativo.
4. Escribe todo con tus propias palabras. PROHIBIDO reproducir poemas,
   versos, letras de canciones o pasajes de libros — puedes describir su
   estilo y temas, nunca citarlos textualmente.
5. Recomienda solo obras y autores reales que conozcas con certeza. No
   inventes títulos, fechas ni premios.
6. Varía: si te doy los títulos de piezas recientes, elige algo distinto en
   tema, época y geografía.
7. Tono: cálido, curioso, sin solemnidad. Como quien recomienda un libro a
   un amigo, no como quien dicta cátedra — pero cuidado en cada frase, no
   informal por descuido.

Vas a pasar por un control de calidad que rechaza piezas de enfoque trillado
o estilo plano aunque estén bien escritas en lo estructural — la corrección
no basta, hace falta una perspectiva propia y lenguaje que valga la pena leer.

Responde SOLO con un objeto JSON con estos campos:
- "title": titular atractivo de la pieza (máx. 90 caracteres) — que refleje
  tu ángulo, no un titular genérico tipo "Perfil de X"
- "summary": 2-3 frases que abren la pieza con la imagen central que
  decidiste — es la parte que más pesa en el control de calidad, no la
  gastes en contexto genérico
- "focus_analysis": 2-3 frases explicando por qué elegiste este tema y este
  ángulo hoy
- "focus_tags": 2-3 etiquetas cortas (género, época, país...)
- "context": exactamente 3 objetos {"label", "text"} con rutas para el
  lector: por dónde empezar con el autor, obras afines, o datos de
  trasfondo — cada "text" también va bien escrito, no es una ficha técnica."""


def publish_daily_literature(api_key, published):
    """Publica la pieza literaria de mano libre si hoy aún no existe.
    Se detiene sin llamar a la API si ya se agotó el presupuesto diario
    (se reintenta en un ciclo posterior, el mismo día o el siguiente)."""
    # "Hoy" en hora de Ciudad de México, no UTC (14 jul 2026): antes
    # comparaba el prefijo del ISO guardado (siempre UTC) contra
    # datetime.now() sin zona (UTC en los runners de Actions) — coincidía
    # casi siempre, pero fallaba justo entre las 18:00 y medianoche hora
    # CDMX, cuando UTC ya había cruzado al día siguiente.
    today = mx_date_str()
    for art in published:
        if not (art.get("editorial_pick") and art.get("published_at")):
            continue
        try:
            pub_dt = datetime.fromisoformat(str(art["published_at"]).replace("Z", "+00:00"))
            if pub_dt.tzinfo is None:
                pub_dt = pub_dt.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
        if mx_date_str(pub_dt) == today:
            return None  # la de hoy ya está publicada

    if not budget.can_spend("news"):
        log("  💰 Presupuesto diario de noticias agotado — se omite la pieza literaria de hoy")
        return None

    recent_titles = [
        a["title"] for a in published if a.get("editorial_pick")
    ][:15]
    now_mx = datetime.now(tz=timezone.utc).astimezone(MX_TZ)
    fecha_hoy = f"{now_mx.day} de {MESES_ES[now_mx.month - 1]} de {now_mx.year}"
    user_prompt = (
        f"Fecha de hoy: {fecha_hoy}.\n"
        f"Títulos de tus piezas recientes (elige algo distinto):\n- "
        + ("\n- ".join(recent_titles) if recent_titles else "(ninguna todavía)")
    )

    try:
        # Fable 5 siempre razona antes de escribir (no se puede desactivar)
        # y ese razonamiento consume max_tokens — holgura amplia para la
        # única pieza del día, donde la calidad es prioridad. (Si
        # LLM_PROVIDER=inception, call_llm ignora LITERATURE_MODEL y usa
        # Mercury — ver agent/llm_client.py.)
        text, usage, model_used = llm_client.call_llm(
            system=LITERATURE_SYSTEM_PROMPT,
            user_content=user_prompt,
            api_key=api_key,
            model=LITERATURE_MODEL,
            max_tokens=8000,
        )
        budget.record_usage(model_used, usage, "news")
        data = json.loads(re.sub(r"```(?:json)?|```", "", text).strip())
    except Exception as exc:
        log(f"  ⚠ Pieza literaria falló: {exc}")
        return None

    now_iso = datetime.now(tz=timezone.utc).isoformat()
    return {
        "id": entry_id(f"lit-{today}"),
        "title": str(data.get("title", "Pieza literaria del día"))[:120],
        "summary": data.get("summary", ""),
        "category": "literatura",
        "source_name": "Contexto · redacción propia",
        "source_url": "",
        "published_at": now_iso,
        "bias_score": 0,
        "bias_reason": "",
        "focus_analysis": data.get("focus_analysis", ""),
        "focus_tags": list(data.get("focus_tags", []))[:3],
        "context": [
            c for c in data.get("context", [])
            if isinstance(c, dict) and c.get("label") and c.get("text")
        ][:3],
        "confidence": "alta",
        "editorial_pick": True,
    }


def to_iso(entry):
    if entry.get("published_parsed"):
        return datetime.fromtimestamp(
            time.mktime(entry["published_parsed"]), tz=timezone.utc
        ).isoformat()
    return datetime.now(tz=timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# PASO 4: CONTROL DE CALIDAD Y PUBLICACIÓN
# ---------------------------------------------------------------------------

def record_verdict(qc_log, article, qc):
    """Deja constancia de cada veredicto del QC (aprobado o no) en la bitácora."""
    qc_log.append({
        "at": datetime.now(tz=timezone.utc).isoformat(),
        "title": article.get("title", "")[:100],
        "kind": "literatura" if article.get("editorial_pick") else "noticia",
        "approved": qc["approved"],
        "overall": qc["overall"],
        "scores": qc["scores"],
        "observacion": qc.get("observacion_global", ""),
        "error": qc.get("error"),
    })


def run_cycle(api_key):
    log("── Iniciando ciclo de lectura ──")
    if not budget.can_spend("news"):
        log(f"  💰 Presupuesto diario de noticias ya alcanzado (${budget.spent_today('news'):.2f} de "
            f"${budget.DAILY_BUDGET_USD['news']:.2f}) — este ciclo no hará llamadas nuevas a la API.")
    state = load_json(STATE_FILE, {"seen": []})
    seen = set(state["seen"])
    qc_log = load_json(QC_LOG_FILE, {"verdicts": []}).get("verdicts", [])

    fresh = fetch_new_entries(seen)
    log(f"Notas nuevas detectadas: {len(fresh)} (meta mínima: {MAX_NEW_PER_CYCLE} "
        f"publicadas; sin techo — se procesa todo el pool, el presupuesto diario "
        f"es el único límite real)")

    portal = load_json(OUTPUT_JSON, {"articles": []})
    published = [a for a in portal.get("articles", []) if a.get("id") not in EXCLUDED_IDS]
    new_count = 0
    qc_rejected = 0

    # pieza literaria de mano libre: una por día, si pasa el control de calidad
    # (si el QC la rechaza, el siguiente ciclo genera una pieza nueva)
    lit_piece = publish_daily_literature(api_key, published)
    if lit_piece:
        qc = quality_check(lit_piece, api_key)
        record_verdict(qc_log, lit_piece, qc)
        if qc["approved"]:
            if qc["overall"] is not None:
                lit_piece["qc"] = {"overall": qc["overall"]}
            published.insert(0, lit_piece)
            new_count += 1
            log(f"  ✒ Pieza literaria del día publicada (QC {qc['overall']}/10): {lit_piece['title'][:60]}")
        else:
            qc_rejected += 1
            log(f"  ✗ QC rechazó la pieza literaria ({qc['overall']}/10): {qc['observacion_global'][:90]}")

    # Se procesa TODO el pool `fresh` cada ciclo, sin techo de cuántas se
    # publican ni de cuántas se intentan — MAX_NEW_PER_CYCLE es solo una
    # meta mínima para el log (ver su comentario arriba). El único límite
    # real es el presupuesto diario (budget.can_spend), como en el resto
    # del pipeline. Nunca se baja la vara del QC para forzar un número: un
    # día de mala calidad simplemente publica menos, y uno con mucho
    # material bueno publica más de la meta sin que nada lo frene.
    news_published = 0
    attempts = 0
    for entry in fresh:
        if not budget.can_spend("news"):
            log(f"  💰 Presupuesto diario de noticias agotado a mitad de ciclo — se detiene "
                f"el análisis por hoy ({entry['title'][:50]}… y las siguientes "
                f"quedan pendientes, NO se marcan como vistas).")
            break  # a propósito: no marcar "seen" lo que no se llegó a analizar
        attempts += 1
        log(f"  → Analizando: {entry['title'][:70]}")
        analysis = analyze_entry(entry, api_key, fresh)
        seen.add(entry["link"])  # aunque falle, no reintentar en bucle
        if not analysis:
            continue
        article = {
            "id": entry_id(entry["link"]),
            "title": entry["title"],
            "summary": analysis.get("summary", ""),
            "category": analysis["category"],
            "source_name": entry["source_name"],
            "source_url": safe_url(entry["link"]),
            "published_at": to_iso(entry),
            "bias_score": analysis["bias_score"],
            "bias_reason": analysis.get("bias_reason", ""),
            "focus_analysis": analysis.get("focus_analysis", ""),
            "focus_tags": analysis["focus_tags"],
            "context": analysis["context"],
            "confidence": analysis["confidence"],
        }
        qc = quality_check(article, api_key)
        record_verdict(qc_log, article, qc)
        if not qc["approved"]:
            qc_rejected += 1
            log(f"  ✗ QC rechazó ({qc['overall']}/10): {entry['title'][:60]}")
            continue
        if qc["overall"] is not None:
            article["qc"] = {"overall": qc["overall"]}
        published.insert(0, article)
        new_count += 1
        news_published += 1
        time.sleep(1)  # cortesía con la API

    if news_published < MAX_NEW_PER_CYCLE:
        log(f"  ⚠ {news_published} publicadas, por debajo de la meta mínima de "
            f"{MAX_NEW_PER_CYCLE} — el pool no alcanzó o el QC rechazó de más este "
            f"ciclo (nunca se baja la vara para forzar el número).")
    else:
        log(f"  ✓ {news_published} publicadas este ciclo (meta mínima: {MAX_NEW_PER_CYCLE}).")

    # actualiza el índice PERMANENTE de la hemeroteca ANTES de recortar
    # `published` — así una nota entra al archivo en el momento en que se
    # publica, sin importar cuántos ciclos después salga de las
    # MAX_ARTICLES_KEPT vivas de la portada. Dedup por id (por si una nota
    # ya archivada sigue viva y se vuelve a ver aquí) y nunca se recorta.
    archive = [a for a in load_json(HEMEROTECA_JSON, {"articles": []}).get("articles", [])
               if a.get("id") not in EXCLUDED_IDS]
    archived_ids = {a["id"] for a in archive if a.get("id")}
    for a in published:
        if a.get("id") and a["id"] not in archived_ids:
            archive.append({
                "id": a["id"],
                "title": a["title"],
                "category": a.get("category", ""),
                "published_at": a.get("published_at", ""),
            })
            archived_ids.add(a["id"])
    archive.sort(key=lambda a: a.get("published_at") or "", reverse=True)
    save_json(HEMEROTECA_JSON, {
        "generated_at": datetime.now(tz=timezone.utc).isoformat(),
        "articles": archive,
    })

    # recorte del archivo y persistencia
    published = published[:MAX_ARTICLES_KEPT]
    save_json(OUTPUT_JSON, {
        "generated_at": datetime.now(tz=timezone.utc).isoformat(),
        "articles": published,
    })
    # Revista jurídica y reseñas de lectores YA NO se procesan aquí: tienen
    # su propio workflow (.github/workflows/moderacion.yml, cada 3 horas) y
    # su propio cron, desacoplado a propósito del ciclo de noticias — así el
    # gasto de Fable 5 en jurídica/reseñas no depende de la frecuencia del
    # agente de noticias. Corre `python agent/juridica.py` o
    # `python agent/resenas.py` a mano si quieres dictaminar algo ya mismo.

    save_json(STATE_FILE, {"seen": sorted(seen)[-2000:]})  # limitar memoria
    save_json(QC_LOG_FILE, {"verdicts": qc_log[-200:]})    # bitácora acotada

    try:
        build_pages.build_all()   # páginas por artículo + sitemap (sin API)
    except Exception as exc:
        log(f"⚠ Generación de páginas falló (el portal sigue funcionando): {exc}")

    log(f"── Ciclo terminado: {new_count} publicadas, {qc_rejected} rechazadas por QC, "
        f"{len(published)} vivas en portal ──")


def main():
    parser = argparse.ArgumentParser(description="Agente de noticias de Contexto")
    parser.add_argument("--loop", type=int, metavar="SEGUNDOS",
                        help="Modo vigilante: repite el ciclo cada N segundos (mín. 300)")
    args = parser.parse_args()

    api_key = llm_client.get_api_key()
    if not api_key:
        sys.exit(
            f"Define la variable de entorno {llm_client.api_key_env_name()} antes de "
            f"ejecutar (proveedor activo: {llm_client.PROVIDER}, ver agent/llm_client.py)."
        )

    if args.loop:
        interval = max(300, args.loop)
        log(f"Modo vigilante activado: ciclo cada {interval} s. Ctrl+C para detener.")
        while True:
            try:
                run_cycle(api_key)
            except Exception as exc:
                log(f"⚠ Ciclo falló, se reintentará: {exc}")
            time.sleep(interval)
    else:
        run_cycle(api_key)


if __name__ == "__main__":
    main()
