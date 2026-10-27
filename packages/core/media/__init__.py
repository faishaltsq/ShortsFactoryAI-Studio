"""Media boundary: the only place this project reaches the operating system for pixels.

``render.py`` holds the single subprocess call into ``packages/video`` (Remotion/Node) plus the
ffprobe probe that proves what that subprocess produced. Nothing else in ``packages/core`` may
spawn a renderer; ``tests/test_architecture.py`` enforces the no-web-framework half of that rule
and review enforces the rest.
"""

from __future__ import annotations
