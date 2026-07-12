"""Extracción de audio y transcripción con whisper.cpp (word-level timestamps)."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from functools import lru_cache
from pathlib import Path

# Homebrew instala 'ffmpeg' sin libass; 'ffmpeg-full' (keg-only) sí la trae.
_FFMPEG_CANDIDATES = (
    "/opt/homebrew/opt/ffmpeg-full/bin/ffmpeg",
    "/usr/local/opt/ffmpeg-full/bin/ffmpeg",
)


class PipelineError(RuntimeError):
    """Error recuperable del pipeline, con mensaje pensado para el usuario."""


def find_ffmpeg(need_ass: bool = False) -> str:
    """Localiza un ffmpeg. Si need_ass, exige uno con el filtro 'ass' (libass).

    Preferimos el del PATH; si no sirve para subtítulos, probamos ffmpeg-full.
    """
    candidates: list[str] = []
    env = os.environ.get("QCAPTIONS_FFMPEG") or os.environ.get("FFMPEG")
    if env:
        candidates.append(env)
    path_ff = shutil.which("ffmpeg")
    if path_ff:
        candidates.append(path_ff)
    candidates.extend(c for c in _FFMPEG_CANDIDATES if Path(c).exists())

    if not candidates:
        raise PipelineError(
            "No se encontró 'ffmpeg' en el PATH. Instálalo: brew install ffmpeg"
        )

    if not need_ass:
        return candidates[0]

    for ff in candidates:
        if _has_ass_filter(ff):
            return ff

    raise PipelineError(
        "El ffmpeg disponible no tiene soporte de subtítulos (libass), "
        "necesario para quemar el .ass.\n"
        "Instálalo con: brew install ffmpeg-full\n"
        "(qcaptions lo detecta automáticamente en /opt/homebrew/opt/ffmpeg-full)."
    )


@lru_cache(maxsize=8)
def _has_ass_filter(ffmpeg: str) -> bool:
    try:
        out = subprocess.run(
            [ffmpeg, "-hide_banner", "-filters"],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
        ).stdout
    except OSError:
        return False
    return any(line.split()[1:2] == ["ass"] for line in out.splitlines() if line.strip())


def extract_audio(video: Path, wav_out: Path) -> Path:
    """Extrae el audio a WAV mono 16kHz PCM s16 (lo que espera whisper.cpp)."""
    ffmpeg = find_ffmpeg(need_ass=False)
    wav_out.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        ffmpeg, "-y",
        "-i", str(video),
        "-vn",                 # sin video
        "-ac", "1",            # mono
        "-ar", "16000",        # 16 kHz
        "-c:a", "pcm_s16le",   # PCM 16-bit
        str(wav_out),
    ]
    _run(cmd, "extrayendo audio con ffmpeg")
    if not wav_out.exists():
        raise PipelineError(f"ffmpeg no generó el WAV esperado: {wav_out}")
    return wav_out


def transcribe(
    wav: Path,
    model: Path,
    json_out: Path,
    language: str = "es",
    whisper_bin: str | None = None,
) -> Path:
    """Transcribe el WAV con whisper.cpp forzando un token por segmento
    (``-ml 1 -sow``) para obtener timestamps a nivel de palabra en el JSON.

    Devuelve la ruta al JSON crudo de whisper.cpp (``<of>.json``).
    """
    binary = whisper_bin or _find_whisper()
    if not model.exists():
        raise PipelineError(
            f"No se encontró el modelo: {model}\n"
            f"Descárgalo con: qcaptions --download-model (o ver README)."
        )

    # whisper-cli AÑADE ".json" al prefijo pasado en -of.
    # Usamos un prefijo sin extensión para que el archivo final sea <stem>.json.
    out_prefix = json_out.with_suffix("")
    cmd = [
        binary,
        "-m", str(model),
        "-f", str(wav),
        "-l", language,
        "-ml", "1",          # max segment length = 1 token
        "-sow",              # split on word -> cada segmento es una palabra
        "-oj",               # output json
        "-of", str(out_prefix),
        "-np",               # no prints (silencioso salvo lo necesario)
    ]
    _run(cmd, "transcribiendo con whisper.cpp (puede tardar)")

    produced = Path(f"{out_prefix}.json")
    if not produced.exists():
        raise PipelineError(f"whisper.cpp no generó el JSON esperado: {produced}")
    return produced


def parse_words(whisper_json: Path) -> list[dict]:
    """Convierte el JSON crudo de whisper.cpp a una lista normalizada
    ``[{word, start, end}, ...]`` con tiempos en segundos (float).
    """
    data = json.loads(whisper_json.read_text(encoding="utf-8"))
    segments = data.get("transcription", [])
    words: list[dict] = []
    for seg in segments:
        text = (seg.get("text") or "").strip()
        if not text:
            continue
        offsets = seg.get("offsets") or {}
        start_ms = offsets.get("from")
        end_ms = offsets.get("to")
        if start_ms is None or end_ms is None:
            continue
        words.append(
            {
                "word": text,
                "start": round(start_ms / 1000.0, 3),
                "end": round(end_ms / 1000.0, 3),
            }
        )
    if not words:
        raise PipelineError(
            "La transcripción no produjo palabras. ¿El audio tiene voz? "
            f"Revisa {whisper_json}."
        )
    return words


def _find_whisper() -> str:
    for name in ("whisper-cli", "whisper-cpp", "whisper"):
        path = shutil.which(name)
        if path:
            return path
    raise PipelineError(
        "No se encontró whisper.cpp (whisper-cli / whisper-cpp). "
        "Instálalo con: brew install whisper-cpp"
    )


def _run(cmd: list[str], what: str) -> None:
    try:
        proc = subprocess.run(
            cmd,
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
    except FileNotFoundError as exc:  # pragma: no cover - _require ya cubre esto
        raise PipelineError(f"No se pudo ejecutar {cmd[0]}: {exc}") from exc
    if proc.returncode != 0:
        sys.stderr.write(proc.stdout or "")
        raise PipelineError(
            f"Falló al {what} (código {proc.returncode}). "
            f"Comando: {' '.join(cmd)}"
        )
