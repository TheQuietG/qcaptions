"""Correcciones post-transcripción (diccionario configurable en config.toml).

Soporta reemplazos de una o varias palabras. Un reemplazo multi-palabra
(ej: "ene ocho ene" -> "n8n") colapsa las palabras coincidentes en una sola,
tomando start = primer inicio y end = último fin, evitando cortar siglas/cifras.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path


def load_corrections(
    config_paths: Path | list[Path] | None,
) -> list[tuple[list[str], str]]:
    """Carga y mergea las reglas de uno o varios config.toml.

    Formato:
        [corrections]
        "ene ocho ene" = "n8n"
        "quimballa" = "Quimbaya"

    Si se pasan varias rutas, se mergean en orden: las últimas pisan a las
    primeras (típico: config del proyecto primero, config del usuario después).

    Devuelve una lista de (tokens_origen_normalizados, texto_destino),
    ordenada de frases más largas a más cortas (para hacer match ávido).
    """
    if config_paths is None:
        return []
    if isinstance(config_paths, Path):
        config_paths = [config_paths]

    merged: dict[str, str] = {}
    for path in config_paths:
        if path is None or not path.exists():
            continue
        data = tomllib.loads(path.read_text(encoding="utf-8"))
        for src, dst in data.get("corrections", {}).items():
            # clave normalizada para que "Cloud" (usuario) pise "cloud" (proyecto)
            key = " ".join(_norm(t) for t in str(src).split() if t.strip())
            if key:
                merged[key] = str(dst)

    rules: list[tuple[list[str], str]] = [
        (key.split(" "), dst) for key, dst in merged.items()
    ]
    # frases largas primero para que ganen sobre reemplazos de 1 palabra
    rules.sort(key=lambda r: len(r[0]), reverse=True)
    return rules


def apply_corrections(
    words: list[dict], rules: list[tuple[list[str], str]]
) -> list[dict]:
    """Aplica las reglas sobre la secuencia de palabras.

    - Reemplazo de 1->1: cambia el texto conservando tiempos.
    - Reemplazo de N->1: colapsa N palabras en una (tiempos min/max).
    """
    if not rules:
        return words
    result: list[dict] = []
    i = 0
    n = len(words)
    while i < n:
        matched = False
        for tokens, dst in rules:
            k = len(tokens)
            if i + k > n:
                continue
            window = [_norm(words[j]["word"]) for j in range(i, i + k)]
            if window == tokens:
                start = words[i]["start"]
                end = words[i + k - 1]["end"]
                result.append(
                    {"word": dst, "start": start, "end": end}
                )
                i += k
                matched = True
                break
        if not matched:
            result.append(dict(words[i]))
            i += 1
    return result


def _norm(text: str) -> str:
    """Normaliza para comparar: minúsculas, sin puntuación de borde ni acentos."""
    text = text.strip().lower()
    text = re.sub(r"[^\w]", "", text, flags=re.UNICODE)
    trans = str.maketrans("áéíóúüñ", "aeiouun")
    return text.translate(trans)
