"""LCARS colour themes shared by the GUI and the TUI."""
from __future__ import annotations

THEMES: dict[str, dict[str, str]] = {
    "TNG LCARS": dict(BLACK="#000000", ORANGE="#ff9900", PEACH="#ffcc99", LAVENDER="#cc99cc",
                      BLUE="#99ccff", PERIWINKLE="#9999ff", RED="#cc6666"),
    "DEEP SPACE 9": dict(BLACK="#000000", ORANGE="#d98a3d", PEACH="#f2d9b8", LAVENDER="#a98bb8",
                         BLUE="#7fa8d1", PERIWINKLE="#8a8ac4", RED="#b85450"),
    "KLINGON": dict(BLACK="#000000", ORANGE="#e03030", PEACH="#f0d0b0", LAVENDER="#b86060",
                    BLUE="#c4c4cc", PERIWINKLE="#d99a33", RED="#ff6a45"),
    "ROMULAN": dict(BLACK="#000000", ORANGE="#3fcf72", PEACH="#d4f2dc", LAVENDER="#8fbf9f",
                    BLUE="#6fd0b4", PERIWINKLE="#a5d35a", RED="#c8a35f"),
    "VULCAN": dict(BLACK="#000000", ORANGE="#e0702e", PEACH="#f5dcaa", LAVENDER="#cfa670",
                   BLUE="#ecc060", PERIWINKLE="#d48a6e", RED="#e05a47"),
}
DEFAULT_THEME = "TNG LCARS"
