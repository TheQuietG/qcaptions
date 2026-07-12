"""Burn-in del .ass sobre el video con ffmpeg.

Dos modos:
  - fast (default): h264_videotoolbox (encoder por hardware de Apple Silicon).
    Quema en segundos; calidad de sobra para TikTok, que recomprime todo.
  - archival: libx264 crf 18 preset slow (máxima calidad, mucho más lento).

Si videotoolbox falla (Mac vieja, ffmpeg sin soporte), cae solo a libx264.
"""

from __future__ import annotations

import re
import shutil
import tempfile
from pathlib import Path

from .transcribe import PipelineError, _run, find_ffmpeg

# Caracteres que pasan sin drama por los DOS niveles de parseo del -vf de
# ffmpeg (grafo y opción). Cualquier otro (coma, comilla, ':', '[', ...) se
# esquiva copiando el .ass a un temp con nombre seguro: el doble des-escape
# de ffmpeg es demasiado frágil para pelearlo con strings.
_SAFE_FILTER_PATH = re.compile(r"^[\w./ @-]+$")


def burn(
    video: Path,
    ass: Path,
    out: Path,
    mode: str = "fast",
    preview_seconds: float | None = None,
) -> Path:
    """Quema los subtítulos .ass sobre el video. Audio copiado sin recodificar."""
    ffmpeg = find_ffmpeg(need_ass=True)

    tmp_ass: Path | None = None
    if not _SAFE_FILTER_PATH.match(str(ass)):
        fd, name = tempfile.mkstemp(prefix="qcaptions_", suffix=".ass")
        import os

        os.close(fd)
        tmp_ass = Path(name)
        shutil.copyfile(ass, tmp_ass)
    try:
        return _burn(ffmpeg, video, tmp_ass or ass, out, mode, preview_seconds)
    finally:
        if tmp_ass:
            tmp_ass.unlink(missing_ok=True)


def _burn(
    ffmpeg: str,
    video: Path,
    ass: Path,
    out: Path,
    mode: str,
    preview_seconds: float | None,
) -> Path:
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
    # Para rutas "seguras" (ver _SAFE_FILTER_PATH) no hace falta escapar nada;
    # esto queda por si el temp dir del sistema trae algo exótico.
    s = str(path)
    s = s.replace("\\", "\\\\").replace(":", "\\:")
    return s
