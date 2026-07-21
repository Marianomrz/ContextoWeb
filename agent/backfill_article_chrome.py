#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CONTEXTO — Backfill de "cromo" global en páginas de nota archivadas
====================================================================
build_pages.py CONGELA las páginas de notas archivadas: solo regenera las
notas vivas de articles.json y nunca vuelve a tocar las viejas (a propósito,
para no reescribir su contenido — ver CLAUDE.md). Eso funciona bien para el
CONTENIDO, pero cuando se agrega UI GLOBAL a "todas las páginas" (el enlace
"Mi cuenta" del footer en Fase 1, el botón de favorito en Fase 2), ese cromo
solo llega a las notas vivas y las archivadas se quedan atrás.

No se pueden re-renderizar desde hemeroteca.json (solo guarda un subconjunto:
id/title/category/bias_score/source_name/published_at — le faltan summary,
context, focus_analysis, etc.). Así que este script PARCHA el HTML existente
sin tocar el contenido: inserta solo lo que falte, es idempotente (se puede
correr varias veces sin duplicar), y se limita a articulo/ (las páginas de
revista/ sí se regeneran en cada build, no las congela nada).

Uso: python agent/backfill_article_chrome.py
Cuándo: una sola vez tras agregar cromo global nuevo. Si una fase futura
suma otro elemento global a la plantilla de articulo/ en build_pages.py,
agrégalo aquí también y vuelve a correrlo.
"""

import pathlib
import re
import sys

BASE_DIR = pathlib.Path(__file__).resolve().parent.parent
ART_DIR = BASE_DIR / "articulo"

FAV_BUTTON = (
    '<button type="button" class="fav-btn" data-fav="{id}" aria-pressed="false">\n'
    '      <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" '
    'stroke-width="1.8" aria-hidden="true"><path d="M6 3h12a1 1 0 0 1 1 1v17l-7-4-7 4V4a1 1 0 0 1 1-1z"/></svg>\n'
    '      <span class="fav-label">Guardar</span>\n'
    '    </button>'
)


def patch(html, article_id):
    """Devuelve (html_parcheado, lista_de_cambios). Cada inserción está
    guardada por un 'if ... not in html', así que correrlo de nuevo no
    duplica nada."""
    changes = []

    # 1) enlace "Mi cuenta" en el footer, antes de Correcciones (Fase 1)
    if "cuenta.html" not in html and '<a href="../correcciones.html">Correcciones</a>' in html:
        html = html.replace(
            '<a href="../correcciones.html">Correcciones</a>',
            '<a href="../cuenta.html">Mi cuenta</a>\n'
            '      <a href="../correcciones.html">Correcciones</a>',
            1,
        )
        changes.append("footer")

    # 2) botón de favorito en el pie del artículo, antes de confidence-note (Fase 2)
    if "data-fav" not in html and '<span class="confidence-note">' in html:
        html = html.replace(
            '<span class="confidence-note">',
            FAV_BUTTON.format(id=article_id) + '\n      <span class="confidence-note">',
            1,
        )
        changes.append("fav-btn")

    # 3) módulo favoritos.js, después de share.js (Fase 2)
    if "favoritos.js" not in html and '<script src="../share.js"></script>' in html:
        html = html.replace(
            '<script src="../share.js"></script>',
            '<script src="../share.js"></script>\n'
            '<script type="module" src="../favoritos.js"></script>',
            1,
        )
        changes.append("favoritos.js")

    return html, changes


def main():
    if not ART_DIR.is_dir():
        print(f"backfill: no existe {ART_DIR}")
        return 1
    patched = 0
    skipped = 0
    for page in sorted(ART_DIR.glob("*.html")):
        article_id = page.stem
        original = page.read_text(encoding="utf-8")
        new, changes = patch(original, article_id)
        if changes:
            page.write_text(new, encoding="utf-8")
            patched += 1
        else:
            skipped += 1
    print(f"backfill: {patched} páginas parchadas, {skipped} ya estaban al día")
    return 0


if __name__ == "__main__":
    sys.exit(main())
