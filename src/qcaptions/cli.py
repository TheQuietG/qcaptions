"""CLI de qcaptions — un solo comando corre todo el pipeline."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__
from .assgen import AssStyle, build_ass
from .burn import burn
from .corrections import apply_corrections, load_corrections
from .grouping import group_words
from .transcribe import (
    PipelineError,
    extract_audio,
    parse_words,
    transcribe,
)

DEFAULT_MODEL = "ggml-large-v3-turbo"


def _project_root() -> Path:
    # <root>/src/qcaptions/cli.py -> <root>
    return Path(__file__).resolve().parents[2]


def _resolve_model(name_or_path: str) -> Path:
    p = Path(name_or_path)
    if p.exists():
        return p
    # nombre suelto -> models/<name>.bin dentro del proyecto
    stem = name_or_path
    if not stem.startswith("ggml-"):
        stem = f"ggml-{stem}"
    if not stem.endswith(".bin"):
        stem = f"{stem}.bin"
    return _project_root() / "models" / stem


def _default_config() -> Path:
    return _project_root() / "config.toml"


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="qcaptions",
        description="Genera subtítulos animados estilo CapCut (Data Quimbaya) "
        "100% local sobre un video vertical.",
    )
    p.add_argument("video", type=Path, help="Video de entrada (.mp4 vertical).")
    p.add_argument(
        "--model",
        default=DEFAULT_MODEL,
        help=f"Modelo whisper.cpp (nombre o ruta). Default: {DEFAULT_MODEL}.",
    )
    p.add_argument(
        "--max-words",
        type=int,
        default=4,
        help="Máximo de palabras por caption (default: 4).",
    )
    p.add_argument(
        "--max-duration",
        type=float,
        default=1.8,
        help="Duración máxima de un caption en segundos (default: 1.8).",
    )
    p.add_argument(
        "--no-uppercase",
        action="store_true",
        help="No convertir el texto a MAYÚSCULAS.",
    )
    p.add_argument(
        "--no-pop",
        action="store_true",
        help="Desactiva el efecto pop de entrada.",
    )
    p.add_argument(
        "--font",
        default="Montserrat ExtraBold",
        help="Fuente del subtítulo (default: 'Montserrat ExtraBold').",
    )
    p.add_argument(
        "--fontsize", type=int, default=90, help="Tamaño de fuente (default: 90)."
    )
    p.add_argument(
        "--margin-v",
        type=int,
        default=600,
        help="Margen vertical desde abajo (default: 600, ~68%% de altura).",
    )
    p.add_argument(
        "--config",
        type=Path,
        default=None,
        help="Ruta a config.toml (default: config.toml del proyecto).",
    )
    p.add_argument(
        "--language", default="es", help="Idioma de la transcripción (default: es)."
    )
    p.add_argument(
        "--from-ass",
        type=Path,
        default=None,
        help="Salta transcripción y quema un .ass ya existente (editado a mano).",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Genera words.json y subs.ass pero NO quema el video.",
    )
    p.add_argument(
        "--out",
        type=Path,
        default=None,
        help="Ruta del video final (default: <video>_captioned.mp4).",
    )
    p.add_argument("--version", action="version", version=f"qcaptions {__version__}")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return _run(args)
    except PipelineError as exc:
        sys.stderr.write(f"\n✗ {exc}\n")
        return 1


def _run(args: argparse.Namespace) -> int:
    video: Path = args.video
    if not video.exists():
        raise PipelineError(f"No existe el video de entrada: {video}")

    stem = video.with_suffix("")
    out_video = args.out or Path(f"{stem}_captioned.mp4")

    style = AssStyle(
        fontname=args.font,
        fontsize=args.fontsize,
        margin_v=args.margin_v,
        uppercase=not args.no_uppercase,
        pop=not args.no_pop,
    )

    # --- Ruta rápida: re-quemar un .ass editado a mano ---
    if args.from_ass:
        if not args.from_ass.exists():
            raise PipelineError(f"No existe el .ass indicado: {args.from_ass}")
        print(f"→ Quemando {args.from_ass.name} sobre {video.name} ...")
        burn(video, args.from_ass, out_video)
        print(f"✓ Listo: {out_video}")
        return 0

    words_json = Path(f"{stem}.words.json")
    ass_path = Path(f"{stem}.subs.ass")

    # 1-2. Audio
    wav = Path(f"{stem}.16k.wav")
    print(f"→ [1/5] Extrayendo audio 16kHz mono ...")
    extract_audio(video, wav)

    # 3. Transcripción word-level
    model = _resolve_model(args.model)
    print(f"→ [2/5] Transcribiendo con whisper.cpp ({model.name}) ...")
    raw_json = Path(f"{stem}.whisper.json")
    transcribe(wav, model, raw_json, language=args.language)

    # 4. Normalizar + correcciones
    print(f"→ [3/5] Normalizando palabras y aplicando correcciones ...")
    words = parse_words(raw_json)
    config = args.config or _default_config()
    rules = load_corrections(config)
    words = apply_corrections(words, rules)
    words_json.write_text(
        json.dumps(words, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"    {len(words)} palabras → {words_json.name}")

    # 5. Agrupar + generar .ass
    print(f"→ [4/5] Agrupando en captions y generando .ass ...")
    captions = group_words(
        words, max_words=args.max_words, max_duration=args.max_duration
    )
    ass = build_ass(captions, style)
    ass_path.write_text(ass, encoding="utf-8")
    print(f"    {len(captions)} captions → {ass_path.name}")

    # limpieza de intermedios de audio/whisper
    for tmp in (wav, raw_json):
        try:
            tmp.unlink()
        except OSError:
            pass

    if args.dry_run:
        print(f"✓ Dry-run: generados {words_json.name} y {ass_path.name} "
              f"(no se quemó el video).")
        return 0

    # 6. Burn-in
    print(f"→ [5/5] Quemando subtítulos (crf 18, preset slow) ...")
    burn(video, ass_path, out_video)
    print(f"\n✓ Listo: {out_video}")
    print(f"  Intermedios: {words_json.name}, {ass_path.name}")
    print(f"  Editá el .ass y re-quemá con: "
          f"qcaptions {video.name} --from-ass {ass_path.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
