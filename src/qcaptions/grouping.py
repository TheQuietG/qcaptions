"""Agrupación de palabras en captions (líneas de subtítulo)."""

from __future__ import annotations

# Si el hueco entre dos palabras supera esto, forzamos corte de caption
# (pausa natural del hablante).
GAP_BREAK_S = 0.6


def group_words(
    words: list[dict],
    max_words: int = 4,
    max_duration: float = 1.8,
) -> list[dict]:
    """Agrupa palabras en captions de <= max_words o <= max_duration segundos,
    lo que ocurra primero. También corta en pausas largas.

    Cada caption: {start, end, words: [{word, start, end}, ...]}.
    """
    captions: list[dict] = []
    current: list[dict] = []

    def flush() -> None:
        if current:
            captions.append(
                {
                    "start": current[0]["start"],
                    "end": current[-1]["end"],
                    "words": list(current),
                }
            )
            current.clear()

    for w in words:
        if current:
            span = w["end"] - current[0]["start"]
            gap = w["start"] - current[-1]["end"]
            if len(current) >= max_words or span > max_duration or gap > GAP_BREAK_S:
                flush()
        current.append(w)

    flush()
    return captions
