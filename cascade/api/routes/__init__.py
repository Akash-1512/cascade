"""cascade.api.routes — REST API route modules.

Each module owns one resource family. Routers are imported and mounted by
:mod:`cascade.api.main` so adding a new resource means adding a new module
and one ``include_router`` call.
"""

from cascade.api.routes import decisions, learnings, okrs

__all__ = ["decisions", "learnings", "okrs"]
