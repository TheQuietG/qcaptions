"""Resolución de rutas de datos (modelos, config) según el modo de instalación.

- Desarrollo (checkout del repo, pipx --editable): todo vive en el repo.
- Instalado (brew, pipx normal): los modelos van a ~/.qcaptions/models y la
  config del usuario a ~/.config/qcaptions/config.toml.
- Override total con la variable de entorno QCAPTIONS_HOME.
"""

from __future__ import annotations

import os
from importlib import resources
from pathlib import Path


def data_dir() -> Path:
    """Directorio de datos (contiene models/ y, opcionalmente, config.toml)."""
    env = os.environ.get("QCAPTIONS_HOME")
    if env:
        return Path(env).expanduser()
    root = Path(__file__).resolve().parents[2]
    # Modo desarrollo: el paquete vive dentro de un checkout del repo.
    if (root / ".git").exists() or (root / "models").exists():
        return root
    return Path.home() / ".qcaptions"


def models_dir() -> Path:
    return data_dir() / "models"


def default_corrections() -> Path | None:
    """Correcciones por defecto empaquetadas con qcaptions."""
    try:
        p = resources.files("qcaptions") / "default_corrections.toml"
        return Path(str(p)) if p.is_file() else None
    except (OSError, TypeError):
        return None


def user_config_paths(explicit: Path | None = None) -> list[Path]:
    """Configs a mergear, de menor a mayor prioridad:
    defaults del paquete -> data_dir()/config.toml -> ~/.config/qcaptions/
    -> --config explícito.
    """
    paths: list[Path] = []
    pkg = default_corrections()
    if pkg:
        paths.append(pkg)
    paths.append(data_dir() / "config.toml")
    paths.append(Path.home() / ".config" / "qcaptions" / "config.toml")
    if explicit:
        paths.append(explicit)
    return paths
