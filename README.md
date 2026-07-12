# qcaptions — Quimbaya Captions

Subtítulos animados estilo CapCut, **100% locales** en tu Mac (Apple Silicon),
sin APIs de pago. Transcribe con `whisper.cpp` (Metal), genera un `.ass` con
karaoke palabra-por-palabra (branding Data Quimbaya) y lo quema con `ffmpeg`.

Un comando: `qcaptions video.mp4` → `video_captioned.mp4`.

![ejemplo](docs/ejemplo.png)

## Setup (una vez)

```bash
# 1. Motor de transcripción con soporte Metal
brew install whisper-cpp

# 2. ffmpeg CON libass (el 'ffmpeg' normal de brew NO trae libass).
#    qcaptions detecta ffmpeg-full automáticamente para el burn-in.
brew install ffmpeg          # para extraer audio / uso general
brew install ffmpeg-full     # trae libass (necesario para quemar el .ass)

# 3. Fuente del branding (Montserrat ExtraBold)
brew install --cask font-montserrat

# 4. Modelo whisper (large-v3-turbo, ~1.5 GB) en models/
mkdir -p models
curl -L -o models/ggml-large-v3-turbo.bin \
  "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-large-v3-turbo.bin?download=true"

# 5. Instalar el CLI en el PATH
brew install pipx && pipx ensurepath
pipx install --editable .
```

Requisitos: Python 3.11+ (usa solo stdlib), macOS Apple Silicon.

## Uso

```bash
qcaptions video.mp4
```

Deja tres archivos junto al video:

| archivo | qué es |
|---|---|
| `video_captioned.mp4` | **el deliverable** (video con subtítulos quemados) |
| `video.words.json`    | palabras normalizadas `[{word,start,end}]` |
| `video.subs.ass`      | subtítulos con estilo karaoke (editable a mano) |

### Editar a mano y re-quemar

Si querés ajustar el `.ass` (texto, timing, posición) y volver a quemar sin
re-transcribir:

```bash
qcaptions video.mp4 --from-ass video.subs.ass
```

### Flags

| flag | efecto |
|---|---|
| `--model NOMBRE`      | modelo whisper (default `ggml-large-v3-turbo`) |
| `--max-words N`       | máx. palabras por caption (default 4) |
| `--max-duration S`    | máx. segundos por caption (default 1.8) |
| `--no-uppercase`      | no pasar el texto a MAYÚSCULAS |
| `--no-pop`            | desactivar el "pop" de entrada |
| `--font "..."`        | fuente (default `Montserrat ExtraBold`) |
| `--fontsize N`        | tamaño (default 90) |
| `--margin-v N`        | margen inferior en px (default 600, ~68% de altura) |
| `--dry-run`           | genera `.words.json` y `.ass` **sin** quemar el video |
| `--from-ass FILE.ass` | salta transcripción y quema un `.ass` existente |
| `--out FILE.mp4`      | ruta del video final |

## Correcciones de texto (`config.toml`)

whisper a veces oye mal términos técnicos. Editá `config.toml`:

```toml
[corrections]
"ene ocho ene" = "n8n"      # colapsa 3 palabras en 1 (no parte la sigla)
"quimballa"    = "Quimbaya"
"cloud"        = "Claude"
```

El match ignora mayúsculas y acentos. Un reemplazo multi-palabra colapsa las
palabras en una sola tomando el inicio de la primera y el fin de la última.

## Estilo

- 1080×1920, texto blanco, borde negro grueso, sin caja.
- Palabra activa resaltada en dorado `#D4AF37`; el resto en blanco.
- Anclado a ~68% de la altura (arriba de la UI de TikTok).
- Montserrat ExtraBold (fallback: la fuente por defecto de libass).

## Tests

```bash
python3 -m pytest tests/      # o: pip install pytest
```

## Cómo funciona (pipeline)

1. `ffmpeg` extrae el audio a WAV 16 kHz mono.
2. `whisper.cpp` (`-ml 1 -sow -oj`) transcribe con timestamps por palabra.
3. Se normaliza a `words.json` y se aplican las correcciones de `config.toml`.
4. Se agrupan las palabras en captions y se genera `subs.ass` con karaoke.
5. `ffmpeg` (con libass) quema el `.ass`: `crf 18`, `preset slow`, audio copiado.
