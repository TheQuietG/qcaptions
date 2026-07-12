#!/usr/bin/env python3
"""Validación end-to-end reproducible de qcaptions.

Pensado para correr en cualquier sesión (o con cualquier modelo de Claude) y
confirmar que el pipeline sigue sano tras un cambio. NO necesita pytest.

Qué hace:
  1. Genera (si falta) un video de prueba: voz `say -v Mónica` + color sólido.
  2. Corre el pipeline completo (qcaptions vía módulo, sin depender del PATH).
  3. Verifica que los timestamps del .ass coinciden con words.json.
  4. Extrae frames y COMPRUEBA POR PÍXELES que la palabra activa es dorada
     y que las demás están blancas (no confía en el ojo).
  5. Corre los tests puros de tests/test_pipeline.py.

Uso:
    python3 scripts/validate.py [--model ggml-medium]

Sale con código 0 si todo pasa, 1 si algo falla.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
SAMPLES = ROOT / "samples"
sys.path.insert(0, str(SRC))

FF_FULL_CANDIDATES = [
    "/opt/homebrew/opt/ffmpeg-full/bin/ffmpeg",
    "/usr/local/opt/ffmpeg-full/bin/ffmpeg",
]

FRASE = (
    "Hola, en este video de Data Quimbaya te muestro cómo automatizar "
    "con n8n, Claude y el protocolo MCP para tu workflow de TikTok."
)


def _ffmpeg_full() -> str:
    for c in FF_FULL_CANDIDATES:
        if Path(c).exists():
            return c
    return "ffmpeg"


def _run(cmd: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True
    )


def ensure_test_video(video: Path) -> None:
    if video.exists():
        return
    SAMPLES.mkdir(exist_ok=True)
    aiff = SAMPLES / "voz.aiff"
    r = _run(["say", "-v", "Mónica", "-o", str(aiff), FRASE])
    if r.returncode != 0:
        raise SystemExit(
            "No se pudo generar la voz con `say -v Mónica`. "
            "Instalá la voz Mónica en Ajustes > Accesibilidad > Contenido hablado."
        )
    ff = _ffmpeg_full()
    _run(
        [ff, "-y", "-f", "lavfi", "-i", "color=c=0x0B1E3B:s=1080x1920:d=7.1:r=30",
         "-i", str(aiff), "-c:v", "libx264", "-pix_fmt", "yuv420p",
         "-c:a", "aac", "-shortest", str(video)]
    )


def run_pipeline(video: Path, model: str) -> tuple[Path, Path, Path]:
    from qcaptions.cli import main as qc_main

    rc = qc_main([str(video), "--model", model])
    if rc != 0:
        raise SystemExit("El pipeline qcaptions devolvió error.")
    stem = video.with_suffix("")
    return (
        Path(f"{stem}.words.json"),
        Path(f"{stem}.subs.ass"),
        Path(f"{stem}_captioned.mp4"),
    )


def _ts(t: str) -> float:
    h, m, rest = t.split(":")
    s, cs = rest.split(".")
    return int(h) * 3600 + int(m) * 60 + int(s) + int(cs) / 100


def check_coherence(words_json: Path, ass: Path) -> None:
    words = json.loads(words_json.read_text(encoding="utf-8"))
    dlg = [l for l in ass.read_text(encoding="utf-8").splitlines()
           if l.startswith("Dialogue")]
    wi = 0
    for line in dlg:
        f = line.split(",", 9)
        start, end, text = _ts(f[1]), _ts(f[2]), f[9]
        # Cada palabra es un bloque que arranca con {\1c...}; el pop inicial
        # ({\fscx...}) no cuenta. Una corrección puede meter espacios dentro de
        # una palabra (ej "Data Quimbaya"), por eso NO partimos por espacios.
        n_words = len(re.findall(r"\{\\1c", text))
        grp = words[wi:wi + n_words]
        assert grp, f"sin palabras para el caption: {line}"
        assert abs(start - grp[0]["start"]) <= 0.011, f"start desalineado: {line}"
        assert abs(end - grp[-1]["end"]) <= 0.011, f"end desalineado: {line}"
        wi += n_words
    print(f"  ✓ Coherencia .ass<->words.json ({len(words)} palabras, "
          f"{len(dlg)} captions)")


def _gold_px(rgb: bytes) -> int:
    return sum(
        1
        for i in range(0, len(rgb), 3)
        if rgb[i] > 150 and rgb[i + 1] > 110 and rgb[i + 2] < 110
        and (rgb[i] - rgb[i + 2]) > 90 and rgb[i + 1] < rgb[i]
    )


def check_gold_pixels(words_json: Path, captioned: Path) -> None:
    """Para cada caption toma un instante en medio de su PRIMERA y su ÚLTIMA
    palabra y verifica que hay píxeles dorados (la palabra activa se resalta).
    """
    ff = _ffmpeg_full()
    words = json.loads(words_json.read_text(encoding="utf-8"))
    tmp = ROOT / ".validate_tmp"
    tmp.mkdir(exist_ok=True)

    # Probamos algunos instantes distribuidos, en el medio de una palabra.
    checked = 0
    for idx, w in enumerate(words):
        if idx % 5 != 0:  # muestreo: cada 5 palabras
            continue
        mid = (w["start"] + w["end"]) / 2
        png = tmp / f"f_{idx}.png"
        _run([ff, "-y", "-i", str(captioned), "-ss", f"{mid:.3f}",
              "-frames:v", "1", str(png)])
        raw = _run([ff, "-y", "-i", str(png), "-f", "rawvideo",
                    "-pix_fmt", "rgb24", str(tmp / "f.rgb")])
        rgb = (tmp / "f.rgb").read_bytes()
        g = _gold_px(rgb)
        assert g > 200, (
            f"En t={mid:.2f}s (palabra '{w['word']}') no hay dorado suficiente "
            f"(gold_px={g}). ¿Se rompió el highlight?"
        )
        checked += 1
    # limpieza
    for p in tmp.glob("*"):
        p.unlink()
    tmp.rmdir()
    print(f"  ✓ Highlight dorado por píxeles ({checked} instantes muestreados)")


def run_unit_tests() -> None:
    sys.path.insert(0, str(ROOT / "tests"))
    import test_pipeline as t  # noqa
    import inspect

    fns = [f for n, f in inspect.getmembers(t, inspect.isfunction)
           if n.startswith("test_")]
    for f in fns:
        f()
    print(f"  ✓ Tests unitarios ({len(fns)} funciones)")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--model", default="ggml-large-v3-turbo")
    args = ap.parse_args()

    video = SAMPLES / "test_input.mp4"
    print("qcaptions — validación end-to-end\n")
    print("1. Preparando video de prueba ...")
    ensure_test_video(video)
    print("2. Corriendo pipeline ...")
    words_json, ass, captioned = run_pipeline(video, args.model)
    print("3. Verificando ...")
    check_coherence(words_json, ass)
    check_gold_pixels(words_json, captioned)
    run_unit_tests()
    print("\n✓ TODO OK")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except AssertionError as exc:
        print(f"\n✗ FALLO: {exc}")
        raise SystemExit(1)
