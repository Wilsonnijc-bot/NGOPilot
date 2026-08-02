"""Backward-compatibility shim.

The canonical domain model now lives in ``app.domain``. This module re-exports
it so older imports (``from app.models import Employee``) keep working.
"""
from .domain import *  # noqa: F401,F403
from .domain import __all__  # noqa: F401
