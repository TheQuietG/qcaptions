"""Generación del archivo .ass con estilo karaoke (branding Data Quimbaya).

Efecto: texto blanco con borde negro grueso; la palabra que se está hablando
se resalta en dorado (#D4AF37) y vuelve a blanco al terminar. Entrada con
un "pop" sutil (escala 110% -> 100% en ~80 ms).

El resaltado de una sola palabra activa se logra con transforms \\t por palabra
(no con \\k acumulativo, que dejaría doradas todas las palabras ya habladas).
"""

from __future__ import annotations

from dataclasses import dataclass

# --- Colores en formato ASS (&HAABBGGRR) ---
WHITE = "&H00FFFFFF"          # texto base
BLACK = "&H00000000"          # borde
GOLD = "&H0037AFD4"           # #D4AF37 dorado Data Quimbaya (BGR)

PLAY_RES_X = 1080
PLAY_RES_Y = 1920


@dataclass
class AssStyle:
    fontname: str = "Montserrat ExtraBold"
    fontsize: int = 90
    outline: int = 6
    shadow: int = 0
    margin_v: int = 600
    margin_lr: int = 60
    uppercase: bool = True
    pop: bool = True
    play_res_x: int = PLAY_RES_X
    play_res_y: int = PLAY_RES_Y


def scale_style(style: AssStyle, width: int, height: int) -> AssStyle:
    """Adapta el estilo (diseñado sobre 1080x1920) a la resolución real.

    Escala fontsize/outline/márgenes proporcionalmente para que el texto se
    vea igual en 4K vertical, horizontal, etc. Los valores ya ajustados por
    el usuario (via flags) deben pasarse DESPUÉS de escalar.
    """
    fx = width / PLAY_RES_X
    fy = height / PLAY_RES_Y
    return AssStyle(
        fontname=style.fontname,
        fontsize=max(1, round(style.fontsize * fx)),
        outline=max(1, round(style.outline * fx)),
        shadow=style.shadow,
        margin_v=round(style.margin_v * fy),
        margin_lr=round(style.margin_lr * fx),
        uppercase=style.uppercase,
        pop=style.pop,
        play_res_x=width,
        play_res_y=height,
    )


def build_ass(captions: list[dict], style: AssStyle) -> str:
    """Construye el contenido completo del .ass a partir de los captions."""
    header = _header(style)
    events = [_dialogue(c, style) for c in captions]
    return header + "\n".join(events) + "\n"


def _header(style: AssStyle) -> str:
    # Bold=1 (por si la familia ExtraBold no está disponible, el fallback pesa).
    # PrimaryColour = blanco base; el dorado se aplica por-palabra con \t.
    return f"""[Script Info]
; qcaptions — Data Quimbaya
ScriptType: v4.00+
PlayResX: {style.play_res_x}
PlayResY: {style.play_res_y}
WrapStyle: 0
ScaledBorderAndShadow: yes
YCbCr Matrix: TV.709

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: DQ,{style.fontname},{style.fontsize},{WHITE},{WHITE},{BLACK},&H00000000,1,0,0,0,100,100,0,0,1,{style.outline},{style.shadow},2,{style.margin_lr},{style.margin_lr},{style.margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""


def _dialogue(caption: dict, style: AssStyle) -> str:
    start = caption["start"]
    end = caption["end"]
    line_start = start  # referencia para los tiempos relativos de \t (ms)

    parts: list[str] = []

    # "Pop" de entrada: escala 110 -> 100 en 80 ms, aplicado a toda la línea.
    if style.pop:
        parts.append(r"{\fscx110\fscy110\t(0,80,\fscx100\fscy100)}")

    for idx, w in enumerate(caption["words"]):
        text = w["word"]
        if style.uppercase:
            text = text.upper()
        text = _escape(text)

        rel_start = int(round((w["start"] - line_start) * 1000))
        rel_end = int(round((w["end"] - line_start) * 1000))
        rel_start = max(rel_start, 0)
        if rel_end <= rel_start:
            rel_end = rel_start + 1

        # La palabra activa se pone dorada durante su ventana y vuelve a blanca.
        # Los transforms \t de duración cero funcionan en libass para t>0, pero
        # NO para \t(0,0). Por eso, si la palabra ya está activa al inicio de la
        # línea (rel_start==0), pintamos el color base dorado directamente.
        if rel_start == 0:
            tag = f"{{\\1c{GOLD}\\t({rel_end},{rel_end},\\1c{WHITE})}}"
        else:
            tag = (
                f"{{\\1c{WHITE}"
                f"\\t({rel_start},{rel_start},\\1c{GOLD})"
                f"\\t({rel_end},{rel_end},\\1c{WHITE})}}"
            )
        parts.append(tag + text)
        if idx != len(caption["words"]) - 1:
            parts.append(" ")

    text_field = "".join(parts)
    return (
        f"Dialogue: 0,{_ts(start)},{_ts(end)},DQ,,0,0,0,,{text_field}"
    )


def _escape(text: str) -> str:
    # Evita que llaves o backslashes del texto rompan el parseo de tags.
    return text.replace("\\", "\\\\").replace("{", "\\{").replace("}", "\\}")


def _ts(seconds: float) -> str:
    """Formato de tiempo ASS: H:MM:SS.cc (centésimas)."""
    if seconds < 0:
        seconds = 0.0
    total_cs = int(round(seconds * 100))
    cs = total_cs % 100
    total_s = total_cs // 100
    s = total_s % 60
    m = (total_s // 60) % 60
    h = total_s // 3600
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"
