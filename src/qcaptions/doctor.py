"""`qcaptions doctor` — diagnóstico del entorno y descarga de modelos.

Chequea cada dependencia y, si falta, imprime el comando exacto para
instalarla. Con --download-model baja el modelo a models/ mostrando progreso.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path

from .transcribe import _FFMPEG_CANDIDATES, _has_ass_filter

HF_BASE = "https://huggingface.co/ggerganov/whisper.cpp/resolve/main"

# Modelos recomendados (nombre -> nota)
KNOWN_MODELS = {
    "ggml-large-v3-turbo": "mejor calidad ES/EN (~1.5 GB) — default",
    "ggml-large-v3-turbo-q5_0": "turbo cuantizado (~550 MB), calidad casi igual",
    "ggml-medium": "más liviano (~1.5 GB), algo menos preciso",
    "ggml-small": "rápido (~470 MB), para pruebas",
}


def _models_dir() -> Path:
    return Path(__file__).resolve().parents[2] / "models"


def _check(ok: bool, label: str, hint: str = "") -> bool:
    mark = "✓" if ok else "✗"
    print(f"  {mark} {label}")
    if not ok and hint:
        print(f"      → {hint}")
    return ok


def run_doctor(model_name: str = "ggml-large-v3-turbo") -> int:
    """Corre todos los chequeos. Devuelve 0 si el entorno está completo."""
    print("qcaptions doctor — diagnóstico del entorno\n")
    all_ok = True

    # whisper.cpp
    whisper = next(
        (shutil.which(n) for n in ("whisper-cli", "whisper-cpp", "whisper")
         if shutil.which(n)),
        None,
    )
    all_ok &= _check(
        whisper is not None,
        f"whisper.cpp ({whisper or 'no encontrado'})",
        "brew install whisper-cpp",
    )

    # ffmpeg básico (audio)
    ffmpeg = shutil.which("ffmpeg")
    all_ok &= _check(
        ffmpeg is not None,
        f"ffmpeg ({ffmpeg or 'no encontrado'})",
        "brew install ffmpeg",
    )

    # ffmpeg con libass (burn-in)
    ass_ff = None
    candidates = ([ffmpeg] if ffmpeg else []) + [
        c for c in _FFMPEG_CANDIDATES if Path(c).exists()
    ]
    for c in candidates:
        if _has_ass_filter(c):
            ass_ff = c
            break
    all_ok &= _check(
        ass_ff is not None,
        f"ffmpeg con libass ({ass_ff or 'ninguno tiene el filtro ass'})",
        "brew install ffmpeg-full   # qcaptions lo detecta solo",
    )

    # Modelo
    model_path = _models_dir() / f"{model_name}.bin"
    all_ok &= _check(
        model_path.exists(),
        f"modelo {model_name} ({model_path if model_path.exists() else 'falta'})",
        f"qcaptions doctor --download-model {model_name}",
    )

    # Fuente Montserrat
    font_dirs = [Path.home() / "Library/Fonts", Path("/Library/Fonts")]
    has_font = any(
        p for d in font_dirs if d.exists() for p in d.glob("Montserrat*")
    )
    all_ok &= _check(
        has_font,
        "fuente Montserrat",
        "brew install --cask font-montserrat  (sin ella libass usa la default)",
    )

    print()
    if all_ok:
        print("✓ Todo listo. Corré: qcaptions tu_video.mp4")
        return 0
    print("✗ Falta algo — corré los comandos indicados arriba.")
    return 1


def download_model(name: str) -> int:
    """Descarga models/<name>.bin desde HuggingFace con barra de progreso."""
    if not name.startswith("ggml-"):
        name = f"ggml-{name}"
    name = name.removesuffix(".bin")

    dest = _models_dir() / f"{name}.bin"
    if dest.exists():
        print(f"✓ El modelo ya existe: {dest}")
        return 0

    if name not in KNOWN_MODELS:
        print(f"Aviso: '{name}' no está en la lista conocida "
              f"({', '.join(KNOWN_MODELS)}); intento igual.")

    url = f"{HF_BASE}/{name}.bin?download=true"
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(".bin.part")
    print(f"Descargando {name}.bin → {dest.parent}/ ...")

    last_pct = -1

    def hook(blocks: int, block_size: int, total: int) -> None:
        nonlocal last_pct
        if total <= 0:
            return
        pct = min(100, blocks * block_size * 100 // total)
        if pct != last_pct and pct % 5 == 0:
            mb = blocks * block_size / 1e6
            sys.stdout.write(f"\r  {pct:3d}%  ({mb:,.0f} MB)")
            sys.stdout.flush()
            last_pct = pct

    try:
        urllib.request.urlretrieve(url, tmp, reporthook=hook)
    except Exception as exc:
        tmp.unlink(missing_ok=True)
        print(f"\n✗ Falló la descarga: {exc}")
        return 1
    tmp.rename(dest)
    print(f"\n✓ Listo: {dest} ({dest.stat().st_size / 1e6:,.0f} MB)")
    return 0


def main(argv: list[str]) -> int:
    """Entrada del subcomando: qcaptions doctor [--download-model NOMBRE]."""
    import argparse

    p = argparse.ArgumentParser(
        prog="qcaptions doctor",
        description="Diagnostica el entorno de qcaptions y descarga modelos.",
    )
    p.add_argument(
        "--download-model",
        nargs="?",
        const="ggml-large-v3-turbo",
        default=None,
        metavar="NOMBRE",
        help="Descarga un modelo a models/ (default: ggml-large-v3-turbo). "
             f"Conocidos: {', '.join(KNOWN_MODELS)}.",
    )
    p.add_argument(
        "--model",
        default="ggml-large-v3-turbo",
        help="Modelo cuya presencia verificar (default: ggml-large-v3-turbo).",
    )
    args = p.parse_args(argv)

    if args.download_model:
        rc = download_model(args.download_model)
        if rc != 0:
            return rc
    return run_doctor(args.model)
