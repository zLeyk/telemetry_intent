"""Template-based telemetry intent generation for Chatito."""

from .base_renderer import RenderedSurface, SurfacePiece
from .renderer import assign_styles, render_grammar, render_variants, surface_family

__all__ = [
    "RenderedSurface", "SurfacePiece", "assign_styles", "render_grammar",
    "render_variants", "surface_family",
]
