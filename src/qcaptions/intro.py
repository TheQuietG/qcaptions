"""Logo animado al inicio del video (branding).

Dos modos, ambos compositados en el MISMO pase de encode que los captions:

- overlay (default): el logo aparece sobre el video con fade + deslizamiento.
- card: el video arranca con una pantalla NEGRA donde el logo se "esparce"
  desde el centro (revelado expansivo estilo circuito, borde difuso) y luego
  hace crossfade al video real. Los captions y el audio se corren
  automáticamente para mantener el sync.

La animación vive en build_filter (overlay) y build_card_filter (card) —
son grafos de filtros de ffmpeg puros, pensados para ser editables
(ver README: "Personalizar la animación").
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from .transcribe import PipelineError

# Crossfade card -> video (s). El video (y sus captions/audio) empieza en
# duration - XFADE.
XFADE = 0.5


@dataclass
class IntroSpec:
    logo: Path                # imagen que consume ffmpeg (PNG)
    source: Path | None = None  # archivo original del usuario (p.ej. el .svg)
    mode: str = "overlay"    # "overlay" | "card"
    start: float = 0.3       # overlay: cuándo aparece (s)
    duration: float = 2.2    # overlay: tiempo visible / card: duración total
    fade_in: float = 0.4
    fade_out: float = 0.5
    width_frac: float = 0.45  # ancho del logo como fracción del ancho del video
    y_frac: float = 0.20      # overlay: posición vertical (fracción de altura)
    # --- solo modo card ---
    bg: str = "#000000"       # color de fondo de la card
    reveal_start: float = 0.25    # cuándo empieza a esparcirse (s)
    reveal_duration: float = 1.3  # cuánto tarda el esparcimiento (s)
    feather: int = 60             # borde difuso del frente de expansión (px)
    glow: bool = True             # halo suave detrás del logo

    @property
    def end(self) -> float:
        return self.start + self.duration

    @property
    def shift(self) -> float:
        """Cuánto se corre el contenido del video (captions + audio).

        Solo el modo card desplaza; el overlay va sobre el video sin moverlo.
        """
        if self.mode == "card":
            return max(0.0, self.duration - XFADE)
        return 0.0

    @property
    def display_name(self) -> str:
        return (self.source or self.logo).name


def from_config(cfg: dict, override_logo: Path | None = None) -> IntroSpec | None:
    """Construye el IntroSpec desde la tabla [intro] de la config.

    override_logo (flag --intro/--logo) gana sobre la config. Devuelve None
    si no hay logo configurado. Un .svg se rasteriza automáticamente a PNG.
    """
    logo = override_logo or (Path(cfg["logo"]).expanduser() if cfg.get("logo") else None)
    if logo is None:
        return None
    if not logo.exists():
        raise PipelineError(f"No existe el logo del intro: {logo}")
    source = logo
    if logo.suffix.lower() == ".svg":
        logo = _rasterize_svg(logo)
    spec = IntroSpec(logo=logo, source=source)

    mode = str(cfg.get("mode", "overlay")).strip().lower()
    if mode not in ("overlay", "card"):
        raise PipelineError(
            f"[intro] mode inválido: '{mode}' (opciones: overlay, card)."
        )
    spec.mode = mode
    # Defaults distintos por modo (si el usuario no los fija).
    if mode == "card":
        spec.duration = 2.8
        spec.width_frac = 0.55

    for key in ("start", "duration", "fade_in", "fade_out", "width_frac",
                "y_frac", "reveal_start", "reveal_duration"):
        if key in cfg:
            setattr(spec, key, float(cfg[key]))
    if "feather" in cfg:
        spec.feather = int(cfg["feather"])
    if "glow" in cfg:
        spec.glow = bool(cfg["glow"])
    if "bg" in cfg:
        bg = str(cfg["bg"]).strip()
        if not re.fullmatch(r"#?[0-9a-fA-F]{6}", bg):
            raise PipelineError(
                f"[intro] bg inválido: '{bg}' (formato: #RRGGBB)."
            )
        spec.bg = bg if bg.startswith("#") else f"#{bg}"
    return spec


def _rasterize_svg(svg: Path) -> Path:
    """Convierte un SVG a PNG temporal con transparencia.

    ffmpeg no decodifica SVG, así que rasterizamos antes: rsvg-convert si
    está (mejor calidad de alpha), Quick Look (qlmanage, nativo de macOS)
    como fallback. El PNG temporal se borra al salir del proceso.
    """
    import atexit
    import os
    import shutil
    import subprocess
    import tempfile

    fd, name = tempfile.mkstemp(prefix="qcaptions_logo_", suffix=".png")
    os.close(fd)
    out = Path(name)
    atexit.register(lambda: out.unlink(missing_ok=True))

    rsvg = shutil.which("rsvg-convert")
    if rsvg:
        r = subprocess.run(
            [rsvg, "-w", "1200", "--keep-aspect-ratio", "-o", str(out), str(svg)],
            capture_output=True,
        )
        if r.returncode == 0 and out.stat().st_size > 0:
            return out

    qlmanage = shutil.which("qlmanage")
    if qlmanage:
        with tempfile.TemporaryDirectory() as d:
            r = subprocess.run(
                [qlmanage, "-t", "-s", "1200", "-o", d, str(svg)],
                capture_output=True,
            )
            produced = Path(d) / f"{svg.name}.png"
            if r.returncode == 0 and produced.exists():
                shutil.copyfile(produced, out)
                return out

    raise PipelineError(
        f"No pude rasterizar el SVG: {svg}\n"
        "Instalá rsvg-convert (brew install librsvg) o convertí el logo a PNG."
    )


def build_card_filter(
    spec: IntroSpec, video_w: int, video_h: int, fps: float, ass_arg: str
) -> str:
    """Grafo del modo card: negro -> logo esparciéndose -> crossfade al video.

    El "esparcirse como circuito" es un revelado expansivo con distancia
    Manhattan (rombo, ángulos rectos — lectura tech) y borde difuso, animado
    por frame (N/fps) multiplicando el alpha original del logo.

    Entradas: [0:v]+[0:a] video, [1:v] logo (con -loop 1). Salidas: [vout], [aout].
    El audio se retrasa spec.shift para quedar en sync tras la card.
    """
    fps_i = max(1, round(fps))
    logo_w = max(2, round(video_w * spec.width_frac))
    t0 = spec.reveal_start
    speed = logo_w / spec.reveal_duration  # px de radio Manhattan por segundo
    bg = f"0x{spec.bg.lstrip('#')}"
    # alpha final = alpha del logo * frente de expansión (0..1 con feather)
    a_expr = (
        f"alpha(X,Y)*clip(((N/{fps_i}-{t0})*{speed}"
        f"-(abs(X-W/2)+abs(Y-H/2)))/{spec.feather},0,1)"
    )
    delay_ms = int(round(spec.shift * 1000))

    graph = (
        f"color={bg}:s={video_w}x{video_h}:r={fps_i}:d={spec.duration:.3f},"
        f"format=yuv420p,setsar=1[bg];"
        f"[1:v]fps={fps_i},format=gbrap,scale={logo_w}:-1,"
        f"geq=r='r(X,Y)':g='g(X,Y)':b='b(X,Y)':a='{a_expr}'[lg];"
    )
    if spec.glow:
        # Halo: copia difuminada del logo (ya revelado) debajo del nítido.
        graph += (
            f"[lg]split[lga][lgb];"
            f"[lgb]gblur=sigma=28[glow];"
            f"[bg][glow]overlay=x=(W-w)/2:y=(H-h)/2[b1];"
            f"[b1][lga]overlay=x=(W-w)/2:y=(H-h)/2[card];"
        )
    else:
        graph += f"[bg][lg]overlay=x=(W-w)/2:y=(H-h)/2[card];"
    graph += (
        f"[0:v]fps={fps_i},format=yuv420p,setsar=1[v0];"
        f"[card][v0]xfade=transition=fade:duration={XFADE}:offset={spec.shift:.3f}[vx];"
        f"[vx]ass={ass_arg}[vout];"
        f"[0:a]adelay={delay_ms}:all=1[aout]"
    )
    return graph


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
