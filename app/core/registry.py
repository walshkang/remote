"""Module registry: builds enabled modules from the REMOTE_MODULES env var."""
from __future__ import annotations

import importlib
import logging
import os

from app.core.module_base import RemoteModule

log = logging.getLogger(__name__)


def load_modules() -> list[RemoteModule]:
    """REMOTE_MODULES="denon,hue,litter_robot,demo" -> imports app.modules.<id>.module.Module."""
    names = [n.strip() for n in os.getenv("REMOTE_MODULES", "denon,hue,litter_robot,demo").split(",") if n.strip()]
    modules: list[RemoteModule] = []
    for name in names:
        try:
            mod = importlib.import_module(f"app.modules.{name}.module")
            modules.append(mod.Module())
        except Exception:
            # One broken/unconfigured module must never take down the rest.
            log.exception("failed to load module %r; skipping", name)
    return modules
