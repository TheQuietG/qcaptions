"""Burn-in del .ass sobre el video con ffmpeg.

Dos modos:
  - fast (default): h264_videotoolbox (encoder por hardware de Apple Silicon).
    Quema en segundos; calidad de sobra para TikTok, que recomprime todo.
  - archival: libx264 crf 18 preset slow (máxima calidad, mucho más lento).

Si videotoolbox falla (Mac vieja, ffmpeg sin soporte), cae solo a libx264.
"""

from __future__ import annotations

from pathlib import Path

from .transcribe import PipelineError, _run, find_ffmpeg


def burn(
    video: Path,
    ass: Path,
    out: Path,
    mode: str = "fast",
    preview_seconds: float | None = None,
) -> Path:
    """Quema los subtítulos .ass sobre el video. Audio copiado sin recodificar."""
    ffmpeg = find_ffmpeg(need_ass=True)
    ass_arg = _escape_filter_path(ass)

    base = [ffmpeg, "-y", "-i", str(video)]
    if preview_seconds is not None:
        base += ["-t", f"{preview_seconds:.3f}"]
    base += ["-vf", f"ass={ass_arg}"]
    tail = ["-pix_fmt", "yuv420p", "-c:a", "copy", "-movflags", "+faststart",
            str(out)]

    if mode == "archival":
        _run(base + ["-c:v", "libx264", "-crf", "18", "-preset", "slow"] + tail,
             "quemando subtítulos (libx264 archival)")
    else:
        # -q:v 65 en videotoolbox ≈ visualmente transparente para redes sociales
        try:
            _run(base + ["-c:v", "h264_videotoolbox", "-q:v", "65",
                         "-allow_sw", "1"] + tail,
                 "quemando subtítulos (videotoolbox)")
        except PipelineError:
            print("    (videotoolbox no disponible; usando libx264)")
            _run(base + ["-c:v", "libx264", "-crf", "18", "-preset", "medium"]
                 + tail,
                 "quemando subtítulos (libx264 fallback)")

    if not out.exists():
        raise PipelineError(f"ffmpeg no generó el video de salida: {out}")
    return out


def _escape_filter_path(path: Path) -> str:
    # En el grafo de filtros de ffmpeg hay que escapar ':' y '\'.
    s = str(path)
    s = s.replace("\\", "\\\\").replace(":", "\\:")
    return s
