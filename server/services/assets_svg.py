"""SVG asset generators for invoices (logo and signature)."""
from __future__ import annotations

import hashlib
import random
import re
from typing import Iterable, List, Sequence, Tuple


def _initials_from_name(name: str) -> str:
    parts = [segment.strip() for segment in name.replace("/", " ").split() if segment.strip()]
    if not parts:
        return "NA"
    if len(parts) == 1:
        candidate = parts[0][:2]
        return candidate.upper()
    initials = "".join(part[0] for part in parts[:2])
    return initials.upper()


def generate_logo_svg(name: str, subtitle: str, color: str) -> str:
    """Return a minimalist circular logo as SVG markup.

    The logo is a 22x22mm circle with the initials of the supplied name
    displayed in the centre. The colour parameter controls both the stroke and
    text colour, defaulting to a blue-ish tone if the provided value is empty.
    """

    safe_color = color or "#2B6CB0"
    if not re.fullmatch(r"#[0-9a-fA-F]{3,8}", safe_color):
        safe_color = "#2B6CB0"
    initials = _initials_from_name(name or subtitle or "")
    svg = f"""
<g aria-label="Logo" role="img">
  <circle cx="11" cy="11" r="10.5" fill="#fff" stroke="{safe_color}" stroke-width="0.8" />
  <text x="11" y="11" font-family='-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Arial, "Noto Sans", "Liberation Sans", sans-serif' font-size="7" font-weight="600" fill="{safe_color}" text-anchor="middle" dominant-baseline="middle" letter-spacing="0.2">{initials}</text>
</g>
"""
    return svg.strip()


def _hash_to_points(name: str, seed: str, point_count: int = 12) -> List[Tuple[float, float]]:
    base = f"{seed}|{name}".encode("utf-8")
    digest = hashlib.sha256(base).digest()
    rng = random.Random(digest)
    points: List[Tuple[float, float]] = []
    width = 42.0
    height = 16.0
    x = 0.0
    for _ in range(point_count):
        x += width / (point_count - 1)
        offset_y = rng.uniform(-height * 0.4, height * 0.4)
        points.append((x, height / 2 + offset_y))
    return points


def _chaikin(points: Sequence[Tuple[float, float]]) -> List[Tuple[float, float]]:
    if len(points) < 3:
        return list(points)
    new_points: List[Tuple[float, float]] = [points[0]]
    for i in range(len(points) - 1):
        p0 = points[i]
        p1 = points[i + 1]
        q = (0.75 * p0[0] + 0.25 * p1[0], 0.75 * p0[1] + 0.25 * p1[1])
        r = (0.25 * p0[0] + 0.75 * p1[0], 0.25 * p0[1] + 0.75 * p1[1])
        new_points.extend([q, r])
    new_points.append(points[-1])
    return new_points


def _points_to_path(points: Iterable[Tuple[float, float]]) -> str:
    iterator = iter(points)
    try:
        first = next(iterator)
    except StopIteration:  # pragma: no cover - defensive
        return ""
    commands = [f"M {first[0]:.2f} {first[1]:.2f}"]
    prev = first
    for current in iterator:
        mid_x = (prev[0] + current[0]) / 2
        mid_y = (prev[1] + current[1]) / 2
        commands.append(f"Q {prev[0]:.2f} {prev[1]:.2f} {mid_x:.2f} {mid_y:.2f}")
        prev = current
    commands.append(f"T {prev[0]:.2f} {prev[1]:.2f}")
    return " ".join(commands)


def generate_signature_svg(name: str, seed: str = "za-2025") -> str:
    """Generate a deterministic pseudo-handwritten signature as SVG markup."""

    base_points = _hash_to_points(name or seed, seed)
    smoothed = list(base_points)
    for _ in range(2):
        smoothed = _chaikin(smoothed)
    # append a flourish loop at the end
    if smoothed:
        last_x, last_y = smoothed[-1]
        flourish = [
            (last_x + 3.0, last_y - 3.0),
            (last_x + 7.0, last_y + 1.5),
            (last_x + 10.0, last_y - 1.0),
            (last_x + 12.0, last_y + 2.5),
        ]
        smoothed.extend(flourish)
    path_commands = _points_to_path(smoothed)
    if not path_commands:
        path_commands = "M 2 8 Q 10 0 20 8 T 38 8"
    svg = f"""
<g aria-label="Signature" role="img">
  <path d="{path_commands}" fill="none" stroke="#111" stroke-width="0.6" stroke-linecap="round" stroke-linejoin="round" />
</g>
"""
    return svg.strip()


__all__ = ["generate_logo_svg", "generate_signature_svg"]
