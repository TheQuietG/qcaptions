# CLAUDE.md — contexto y handoff del proyecto qcaptions

Herramienta CLI **local** que pone subtítulos animados estilo CapCut sobre
videos verticales de TikTok de **Data Quimbaya** (`#retodataquimbaya`).
Todo corre en la Mac (Apple Silicon) sin APIs de pago.

> **Para cualquier sesión/modelo nuevo:** este archivo es el punto de partida.
> Antes de tocar nada, corré la validación (ver §"Cómo re-verificar") para
> confirmar que el pipeline está sano. Después mirá §"Pendientes / ideas".

## Objetivo del usuario
Un solo comando `qcaptions video.mp4` que transcribe, genera un `.ass` con
karaoke palabra-por-palabra (branding Data Quimbaya) y lo quema en el video.
El usuario edita videos en Final Cut, exporta vertical 1080×1920, audio en
español con términos técnicos en inglés (n8n, Claude, MCP, workflow…).

## Arquitectura
```
src/qcaptions/
  cli.py          # argparse + orquestación del pipeline (punto de entrada)
                  # subcomando: `qcaptions doctor` (ruteado antes de argparse)
  doctor.py       # diagnóstico del entorno + --download-model (con progreso)
  transcribe.py   # extract_audio + whisper.cpp (con progreso -pp) + parse_words
                  # + find_ffmpeg + probe_video (resolución via ffprobe)
  corrections.py  # correcciones (merge proyecto -> ~/.config/qcaptions -> --config)
  grouping.py     # agrupa palabras en captions (max_words / max_duration / pausas)
  assgen.py       # genera el .ass (estilo + karaoke + scale_style por resolución)
  burn.py         # burn-in: videotoolbox (default, rápido) / --archival libx264
config.toml       # correcciones por defecto (n8n, Claude, MCP, Quimbaya...)
scripts/validate.py  # validación end-to-end reproducible (correr tras cambios)
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

## Decisiones / gotchas importantes (leer antes de editar)
- **ffmpeg de Homebrew NO trae libass.** Hay que instalar `ffmpeg-full`
  (keg-only). `find_ffmpeg(need_ass=True)` prueba el del PATH y cae a
  `/opt/homebrew/opt/ffmpeg-full/bin/ffmpeg`. Forzable con env `QCAPTIONS_FFMPEG`.
- **Karaoke de una sola palabra activa** (no `\k` acumulativo): cada palabra
  arranca blanca, se vuelve dorada en su ventana con `\t(ini,ini,\1c&gold&)` y
  vuelve a blanca con `\t(fin,fin,\1c&white&)`.
- **`\t(0,0,...)` NO aplica en libass.** Por eso, si una palabra ya está activa
  al inicio del caption (`rel_start==0`, típicamente la primera), se pinta el
  color base **dorado** directamente. Ver `assgen._dialogue`. Regresión cubierta
  por `test_ass_first_word_starts_gold` y por el chequeo de píxeles de validate.py.
- **Formato ASS de `[Events]`** debe declarar `Name` y `MarginV`; si faltan,
  libass mete basura (`0,,`) al principio del texto.
- **Una corrección puede meter espacios dentro de una "palabra"** (ej.
  `"datakimbaya" = "Data Quimbaya"`). Eso genera un word cuyo `word` tiene
  espacio y se resalta como una unidad. No partir por espacios al analizar el
  `.ass`: contar bloques `{\1c...}` (así lo hace validate.py).
- **Dorado `#D4AF37`** en ASS es `&H0037AFD4` (orden BGR + alpha).
- **Colores ASS** = `&HAABBGGRR`. Blanco `&H00FFFFFF`, negro `&H00000000`.
- **Posición**: Alignment 2 (abajo-centro) + `MarginV=600` → ~68% de altura,
  arriba de la UI de TikTok.
- **Resolución**: el estilo se diseña sobre 1080×1920 y `scale_style()` lo
  adapta a la resolución real (via `probe_video`/ffprobe). Los flags
  `--fontsize/--margin-v` explícitos NO se re-escalan (se respetan tal cual).
- **Burn default = h264_videotoolbox** (`-q:v 65`): segundos en vez de minutos,
  calidad de sobra para TikTok (recomprime todo). `--archival` = libx264 crf 18
  slow. Si videotoolbox falla, cae solo a libx264.
- **Cache de transcripción**: el `.whisper.json` crudo se CONSERVA junto al
  video y se reusa si es más nuevo que el .mp4 (`--force` regenera). Las
  correcciones y la agrupación se re-aplican SIEMPRE desde el crudo, así editar
  config.toml no requiere re-transcribir. Ojo: cambiar `--model` no invalida
  el cache (usar `--force`).
- **Progreso whisper**: `-np -pp` juntos → sin logs pero con líneas
  `progress = N%` que `_run_with_progress` muestra con `\r`.
- Sin dependencias Python externas: solo stdlib (`tomllib`, `argparse`,
  `urllib` para descargar modelos).

## Cambiar de modelo whisper
El flag `--model` acepta un nombre (busca `models/ggml-<nombre>.bin`) o una ruta.

```bash
# Default (mejor calidad, ~1.5 GB):
qcaptions video.mp4                       # = --model ggml-large-v3-turbo

# Más liviano/rápido si el turbo va lento o falta espacio:
curl -L -o models/ggml-medium.bin \
  "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-medium.bin?download=true"
qcaptions video.mp4 --model ggml-medium

# Otros: ggml-small, ggml-base, ggml-large-v3 (lista en HuggingFace ggerganov/whisper.cpp)
```
Trade-off: `large-v3-turbo` = mejor con términos EN/ES y siglas; `medium`/`small`
= más rápidos pero cometen más errores (se compensan con `config.toml`).
Para validar con otro modelo: `python3 scripts/validate.py --model ggml-medium`.

> **"Cambiar de modelo de Claude":** no afecta al código. Cualquier modelo puede
> retomar leyendo este archivo y corriendo `scripts/validate.py`. Si el modelo
> nuevo quiere proponer mejoras, que primero valide el estado actual (baseline),
> luego cambie, y vuelva a correr validate.py para no romper regresiones.

## Cómo re-verificar (hacelo tras CUALQUIER cambio)
```bash
# Validación completa end-to-end (genera video de prueba con `say -v Mónica`,
# corre el pipeline, chequea coherencia .ass<->words.json, comprueba POR PÍXELES
# que la palabra activa es dorada, y corre los tests). Sale 0 si todo pasa.
python3 scripts/validate.py

# Solo los tests puros (rápido, sin whisper/ffmpeg):
python3 -m pytest tests/        # o correr las funciones test_* a mano si no hay pytest

# Inspección visual manual de un frame concreto (t en segundos):
/opt/homebrew/opt/ffmpeg-full/bin/ffmpeg -i samples/test_input_captioned.mp4 \
  -ss 2.9 -frames:v 1 /tmp/frame.png   # abrilo y mirá el dorado
```
El chequeo de píxeles de `validate.py` es la red de seguridad clave: detecta si
el highlight dorado se rompe (fue un bug real: la 1ª palabra no se doraba).

## Estado actual (validado)
Pipeline probado end-to-end con audio TTS (`say -v Mónica`) sobre video de color
sólido. Verificado por muestreo de píxeles que la palabra activa es dorada y las
demás blancas, y que los timestamps del `.ass` coinciden con `words.json`.
`scripts/validate.py` pasa: coherencia + dorado (5 instantes) + 6 tests.
Aún NO probado con un video real del usuario (voz humana).

## Pendientes / ideas para mejorar (para futuras sesiones)
Checklist de cosas que otro modelo/sesión podría tomar. Ninguna es bloqueante.
- [ ] **Probar con un video real** del usuario y afinar `config.toml` con los
      términos que su voz haga fallar (es lo más valioso; requiere un .mp4 real).
- [ ] **Watermark/logo Data Quimbaya** opcional en el `.ass` (un `Dialogue` fijo
      con `\pos` en una esquina, o `overlay` de un PNG en `burn.py`).
- [ ] **Preset de estilo alternativo**: resaltado con CAJA (BorderStyle 3 +
      BackColour) en vez de color, o color configurable por flag/config.
- [ ] **Balanceo de líneas**: con 4 palabras largas a veces parte feo; evaluar
      `\N` manual o bajar `--max-words` según ancho estimado.
- [ ] **VAD / filtrado de silencios** para timestamps más limpios en pausas
      largas (whisper.cpp tiene flags de VAD).
- [ ] **Confianza por palabra**: whisper-cli `--output-json-full` trae `p`
      (probabilidad); se podría marcar palabras dudosas para revisión.
- [ ] **Correcciones sensibles a contexto** (ej. "cloud"→"Claude" solo a veces).
      Hoy el reemplazo es incondicional; se podría hacer por regex/contexto.
- [ ] **Emojis / énfasis** por palabra clave (estilo CapCut más agresivo).
- [ ] **Invalidar cache al cambiar --model** (guardar el modelo usado en el
      .whisper.json o en un sidecar y comparar).
- [x] ~~`--preview`~~ — hecho (quema los primeros N segundos, encoder rápido).
- [x] ~~doctor + download-model~~ — hecho (`qcaptions doctor`).
- [x] ~~burn por hardware~~ — hecho (videotoolbox default + `--archival`).
- [x] ~~cache de transcripción~~ — hecho (reusa `.whisper.json`, `--force`).
- [x] ~~resoluciones ≠1080×1920~~ — hecho (`scale_style` + `probe_video`).
- [x] ~~config de usuario~~ — hecho (`~/.config/qcaptions/config.toml`).
- [x] ~~progreso de whisper~~ — hecho (`-pp` + `_run_with_progress`).
- [x] ~~`--open`~~ — hecho.
- [x] ~~modelo cuantizado~~ — hecho (doctor lo descarga; `--model *-q5_0`).

## Cómo correr los tests
```bash
python3 -m pytest tests/     # o correr las funciones test_* a mano (sin pytest)
python3 scripts/validate.py  # end-to-end (necesita whisper-cpp, ffmpeg-full, modelo, voz Mónica)
```
