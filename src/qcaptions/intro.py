"""Logo animado al inicio del video (branding).

Se composita en el MISMO pase de encode que los captions (un solo re-encode).
Animación: fade-in con deslizamiento suave hacia arriba, hold, fade-out.
Todo con filtros nativos de ffmpeg (overlay + fade alpha + expresión en y).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .transcribe import PipelineError


@dataclass
class IntroSpec:
    logo: Path
    start: float = 0.3       # cuándo aparece (s)
    duration: float = 2.2    # cuánto dura visible en total (s)
    fade_in: float = 0.4
    fade_out: float = 0.5
    width_frac: float = 0.45  # ancho del logo como fracción del ancho del video
    y_frac: float = 0.20      # posición vertical del centro (fracción de altura)

    @property
    def end(self) -> float:
        return self.start + self.duration


def from_config(cfg: dict, override_logo: Path | None = None) -> IntroSpec | None:
    """Construye el IntroSpec desde la tabla [intro] de la config.

    override_logo (flag --intro) gana sobre la config. Devuelve None si no
    hay logo configurado.
    """
    logo = override_logo or (Path(cfg["logo"]).expanduser() if cfg.get("logo") else None)
    if logo is None:
        return None
    if not logo.exists():
        raise PipelineError(f"No existe el logo del intro: {logo}")
    spec = IntroSpec(logo=logo)
    for key in ("start", "duration", "fade_in", "fade_out", "width_frac", "y_frac"):
        if key in cfg:
            setattr(spec, key, float(cfg[key]))
    return spec


def build_filter(spec: IntroSpec, video_w: int, video_h: int, ass_arg: str) -> str:
    """Arma el -filter_complex: logo animado + captions en un solo grafo.

    Entradas esperadas: [0:v] video, [1:v] logo (con -loop 1 -t <end+1>).
    Salida: [vout].
    """
    logo_w = max(2, round(video_w * spec.width_frac))
    rest_y = round(video_h * spec.y_frac)
    fade_out_st = spec.end - spec.fade_out
    # y: arranca 40px abajo y sube con easing exponencial hasta reposar.
    y_expr = f"{rest_y}+40*exp(-6*(t-{spec.start}))"
    return (
        f"[1:v]format=rgba,scale={logo_w}:-1,"
        f"fade=t=in:st={spec.start}:d={spec.fade_in}:alpha=1,"
        f"fade=t=out:st={fade_out_st:.3f}:d={spec.fade_out}:alpha=1[lg];"
        f"[0:v][lg]overlay=x=(W-w)/2:y='{y_expr}'"
        f":enable='between(t,{spec.start},{spec.end})'[vb];"
        f"[vb]ass={ass_arg}[vout]"
    )
