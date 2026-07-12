"""Burn-in del .ass sobre el video con ffmpeg, preservando calidad."""

from __future__ import annotations

from pathlib import Path

from .transcribe import _run, find_ffmpeg


def burn(video: Path, ass: Path, out: Path, crf: int = 18, preset: str = "slow") -> Path:
    """Quema los subtítulos .ass sobre el video.

    - Video: libx264, crf 18, preset slow (alta calidad).
    - Audio: copiado sin recodificar.
    """
    ffmpeg = find_ffmpeg(need_ass=True)

    # El filtro ass necesita la ruta escapada (dos puntos, comas...).
    ass_arg = _escape_filter_path(ass)
    cmd = [
        ffmpeg, "-y",
        "-i", str(video),
        "-vf", f"ass={ass_arg}",
        "-c:v", "libx264",
        "-crf", str(crf),
        "-preset", preset,
        "-pix_fmt", "yuv420p",
        "-c:a", "copy",
        "-movflags", "+faststart",
        str(out),
    ]
    _run(cmd, "quemando subtítulos con ffmpeg")
    if not out.exists():
        raise PipelineError(f"ffmpeg no generó el video de salida: {out}")
    return out


def _escape_filter_path(path: Path) -> str:
    # En el grafo de filtros de ffmpeg hay que escapar ':' y '\'.
    s = str(path)
    s = s.replace("\\", "\\\\").replace(":", "\\:")
    return s
