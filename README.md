# qcaptions — Quimbaya Captions

Subtítulos animados estilo CapCut, **100% locales** en tu Mac (Apple Silicon),
sin APIs de pago. Transcribe con `whisper.cpp` (Metal), genera un `.ass` con
karaoke palabra-por-palabra (branding Data Quimbaya) y lo quema con `ffmpeg`.

Un comando: `qcaptions video.mp4` → `video_captioned.mp4`.

![ejemplo](docs/ejemplo.png)

## Instalación con Homebrew (recomendada)

```bash
brew tap TheQuietG/tap
brew install qcaptions
qcaptions doctor --download-model   # baja el modelo (~1.5 GB) y verifica todo
brew install --cask font-montserrat # fuente del estilo (opcional pero recomendada)
```

En modo instalado, los modelos viven en `~/.qcaptions/models/` y tu config en
`~/.config/qcaptions/config.toml` (override total con la env `QCAPTIONS_HOME`).

## Setup desde el código (desarrollo)

```bash
# 1. Motor de transcripción con soporte Metal
brew install whisper-cpp

# 2. ffmpeg CON libass (el 'ffmpeg' normal de brew NO trae libass).
#    qcaptions detecta ffmpeg-full automáticamente para el burn-in.
brew install ffmpeg          # para extraer audio / uso general
brew install ffmpeg-full     # trae libass (necesario para quemar el .ass)

# 3. Fuente del branding (Montserrat ExtraBold)
brew install --cask font-montserrat

# 4. Instalar el CLI en el PATH
brew install pipx && pipx ensurepath
pipx install --editable .

# 5. Descargar el modelo y verificar que todo esté listo
qcaptions doctor --download-model     # baja ggml-large-v3-turbo (~1.5 GB)
```

`qcaptions doctor` diagnostica el entorno completo (whisper, ffmpeg, libass,
modelo, fuente) y te dice el comando exacto para arreglar lo que falte.

¿Poco espacio? El modelo cuantizado rinde casi igual y pesa un tercio (547 MB
vs 1.5 GB). Descargalo y fijalo como tu default en la config:

```bash
qcaptions doctor --download-model ggml-large-v3-turbo-q5_0
```

```toml
# ~/.config/qcaptions/config.toml
[settings]
model = "ggml-large-v3-turbo-q5_0"
```

(También podés pasarlo por corrida con `--model`; el flag pisa a la config.)

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

### Iterar rápido

- **Cache**: la transcripción (`.whisper.json`) se conserva y se reusa mientras
  el video no cambie — re-correr para ajustar estilo o correcciones es
  instantáneo. `--force` re-transcribe.
- **`--preview 10`**: quema solo los primeros 10 s a `<video>_preview.mp4`.
- **`--open`**: abre el resultado en QuickTime al terminar.

### Calidad del burn

Por defecto se usa el encoder por hardware de Apple Silicon
(`h264_videotoolbox`): quema un video en segundos y la calidad sobra para
TikTok (que recomprime todo al subir). Para máxima calidad de archivo
(libx264 crf 18 preset slow, mucho más lento): `--archival`.

### Flags

| flag | efecto |
|---|---|
| `--model NOMBRE`      | modelo whisper (default `ggml-large-v3-turbo`) |
| `--max-words N`       | máx. palabras por caption (default 4) |
| `--max-duration S`    | máx. segundos por caption (default 1.8) |
| `--no-uppercase`      | no pasar el texto a MAYÚSCULAS |
| `--no-pop`            | desactivar el "pop" de entrada |
| `--font "..."`        | fuente (default `Montserrat ExtraBold`) |
| `--fontsize N`        | tamaño (default 90 en 1080p, se escala a la resolución real) |
| `--margin-v N`        | margen inferior (default 600 en 1080×1920, se escala) |
| `--dry-run`           | genera `.words.json` y `.ass` **sin** quemar el video |
| `--preview SEG`       | quema solo los primeros SEG segundos (iteración rápida) |
| `--archival`          | burn libx264 crf 18 slow (máxima calidad, lento) |
| `--force`             | ignora la transcripción cacheada y re-transcribe |
| `--open`              | abre el video final al terminar |
| `--from-ass FILE.ass` | salta transcripción y quema un `.ass` existente |
| `--out FILE.mp4`      | ruta del video final |

El video no tiene que ser 1080×1920: la resolución se detecta con ffprobe y
el estilo se escala proporcionalmente (probado con 4K vertical).

## Logo animado al inicio (`[intro]`)

Poné tu logo (PNG con transparencia) al arranque de cada video: aparece con
fade + deslizamiento suave, sostiene ~2 s y desaparece. Se composita en el
mismo pase de encode que los captions (sin doble re-encode).

```toml
# ~/.config/qcaptions/config.toml
[intro]
logo = "~/branding/logo.png"
duration = 2.2      # segundos visible (opcional)
width_frac = 0.45   # ancho relativo al video (opcional)
y_frac = 0.20       # posición vertical (opcional)
```

Con eso configurado, se aplica a todos tus videos automáticamente.
Por corrida: `--logo logo.png` (alias: `--intro`; pisa la config) o
`--no-intro` (lo salta).

También acepta **SVG** directamente — se rasteriza solo (con `rsvg-convert`
si está instalado, o Quick Look de macOS como fallback):

```bash
qcaptions video.mp4 --logo logo.svg
```

## Correcciones de texto (`config.toml`)

whisper a veces oye mal términos técnicos. Hay varios niveles que se mergean
(el de más abajo pisa al de más arriba):

1. Defaults empaquetados (`src/qcaptions/default_corrections.toml`)
2. `<data>/config.toml` (raíz del repo en desarrollo, `~/.qcaptions/` instalado)
3. `~/.config/qcaptions/config.toml` (tus correcciones personales)
4. `--config otro.toml` (por corrida)

Formato:

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

## Tests y validación

```bash
python3 -m pytest tests/       # tests puros (o: pip install pytest)
python3 scripts/validate.py    # validación end-to-end reproducible:
                               # genera un video con `say -v Mónica`, corre el
                               # pipeline, chequea coherencia y verifica por
                               # píxeles que la palabra activa sale dorada.
```

## Cómo funciona (pipeline)

1. `ffmpeg` extrae el audio a WAV 16 kHz mono.
2. `whisper.cpp` (`-ml 1 -sow -oj`) transcribe con timestamps por palabra.
3. Se normaliza a `words.json` y se aplican las correcciones de `config.toml`.
4. Se agrupan las palabras en captions y se genera `subs.ass` con karaoke.
5. `ffmpeg` (con libass) quema el `.ass`: `crf 18`, `preset slow`, audio copiado.
