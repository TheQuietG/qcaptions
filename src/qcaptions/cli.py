"""CLI de qcaptions — un solo comando corre todo el pipeline.

Además: `qcaptions doctor [--download-model NOMBRE]` diagnostica el entorno.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

from . import __version__
from .assgen import AssStyle, build_ass, scale_style
from .burn import burn
from .corrections import (
    apply_corrections,
    load_corrections,
    load_settings,
    load_table,
)
from .grouping import group_words
from .intro import from_config as intro_from_config
from .paths import models_dir, user_config_paths
from .transcribe import (
    PipelineError,
    extract_audio,
    parse_words,
    probe_video,
    transcribe,
)

DEFAULT_MODEL = "ggml-large-v3-turbo"
DEFAULT_FONTSIZE = 90
DEFAULT_MARGIN_V = 600


def _resolve_model(name_or_path: str) -> Path:
    p = Path(name_or_path)
    if p.exists():
        return p
    # nombre suelto -> <data>/models/<name>.bin
    stem = name_or_path
    if not stem.startswith("ggml-"):
        stem = f"ggml-{stem}"
    if not stem.endswith(".bin"):
        stem = f"{stem}.bin"
    return models_dir() / stem


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="qcaptions",
        description="Genera subtítulos animados estilo CapCut (Data Quimbaya) "
        "100% local sobre un video vertical. "
        "Diagnóstico del entorno: qcaptions doctor",
    )
    p.add_argument("video", type=Path, help="Video de entrada (.mp4 vertical).")
    p.add_argument(
        "--model",
        default=None,
        help=f"Modelo whisper.cpp (nombre o ruta). Default: 'model' en "
        f"[settings] de la config, o {DEFAULT_MODEL}.",
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
        "--fontsize",
        type=int,
        default=None,
        help=f"Tamaño de fuente (default: {DEFAULT_FONTSIZE}, escalado a la "
        "resolución real del video).",
    )
    p.add_argument(
        "--margin-v",
        type=int,
        default=None,
        help=f"Margen vertical desde abajo (default: {DEFAULT_MARGIN_V} en "
        "1080x1920, escalado a la resolución real).",
    )
    p.add_argument(
        "--config",
        type=Path,
        default=None,
        help="config.toml extra (se mergea sobre el del proyecto y el de "
        "~/.config/qcaptions/config.toml).",
    )
    p.add_argument(
        "--language", default="es", help="Idioma de la transcripción (default: es)."
    )
    p.add_argument(
        "--intro",
        type=Path,
        default=None,
        metavar="LOGO",
        help="Logo animado al inicio (PNG, idealmente con transparencia). "
        "También configurable en [intro] de config.toml para aplicarlo "
        "siempre.",
    )
    p.add_argument(
        "--no-intro",
        action="store_true",
        help="No aplicar el intro aunque esté configurado en config.toml.",
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
        "--preview",
        type=float,
        default=None,
        metavar="SEG",
        help="Quema solo los primeros SEG segundos a <video>_preview.mp4 "
        "(rápido, para iterar sobre el estilo).",
    )
    p.add_argument(
        "--archival",
        action="store_true",
        help="Burn con libx264 crf 18 preset slow (máxima calidad, lento). "
        "Default: encoder por hardware (videotoolbox), calidad de sobra "
        "para TikTok y mucho más rápido.",
    )
    p.add_argument(
        "--force",
        action="store_true",
        help="Re-transcribe aunque exista una transcripción cacheada vigente.",
    )
    p.add_argument(
        "--open",
        action="store_true",
        dest="open_after",
        help="Abre el video final al terminar (QuickTime).",
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
    if argv is None:
        argv = sys.argv[1:]
    # Subcomando doctor (antes de argparse para no chocar con el posicional).
    if argv and argv[0] == "doctor":
        from .doctor import main as doctor_main

        return doctor_main(argv[1:])

    args = build_parser().parse_args(argv)
    try:
        return _run(args)
    except PipelineError as exc:
        sys.stderr.write(f"\n✗ {exc}\n")
        sys.stderr.write("  Diagnóstico del entorno: qcaptions doctor\n")
        return 1


def _run(args: argparse.Namespace) -> int:
    video: Path = args.video
    if not video.exists():
        raise PipelineError(f"No existe el video de entrada: {video}")

    stem = video.with_suffix("")
    if args.preview is not None:
        out_video = args.out or Path(f"{stem}_preview.mp4")
    else:
        out_video = args.out or Path(f"{stem}_captioned.mp4")
    burn_mode = "archival" if args.archival else "fast"
    if args.preview is not None:
        burn_mode = "fast"  # un preview nunca necesita archival

    # Estilo: diseñado sobre 1080x1920 y escalado a la resolución real.
    width, height = probe_video(video)
    style = scale_style(
        AssStyle(
            fontname=args.font,
            uppercase=not args.no_uppercase,
            pop=not args.no_pop,
        ),
        width,
        height,
    )
    # Overrides explícitos del usuario (sin re-escalar).
    if args.fontsize is not None:
        style.fontsize = args.fontsize
    if args.margin_v is not None:
        style.margin_v = args.margin_v
    if (width, height) != (1080, 1920):
        print(f"→ Video {width}x{height}: estilo escalado "
              f"(fontsize {style.fontsize}, marginV {style.margin_v}).")

    # Intro (logo animado): flag --intro > tabla [intro] de la config.
    intro = None
    if not args.no_intro:
        intro_cfg = load_table(user_config_paths(args.config), "intro")
        intro = intro_from_config(intro_cfg, override_logo=args.intro)
    if intro:
        print(f"→ Intro: {intro.logo.name} "
              f"({intro.start:g}s → {intro.end:g}s).")

    # --- Ruta rápida: re-quemar un .ass editado a mano ---
    if args.from_ass:
        if not args.from_ass.exists():
            raise PipelineError(f"No existe el .ass indicado: {args.from_ass}")
        print(f"→ Quemando {args.from_ass.name} sobre {video.name} ...")
        burn(video, args.from_ass, out_video, mode=burn_mode,
             preview_seconds=args.preview, intro=intro)
        return _finish(out_video, args)

    words_json = Path(f"{stem}.words.json")
    ass_path = Path(f"{stem}.subs.ass")
    raw_json = Path(f"{stem}.whisper.json")

    # 1-3. Audio + transcripción (con cache: el whisper.json se conserva y se
    # reusa si es más nuevo que el video; --force lo regenera).
    cache_ok = (
        not args.force
        and raw_json.exists()
        and raw_json.stat().st_mtime >= video.stat().st_mtime
    )
    if cache_ok:
        print(f"→ [1-2/5] Transcripción cacheada ({raw_json.name}; "
              f"--force para regenerar).")
    else:
        wav = Path(f"{stem}.16k.wav")
        print("→ [1/5] Extrayendo audio 16kHz mono ...")
        extract_audio(video, wav)
        settings = load_settings(user_config_paths(args.config))
        model_name = args.model or settings.get("model") or DEFAULT_MODEL
        model = _resolve_model(model_name)
        print(f"→ [2/5] Transcribiendo con whisper.cpp ({model.name}) ...")
        transcribe(wav, model, raw_json, language=args.language)
        try:
            wav.unlink()
        except OSError:
            pass

    # 4. Normalizar + correcciones (siempre se re-aplican: editar config.toml
    # y re-correr actualiza los subtítulos sin re-transcribir).
    print("→ [3/5] Normalizando palabras y aplicando correcciones ...")
    words = parse_words(raw_json)
    rules = load_corrections(user_config_paths(args.config))
    words = apply_corrections(words, rules)
    words_json.write_text(
        json.dumps(words, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"    {len(words)} palabras → {words_json.name}")

    # 5. Agrupar + generar .ass
    print("→ [4/5] Agrupando en captions y generando .ass ...")
    captions = group_words(
        words, max_words=args.max_words, max_duration=args.max_duration
    )
    ass = build_ass(captions, style)
    ass_path.write_text(ass, encoding="utf-8")
    print(f"    {len(captions)} captions → {ass_path.name}")

    if args.dry_run:
        print(f"✓ Dry-run: generados {words_json.name} y {ass_path.name} "
              f"(no se quemó el video).")
        return 0

    # 6. Burn-in
    if args.preview is not None:
        print(f"→ [5/5] Preview: quemando los primeros {args.preview:g}s ...")
    else:
        label = "libx264 archival" if burn_mode == "archival" else "videotoolbox"
        print(f"→ [5/5] Quemando subtítulos ({label}) ...")
    burn(video, ass_path, out_video, mode=burn_mode,
         preview_seconds=args.preview, intro=intro)

    print(f"  Intermedios: {words_json.name}, {ass_path.name}")
    print(f"  Editá el .ass y re-quemá con: "
          f"qcaptions {video.name} --from-ass {ass_path.name}")
    return _finish(out_video, args)


def _finish(out_video: Path, args: argparse.Namespace) -> int:
    print(f"\n✓ Listo: {out_video}")
    if args.open_after:
        subprocess.run(["open", str(out_video)], check=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
