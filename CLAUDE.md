# CLAUDE.md — contexto del proyecto qcaptions

Herramienta CLI **local** que pone subtítulos animados estilo CapCut sobre
videos verticales de TikTok de **Data Quimbaya** (`#retodataquimbaya`).
Todo corre en la Mac (Apple Silicon) sin APIs de pago.

## Objetivo del usuario
Un solo comando `qcaptions video.mp4` que transcribe, genera un `.ass` con
karaoke palabra-por-palabra (branding Data Quimbaya) y lo quema en el video.

## Arquitectura
```
src/qcaptions/
  cli.py          # argparse + orquestación del pipeline (punto de entrada)
  transcribe.py   # extract_audio + whisper.cpp + parse_words + find_ffmpeg
  corrections.py  # diccionario config.toml (reemplazos, colapso multi-palabra)
  grouping.py     # agrupa palabras en captions (max_words / max_duration / pausas)
  assgen.py       # genera el .ass (estilo + karaoke con \t por palabra)
  burn.py         # burn-in con ffmpeg (crf 18, preset slow, audio copy)
config.toml       # correcciones por defecto (n8n, Claude, MCP, Quimbaya...)
models/           # ggml-*.bin (NO en git; ~1.5 GB)
samples/          # material de prueba (NO en git)
tests/            # tests de las piezas puras (corrections, grouping, assgen)
```

## Pipeline
1. `ffmpeg` → WAV 16 kHz mono PCM.
2. `whisper-cli -m modelo -l es -ml 1 -sow -oj -of <pre>` → JSON word-level.
   whisper **añade** `.json` al prefijo `-of` (ojo con `Path.with_suffix`).
3. `parse_words`: `transcription[].{text, offsets.from/to}` (ms) → `words.json`.
4. `apply_corrections`.
5. `group_words` → captions.
6. `build_ass` → `subs.ass`.
7. `burn`.

## Decisiones / gotchas importantes
- **ffmpeg de Homebrew NO trae libass.** Hay que instalar `ffmpeg-full`
  (keg-only). `find_ffmpeg(need_ass=True)` prueba el del PATH y cae a
  `/opt/homebrew/opt/ffmpeg-full/bin/ffmpeg`. Se puede forzar con la env
  `QCAPTIONS_FFMPEG`.
- **Karaoke de una sola palabra activa** (no `\k` acumulativo): cada palabra
  arranca blanca, se vuelve dorada en su ventana con `\t(ini,ini,\1c&gold&)` y
  vuelve a blanca con `\t(fin,fin,\1c&white&)`.
- **`\t(0,0,...)` NO aplica en libass.** Por eso, si una palabra ya está activa
  al inicio del caption (`rel_start==0`, típicamente la primera), se pinta el
  color base **dorado** directamente en vez de usar `\t(0,0)`. Ver
  `assgen._dialogue`. (Regresión cubierta por `test_ass_first_word_starts_gold`.)
- **Formato ASS de `[Events]`** debe declarar `Name` y `MarginV`; si faltan,
  libass mete basura (`0,,`) al principio del texto.
- **Dorado `#D4AF37`** en ASS es `&H0037AFD4` (orden BGR + alpha).
- **Colores ASS** = `&HAABBGGRR`. Blanco `&H00FFFFFF`, negro `&H00000000`.
- **Posición**: Alignment 2 (abajo-centro) + `MarginV=600` → ~68% de altura,
  arriba de la UI de TikTok.
- Sin dependencias Python externas: solo stdlib (`tomllib`, `argparse`).

## Validación hecha
Pipeline probado end-to-end con audio TTS (`say -v Mónica`) sobre un video de
color sólido. Verificado por muestreo de píxeles que la palabra activa es
dorada y las demás blancas, y que los timestamps del `.ass` coinciden con
`words.json`. Ver `tests/` para regresiones de las piezas puras.

## Cómo correr los tests
```bash
python3 -m pytest tests/     # o correr las funciones test_* a mano (sin pytest)
```
