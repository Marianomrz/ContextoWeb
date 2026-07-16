#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CONTEXTO — Smoke test de articles.json (agregado 16 jul 2026)
================================================================
Valida articles.json ANTES de que el workflow lo comitee: JSON bien
formado, "articles" es una lista, y cada nota trae los campos que
renderArticle() en app.js necesita para no romper el frontend (ver
"Esquema de artículo" en CLAUDE.md — cambiar un campo ahí exige cambiar
ambos lados). No es un control de calidad editorial (eso ya lo hace
agent/quality.py antes de publicar) — es solo una red de seguridad
estructural: si algo corrompe el JSON o deja un campo requerido vacío,
esto para el commit en vez de dejar pasar un articles.json roto a
producción.

Uso: python agent/validate_articles.py [ruta opcional, default articles.json]
Sale con código 1 y un mensaje claro si algo no pasa; 0 si todo bien.
También valida hemeroteca.json si existe (mismo esquema, menos estricto:
solo id/title/category/published_at, ver agent.py).
"""
import json
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

VALID_CATEGORIES = {
    "politica", "economia", "tecnologia", "sociedad",
    "internacional", "deportes", "literatura",
}

# Campos que renderArticle() (app.js) y render_article_page() (build_pages.py)
# leen directamente — si faltan, la tarjeta o la página de la nota se rompen
# o se ven a medias en vez de fallar ruidosamente.
REQUIRED_FIELDS = ["id", "title", "summary", "category", "source_name", "published_at"]


def validate_article(a, idx, errors):
    if not isinstance(a, dict):
        errors.append(f"articles[{idx}]: no es un objeto ({type(a).__name__})")
        return
    label = a.get("id", f"índice {idx}")
    for field in REQUIRED_FIELDS:
        if not a.get(field):
            errors.append(f"{label}: falta o está vacío el campo requerido \"{field}\"")
    cat = a.get("category")
    if cat is not None and cat not in VALID_CATEGORIES:
        errors.append(f"{label}: categoría \"{cat}\" no está en VALID_CATEGORIES")
    # bias_score es obligatorio salvo en piezas de mano libre (editorial_pick)
    if not a.get("editorial_pick"):
        score = a.get("bias_score")
        if not isinstance(score, int) or not (-100 <= score <= 100):
            errors.append(f"{label}: bias_score inválido ({score!r}), debe ser int entre -100 y 100")
    for list_field in ("focus_tags", "context"):
        val = a.get(list_field)
        if val is not None and not isinstance(val, list):
            errors.append(f"{label}: \"{list_field}\" debería ser una lista, es {type(val).__name__}")


def validate_file(path, label, strict=True):
    errors = []
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        print(f"validate_articles: {label} no existe todavía — se omite (normal en la primera corrida)")
        return []
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        return [f"{label}: JSON inválido — {exc}"]
    if not isinstance(data, dict) or "articles" not in data:
        return [f"{label}: falta la clave \"articles\" en el nivel superior"]
    if not isinstance(data["articles"], list):
        return [f"{label}: \"articles\" debería ser una lista, es {type(data['articles']).__name__}"]
    if strict:
        for idx, a in enumerate(data["articles"]):
            validate_article(a, idx, errors)
    return errors


def main():
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else BASE_DIR / "articles.json"
    errors = validate_file(target, target.name, strict=True)
    # hemeroteca.json usa un esquema reducido a propósito (ver agent.py,
    # solo id/title/category/published_at) — no aplica la validación
    # estricta de bias_score/campos completos, solo que sea JSON válido con
    # la forma correcta.
    errors += validate_file(BASE_DIR / "hemeroteca.json", "hemeroteca.json", strict=False)

    if errors:
        print(f"validate_articles: {len(errors)} problema(s) encontrado(s) — NO se debe comitear:")
        for e in errors[:30]:
            print(f"  ✗ {e}")
        if len(errors) > 30:
            print(f"  … y {len(errors) - 30} más")
        return 1
    print(f"validate_articles: OK ({target.name} y hemeroteca.json bien formados)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
