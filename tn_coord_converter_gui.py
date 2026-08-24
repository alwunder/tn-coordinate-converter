#!/usr/bin/env python3
"""
Tennessee Coordinate Converter

Features
- Carter <-> NAD27 geographic conversion using the standalone Carter module
- Projection/datums conversion using pyproj
- Tkinter GUI for single-point and batch conversion
- CSV and JSON batch input/output
- CLI mode for batch conversion

See README.md for installation, usage, and deployment guidance.
"""
from __future__ import annotations

import argparse
import csv
import importlib.util
import json
import math
import os
import re
import subprocess
import sys
import tempfile
import traceback
import webbrowser
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple
from urllib.parse import unquote, urlsplit

from tn_coord_converter_module import (
    carter_area_center_to_nad27 as module_carter_area_center_to_nad27,
)
from tn_coord_converter_module import (
    carter_to_nad27 as module_carter_to_nad27,
)
from tn_coord_converter_module import (
    nad27_to_carter as module_nad27_to_carter,
)
from tn_coord_converter_module import normalize_carter_quadrants
from tn_coord_converter_version import __version__

try:
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk
    from tkinter import font as tkfont
    from tkinter.scrolledtext import ScrolledText
except Exception:  # pragma: no cover
    tk = None
    tkfont = None
    ttk = None
    ScrolledText = None
    filedialog = None
    messagebox = None

try:
    from pyproj import CRS, Transformer
except ImportError as exc:  # pragma: no cover
    raise SystemExit("pyproj is required. Install with: pip install pyproj") from exc

APP_TITLE = f"Tennessee Coordinate Converter v{__version__}"
MAPVIEW_DEFAULT_ZOOM = 14
MAPVIEW_DEFAULT_SCALE_BIN = "mvCache24K"

# Common Tennessee-centric CRS options.
FORMATS: Dict[str, Dict[str, Any]] = {
    "CARTER_QUADRANT": {
        "label": "Carter Coordinates (Quadrant)",
        "kind": "carter",
        "crs": None,
        "can_target": False,
    },
    "CARTER": {
        "label": "Carter Coordinates (Footage)",
        "kind": "carter",
        "crs": None,
    },
    "GEOGRAPHIC_NAD27": {"label": "Latitude/Longitude (NAD27)", "kind": "geographic", "crs": "EPSG:4267"},
    "GEOGRAPHIC_NAD83": {"label": "Latitude/Longitude (NAD83)", "kind": "geographic", "crs": "EPSG:4269"},
    "GEOGRAPHIC_WGS84": {"label": "Latitude/Longitude (WGS84)", "kind": "geographic", "crs": "EPSG:4326"},
    "TNSPC_NAD27": {"label": "Tennessee State Plane (NAD27, US ft)", "kind": "projected", "crs": "EPSG:2204"},
    "TNSPC_NAD83": {"label": "Tennessee State Plane (NAD83, meters)", "kind": "projected", "crs": "EPSG:32136"},
    "TNSPC_NAD83_FTUS": {"label": "Tennessee State Plane (NAD83, US ft)", "kind": "projected", "crs": "EPSG:2274"},
    "UTM15_NAD27": {"label": "UTM Zone 15N (NAD27)", "kind": "projected", "crs": "EPSG:26715"},
    "UTM16_NAD27": {"label": "UTM Zone 16N (NAD27)", "kind": "projected", "crs": "EPSG:26716"},
    "UTM17_NAD27": {"label": "UTM Zone 17N (NAD27)", "kind": "projected", "crs": "EPSG:26717"},
    "UTM15_NAD83": {"label": "UTM Zone 15N (NAD83)", "kind": "projected", "crs": "EPSG:26915"},
    "UTM16_NAD83": {"label": "UTM Zone 16N (NAD83)", "kind": "projected", "crs": "EPSG:26916"},
    "UTM17_NAD83": {"label": "UTM Zone 17N (NAD83)", "kind": "projected", "crs": "EPSG:26917"},
}

FORMAT_LABEL_TO_KEY = {v["label"]: k for k, v in FORMATS.items()}
SOURCE_FORMAT_LABELS = tuple(v["label"] for v in FORMATS.values())
TARGET_FORMAT_KEYS = tuple(k for k, v in FORMATS.items() if v.get("can_target", True))
TARGET_FORMAT_LABELS = tuple(FORMATS[key]["label"] for key in TARGET_FORMAT_KEYS)
CARTER_SOURCE_FORMATS = {"CARTER", "CARTER_QUADRANT"}

GEOGRAPHIC_DISPLAY_FORMATS = (
    "DD",
    "DMS (symbols)",
    "DMS (spaces)",
    "DDM (symbols)",
    "DDM (spaces)",
)

README_FILENAME = "README.md"
_MARKDOWN_INLINE_RE = re.compile(
    r"(\*\*[^*]+\*\*|`[^`]+`|\[[^\]]+\]\([^)]+\))"
)
_MARKDOWN_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+)$")
_MARKDOWN_BULLET_RE = re.compile(r"^\s*[-*]\s+(.+)$")
_MARKDOWN_NUMBER_RE = re.compile(r"^\s*(\d+)\.\s+(.+)$")
_MARKDOWN_IMAGE_RE = re.compile(
    r"^!\[([^\]]*)\]\((?:<([^>]+)>|([^)]+))\)\s*$"
)


def resolve_readme_document() -> Tuple[str, Optional[Path]]:
    """Load the About-tab README and return its text and asset directory."""

    candidates: List[Path] = []
    if getattr(sys, "frozen", False):
        candidates.append(Path(sys.executable).resolve().with_name(README_FILENAME))
        bundle_directory = getattr(sys, "_MEIPASS", None)
        if bundle_directory:
            candidates.append(Path(bundle_directory) / README_FILENAME)
    candidates.append(Path(__file__).resolve().with_name(README_FILENAME))

    for path in candidates:
        if path.is_file():
            return path.read_text(encoding="utf-8"), path.parent

    return (
        (
            "# Tennessee Coordinate Converter\n\n"
            "The full user guide could not be loaded. Keep README.md beside the "
            "application, or include it as data when building the executable.\n"
        ),
        None,
    )


def resolve_readme_text() -> str:
    """Load the README text used by the formatted About tab."""

    return resolve_readme_document()[0]


def parse_markdown_image(line: str) -> Optional[Tuple[str, str]]:
    """Return alt text and target for a standalone Markdown image line."""

    match = _MARKDOWN_IMAGE_RE.fullmatch(line.strip())
    if match is None:
        return None
    return match.group(1).strip(), (match.group(2) or match.group(3)).strip()


def parse_markdown_link(token: str) -> Optional[Tuple[str, str]]:
    """Return the label and target from one inline Markdown link token."""

    match = re.fullmatch(r"\[([^\]]+)\]\(([^)]+)\)", token)
    if match is None:
        return None
    label = match.group(1).strip()
    target = match.group(2).strip()
    if target.startswith("<") and target.endswith(">"):
        target = target[1:-1].strip()
    return label, target


def resolve_markdown_image_path(target: str, asset_directory: Optional[Path]) -> Optional[Path]:
    """Resolve a local Markdown image target relative to its document."""

    if asset_directory is None or re.match(r"^[a-z][a-z0-9+.-]*://", target, re.IGNORECASE):
        return None
    path = Path(target)
    if not path.is_absolute():
        path = asset_directory / path
    return path.resolve()


def open_path_with_default_application(path: Path) -> None:
    """Open a local file with the operating system's associated application."""

    path = Path(path).resolve()
    if sys.platform == "win32":
        os.startfile(str(path))
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(path)])
    else:
        subprocess.Popen(["xdg-open", str(path)])


def _markdown_tags(base_tag: Optional[str], inline_tag: Optional[str] = None) -> Tuple[str, ...]:
    return tuple(tag for tag in (base_tag, inline_tag) if tag)


def _insert_markdown_link(
    widget: tk.Text,
    label: str,
    target: str,
    base_tag: Optional[str],
) -> None:
    """Insert a clean clickable link label into a Markdown Text widget."""

    link_serial = getattr(widget, "_markdown_link_serial", 0) + 1
    setattr(widget, "_markdown_link_serial", link_serial)
    unique_tag = f"markdown_link_{link_serial}"
    widget.insert(
        "end",
        label,
        (*_markdown_tags(base_tag, "link"), unique_tag),
    )

    link_handler = getattr(widget, "_markdown_link_handler", None)
    if link_handler is not None:
        def activate_link(_event: Any, link_target: str = target) -> str:
            link_handler(link_target)
            return "break"

        widget.tag_bind(unique_tag, "<Button-1>", activate_link)


def _insert_markdown_inline(widget: tk.Text, text: str, base_tag: Optional[str] = None) -> None:
    """Insert a small, dependency-free subset of inline Markdown."""

    position = 0
    for match in _MARKDOWN_INLINE_RE.finditer(text):
        widget.insert("end", text[position:match.start()], _markdown_tags(base_tag))
        token = match.group(0)
        if token.startswith("**"):
            widget.insert("end", token[2:-2], _markdown_tags(base_tag, "strong"))
        elif token.startswith("`"):
            widget.insert("end", token[1:-1], _markdown_tags(base_tag, "inline_code"))
        else:
            markdown_link = parse_markdown_link(token)
            if markdown_link is None:
                widget.insert("end", token, _markdown_tags(base_tag))
            else:
                label, target = markdown_link
                _insert_markdown_link(widget, label, target, base_tag)
        position = match.end()
    widget.insert("end", text[position:], _markdown_tags(base_tag))


def _split_markdown_table_row(line: str) -> List[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def _is_markdown_table_separator(line: str) -> bool:
    cells = _split_markdown_table_row(line)
    return bool(cells) and all(re.fullmatch(r":?-{3,}:?", cell) for cell in cells)


def _insert_markdown_table(widget: tk.Text, table_lines: List[str]) -> None:
    headers = _split_markdown_table_row(table_lines[0])
    rows = [
        _split_markdown_table_row(line)
        for line in table_lines[2:]
        if line.strip()
    ]

    for row in rows:
        if not row:
            continue
        _insert_markdown_inline(widget, row[0], "table_title")
        widget.insert("end", "\n")
        for index, value in enumerate(row[1:], start=1):
            header = headers[index] if index < len(headers) else f"Column {index + 1}"
            widget.insert("end", f"    {header}: ", "table_label")
            _insert_markdown_inline(widget, value)
            widget.insert("end", "\n")
        widget.insert("end", "\n")


def _insert_markdown_image(
    widget: tk.Text,
    alt_text: str,
    target: str,
    asset_directory: Optional[Path],
) -> None:
    """Insert a local PNG image, with readable fallback text on failure."""

    image_path = resolve_markdown_image_path(target, asset_directory)
    try:
        if image_path is None or not image_path.is_file():
            raise FileNotFoundError(target)
        image = tk.PhotoImage(master=widget, file=str(image_path))
    except (FileNotFoundError, OSError, tk.TclError):
        description = alt_text or Path(target).name or "unnamed image"
        widget.insert(
            "end",
            f"[Image unavailable: {description} ({target})]\n\n",
            "image_error",
        )
        return

    # Tk discards images whose Python objects are garbage-collected, so keep
    # references on the long-lived Text widget.
    image_references = getattr(widget, "_markdown_image_references", None)
    if image_references is None:
        image_references = []
        setattr(widget, "_markdown_image_references", image_references)
    image_references.append(image)

    start = widget.index("end-1c")
    widget.image_create("end", image=image, padx=8, pady=6)
    widget.insert("end", "\n\n")
    widget.tag_add("markdown_image", start, "end-1c")


def render_markdown(
    widget: tk.Text,
    markdown_text: str,
    asset_directory: Optional[Path] = None,
    link_handler: Optional[Callable[[str], None]] = None,
) -> None:
    """Render readable Markdown-style content in a Tkinter Text widget."""

    setattr(widget, "_markdown_link_handler", link_handler)
    lines = markdown_text.expandtabs(4).splitlines()
    paragraph: List[str] = []

    def flush_paragraph() -> None:
        if not paragraph:
            return
        _insert_markdown_inline(widget, " ".join(part.strip() for part in paragraph))
        widget.insert("end", "\n\n")
        paragraph.clear()

    index = 0
    in_code_block = False
    while index < len(lines):
        line = lines[index]
        stripped = line.strip()

        if stripped.startswith("```"):
            flush_paragraph()
            in_code_block = not in_code_block
            if not in_code_block:
                widget.insert("end", "\n")
            index += 1
            continue

        if in_code_block:
            widget.insert("end", line + "\n", "code_block")
            index += 1
            continue

        markdown_image = parse_markdown_image(stripped)
        if markdown_image is not None:
            flush_paragraph()
            alt_text, target = markdown_image
            _insert_markdown_image(widget, alt_text, target, asset_directory)
            index += 1
            continue

        heading = _MARKDOWN_HEADING_RE.match(stripped)
        if heading:
            flush_paragraph()
            level = min(len(heading.group(1)), 3)
            _insert_markdown_inline(widget, heading.group(2), f"heading{level}")
            widget.insert("end", "\n")
            index += 1
            continue

        if (
            "|" in line
            and index + 1 < len(lines)
            and _is_markdown_table_separator(lines[index + 1])
        ):
            flush_paragraph()
            end = index + 2
            while end < len(lines) and "|" in lines[end] and lines[end].strip():
                end += 1
            _insert_markdown_table(widget, lines[index:end])
            index = end
            continue

        bullet = _MARKDOWN_BULLET_RE.match(line)
        numbered = _MARKDOWN_NUMBER_RE.match(line)
        if bullet or numbered:
            flush_paragraph()
            marker = "\u2022" if bullet else f"{numbered.group(1)}."
            content = bullet.group(1) if bullet else numbered.group(2)

            continuation = index + 1
            while (
                continuation < len(lines)
                and lines[continuation].startswith(("  ", "\t"))
                and lines[continuation].strip()
                and not _MARKDOWN_BULLET_RE.match(lines[continuation])
                and not _MARKDOWN_NUMBER_RE.match(lines[continuation])
            ):
                content += " " + lines[continuation].strip()
                continuation += 1

            widget.insert("end", f"  {marker} ", "list_marker")
            _insert_markdown_inline(widget, content)
            widget.insert("end", "\n")
            index = continuation
            continue

        if not stripped:
            had_paragraph = bool(paragraph)
            flush_paragraph()
            existing_text = widget.get("1.0", "end-1c")
            if (
                not had_paragraph
                and existing_text
                and not existing_text.endswith("\n\n")
            ):
                widget.insert("end", "\n")
            index += 1
            continue

        paragraph.append(stripped)
        index += 1

    flush_paragraph()


class MapViewController:
    def __init__(
        self,
        command_file: Path,
        *,
        zoom: int = MAPVIEW_DEFAULT_ZOOM,
        scale_bin: str = MAPVIEW_DEFAULT_SCALE_BIN,
    ):
        self.command_file = Path(command_file)
        self.zoom = int(zoom)
        self.scale_bin = str(scale_bin)
        self.command_seq = 0
        self.browser_process: Optional[subprocess.Popen] = None

    @staticmethod
    def _atomic_write_json(path: Path, payload: Dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = path.with_suffix(path.suffix + ".tmp")
        tmp_path.write_text(json.dumps(payload), encoding="utf-8")
        tmp_path.replace(path)

    def _browser_is_running(self) -> bool:
        return self.browser_process is not None and self.browser_process.poll() is None

    @staticmethod
    def _ensure_pywebview_available() -> bool:
        return importlib.util.find_spec("webview") is not None

    def _browser_command(self) -> List[str]:
        command = [sys.executable]
        if not getattr(sys, "frozen", False):
            command.append(str(Path(__file__).resolve()))
        command.extend(
            [
                "--mapview-browser",
                "--mapview-command-file",
                str(self.command_file),
                "--mapview-scale-bin",
                self.scale_bin,
            ]
        )
        return command

    def _start_browser_if_needed(self) -> None:
        if self._browser_is_running():
            return

        if not self._ensure_pywebview_available():
            raise RuntimeError("pywebview is not installed. Install it with: pip install pywebview")

        self.browser_process = subprocess.Popen(
            self._browser_command()
        )

    def open_or_update(self, lon: float, lat: float) -> str:
        lon = float(lon)
        lat = float(lat)
        if not (-180 <= lon <= 180):
            raise ValueError("Map longitude must be between -180 and 180.")
        if not (-90 <= lat <= 90):
            raise ValueError("Map latitude must be between -90 and 90.")

        self.command_seq += 1
        self._atomic_write_json(
            self.command_file,
            {"seq": self.command_seq, "lon": lon, "lat": lat, "zoom": self.zoom},
        )

        started = False
        if not self._browser_is_running():
            self._start_browser_if_needed()
            started = True

        if self._browser_is_running():
            return "started" if started else "updated"
        return "start_attempted"

    def close(self) -> None:
        if self._browser_is_running():
            try:
                self.browser_process.terminate()
            except Exception:
                pass


def normalize_text(value: Any) -> str:
    return str(value).strip().upper()


def normalize_township(value: Any) -> str:
    return normalize_text(value)


def normalize_range(value: Any) -> str:
    return normalize_text(value)


def parse_geographic_coordinate(value: Any, axis: str) -> float:
    """Parse decimal degrees, DDM, or DMS text for one geographic axis."""

    if axis not in {"lat", "lon"}:
        raise ValueError("Geographic coordinate axis must be 'lat' or 'lon'.")

    field_name = "Latitude" if axis == "lat" else "Longitude"
    if value is None or (isinstance(value, str) and not value.strip()):
        raise ValueError(f"{field_name} is required.")

    text = str(value).strip().upper().replace("\N{MINUS SIGN}", "-")
    hemispheres = re.findall(r"[NSEW]", text)
    if len(hemispheres) > 1:
        raise ValueError(f"{field_name} must contain at most one direction letter.")

    hemisphere = hemispheres[0] if hemispheres else None
    allowed_hemispheres = {"N", "S"} if axis == "lat" else {"E", "W"}
    if hemisphere is not None and hemisphere not in allowed_hemispheres:
        expected = "N or S" if axis == "lat" else "E or W"
        raise ValueError(f"{field_name} direction must be {expected}.")

    unsigned_text = re.sub(r"[NSEW]", " ", text)
    cleaned = re.sub(
        r"[\N{DEGREE SIGN}\N{MASCULINE ORDINAL INDICATOR}\N{RING ABOVE}]",
        " ",
        unsigned_text,
    )
    cleaned = re.sub(r"['\N{RIGHT SINGLE QUOTATION MARK}\N{PRIME}]", " ", cleaned)
    cleaned = re.sub(r'["\N{RIGHT DOUBLE QUOTATION MARK}\N{DOUBLE PRIME}]', " ", cleaned)
    cleaned = re.sub(r"[:,;]", " ", cleaned).strip()
    number = r"(?:\d+(?:\.\d*)?|\.\d+)"
    if not re.fullmatch(rf"[+-]?{number}(?:\s+{number}){{0,2}}", cleaned):
        raise ValueError(
            f"{field_name} must be decimal degrees, degrees/minutes, or "
            "degrees/minutes/seconds."
        )

    parts = cleaned.split()
    degrees = float(parts[0])
    minutes = float(parts[1]) if len(parts) >= 2 else 0.0
    seconds = float(parts[2]) if len(parts) == 3 else 0.0
    if minutes >= 60.0:
        raise ValueError(f"{field_name} minutes must be less than 60.")
    if seconds >= 60.0:
        raise ValueError(f"{field_name} seconds must be less than 60.")

    explicit_negative = parts[0].startswith("-")
    magnitude = abs(degrees) + minutes / 60.0 + seconds / 3600.0
    if hemisphere in {"S", "W"}:
        parsed = -magnitude
    elif hemisphere in {"N", "E"}:
        if explicit_negative:
            raise ValueError(
                f"{field_name} cannot combine a negative sign with direction {hemisphere}."
            )
        parsed = magnitude
    else:
        parsed = -magnitude if explicit_negative else magnitude

    limit = 90.0 if axis == "lat" else 180.0
    if not math.isfinite(parsed) or not (-limit <= parsed <= limit):
        raise ValueError(f"{field_name} must be between {-limit:g} and {limit:g}.")
    return parsed


def _coordinate_parts(
    value: Any,
    axis: str,
    minute_precision: int = 3,
) -> Tuple[int, int, float, str]:
    """Return rounded absolute DMS parts and a direction letter."""

    coordinate = float(value)
    if not math.isfinite(coordinate):
        raise ValueError("Coordinate must be a finite number.")
    limit = 90.0 if axis == "lat" else 180.0
    if not (-limit <= coordinate <= limit):
        label = "Latitude" if axis == "lat" else "Longitude"
        raise ValueError(f"{label} must be between {-limit:g} and {limit:g}.")

    direction = (
        ("S" if coordinate < 0 else "N")
        if axis == "lat"
        else ("W" if coordinate < 0 else "E")
    )
    absolute = abs(coordinate)
    degrees = int(absolute)
    minute_total = (absolute - degrees) * 60.0
    minutes = int(minute_total)
    seconds = round((minute_total - minutes) * 60.0, minute_precision)
    if seconds >= 60.0:
        minutes += 1
        seconds = 0.0
    if minutes >= 60:
        degrees += 1
        minutes = 0
    return degrees, minutes, seconds, direction


def format_geographic_coordinate_for_clipboard(
    value: Any,
    axis: str,
    output_format: str = "DD",
) -> str:
    """Format a latitude or longitude for clipboard output."""

    if output_format == "DD":
        return format_coordinate_for_clipboard(value)
    if output_format not in GEOGRAPHIC_DISPLAY_FORMATS:
        raise ValueError(f"Unsupported geographic output format: {output_format}")

    degrees, minutes, seconds, direction = _coordinate_parts(value, axis)
    if output_format.startswith("DMS"):
        seconds_text = f"{seconds:.3f}"
        if output_format == "DMS (symbols)":
            return f'{degrees}\N{DEGREE SIGN} {minutes}\' {seconds_text}" {direction}'
        return f"{degrees} {minutes} {seconds_text} {direction}"

    decimal_minutes = minutes + seconds / 60.0
    minutes_text = f"{decimal_minutes:.3f}"
    if output_format == "DDM (symbols)":
        return f"{degrees}\N{DEGREE SIGN} {minutes_text}' {direction}"
    return f"{degrees} {minutes_text} {direction}"


def make_cartercord(section: Any, township: Any, range_: Any) -> str:
    if section is None or str(section).strip() == "":
        return f"{normalize_township(township)}-{normalize_range(range_)}"
    return f"{int(section)}-{normalize_township(township)}-{normalize_range(range_)}"


@dataclass
class CarterResult:
    section: Optional[int]
    township: str
    range_: str
    ns_feet: Optional[float]
    ns_line: Optional[str]
    ew_feet: Optional[float]
    ew_line: Optional[str]
    cartercord: str
    nad27_lat: float
    nad27_lon: float
    quadrants: Optional[str] = None
    carter_complete: bool = True
    location_method: str = "footage"
    location_note: Optional[str] = None


class CoordinateConverter:
    def __init__(self):
        self._transformers: Dict[Tuple[str, str], Transformer] = {}

    def get_transformer(self, from_fmt: str, to_fmt: str) -> Transformer:
        key = (from_fmt, to_fmt)
        if key not in self._transformers:
            from_crs = FORMATS[from_fmt]["crs"]
            to_crs = FORMATS[to_fmt]["crs"]
            self._transformers[key] = Transformer.from_crs(CRS.from_user_input(from_crs), CRS.from_user_input(to_crs), always_xy=True)
        return self._transformers[key]

    def carter_to_nad27(self, section: Any, township: Any, range_: Any, ns_feet: float, ns_line: str, ew_feet: float, ew_line: str) -> CarterResult:
        coordinate = module_carter_to_nad27(
            section,
            township,
            range_,
            ns_feet,
            ns_line,
            ew_feet,
            ew_line,
        )
        section = int(str(section).strip())
        township = normalize_township(township)
        range_ = normalize_range(range_)
        ns_line = normalize_text(ns_line)
        ew_line = normalize_text(ew_line)
        ns_feet = float(ns_feet)
        ew_feet = float(ew_feet)

        return CarterResult(
            section=section,
            township=township,
            range_=range_,
            ns_feet=ns_feet,
            ns_line=ns_line,
            ew_feet=ew_feet,
            ew_line=ew_line,
            cartercord=make_cartercord(section, township, range_),
            nad27_lat=coordinate.nad27_lat,
            nad27_lon=coordinate.nad27_lon,
        )

    def carter_quadrant_to_nad27(
        self,
        section: Any,
        township: Any,
        range_: Any,
        quadrants: Any,
    ) -> CarterResult:
        return self.carter_area_center_to_nad27(
            township,
            range_,
            section=section,
            quadrants=quadrants,
        )

    def carter_area_center_to_nad27(
        self,
        township: Any,
        range_: Any,
        *,
        section: Any = None,
        quadrants: Any = None,
    ) -> CarterResult:
        has_section = not self._is_blank(section)
        has_quadrants = not self._is_blank(quadrants)
        calls = normalize_carter_quadrants(quadrants) if has_quadrants else ()
        coordinate = module_carter_area_center_to_nad27(
            township,
            range_,
            section=section if has_section else None,
            quadrants=calls if calls else None,
        )

        normalized_township = normalize_township(township)
        normalized_range = normalize_range(range_)
        section_number = int(str(section).strip()) if has_section else None
        if not has_section:
            complete = False
            location_method = "center_of_township_range"
            location_note = (
                "Incomplete Carter coordinate (township/range only); result is the center "
                "of the 5-minute Carter quadrangle."
            )
        elif not calls:
            complete = False
            location_method = "center_of_section"
            location_note = (
                "Incomplete Carter coordinate (no footage or quadrants); result is the "
                "center of the section."
            )
        elif len(calls) == 1:
            complete = False
            location_method = "center_of_largest_quadrant"
            location_note = (
                "Incomplete legacy Carter coordinate (largest quadrant only); result is "
                "the center of that largest quadrant."
            )
        elif len(calls) == 2:
            complete = False
            location_method = "center_of_middle_quadrant"
            location_note = (
                "Incomplete legacy Carter coordinate (middle and largest quadrants only); "
                "result is the center of the middle quadrant subdivision."
            )
        else:
            complete = True
            location_method = "center_of_smallest_quadrant"
            location_note = (
                "Legacy Carter quadrant coordinate; result is the center of the smallest "
                "quadrant subdivision."
            )

        return CarterResult(
            section=section_number,
            township=normalized_township,
            range_=normalized_range,
            ns_feet=None,
            ns_line=None,
            ew_feet=None,
            ew_line=None,
            cartercord=make_cartercord(
                section_number,
                normalized_township,
                normalized_range,
            ),
            nad27_lat=coordinate.nad27_lat,
            nad27_lon=coordinate.nad27_lon,
            quadrants=" ".join(calls) if calls else None,
            carter_complete=complete,
            location_method=location_method,
            location_note=location_note,
        )

    def nad27_to_carter(self, lat27: float, lon27: float) -> CarterResult:
        coordinate = module_nad27_to_carter(lat27, lon27)

        return CarterResult(
            section=coordinate.section,
            township=coordinate.township,
            range_=coordinate.range_,
            ns_feet=coordinate.ns_feet,
            ns_line=coordinate.ns_line,
            ew_feet=coordinate.ew_feet,
            ew_line=coordinate.ew_line,
            cartercord=coordinate.cartercord,
            nad27_lat=coordinate.nad27_lat,
            nad27_lon=coordinate.nad27_lon,
            location_method="derived_footage",
        )

    def project(self, x: float, y: float, source_fmt: str, target_fmt: str) -> Tuple[float, float]:
        transformer = self.get_transformer(source_fmt, target_fmt)
        return transformer.transform(float(x), float(y))

    @staticmethod
    def _is_blank(value: Any) -> bool:
        return value is None or (isinstance(value, str) and value.strip() == "")

    @staticmethod
    def _parse_float(field_name: str, value: Any) -> float:
        try:
            parsed = float(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{field_name} must be a valid number.") from exc
        if math.isnan(parsed) or math.isinf(parsed):
            raise ValueError(f"{field_name} must be a finite number.")
        return parsed

    @staticmethod
    def _parse_int(field_name: str, value: Any) -> int:
        try:
            return int(str(value).strip())
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{field_name} must be a whole number.") from exc

    def _validate_source_payload(self, source_fmt: str, payload: Dict[str, Any]) -> None:
        if source_fmt in CARTER_SOURCE_FORMATS:
            required_location = [
                ("township", "Township"),
                ("range", "Range"),
            ]
            missing = [
                label for key, label in required_location
                if self._is_blank(payload.get(key))
            ]
            if missing:
                raise ValueError(f"Missing required Carter input field(s): {', '.join(missing)}.")

            has_section = not self._is_blank(payload.get("section"))
            if has_section:
                self._parse_int("Section", payload["section"])

            if source_fmt == "CARTER_QUADRANT":
                has_quadrants = not self._is_blank(payload.get("quadrants"))
                if has_quadrants:
                    if not has_section:
                        raise ValueError(
                            "A Carter section is required when quadrants are provided."
                        )
                    normalize_carter_quadrants(payload["quadrants"])
                return

            has_any_footage = any(
                not self._is_blank(payload.get(key))
                for key in ("ns_feet", "ew_feet")
            )
            if not has_any_footage:
                # Township/range alone and township/range/section are valid
                # incomplete locations represented by their bounding center.
                return

            missing_footage = [
                label
                for key, label in (
                    ("section", "Section"),
                    ("ns_feet", "N-S Distance"),
                    ("ns_line", "From N-S Line"),
                    ("ew_feet", "E-W Distance"),
                    ("ew_line", "From E-W Line"),
                )
                if self._is_blank(payload.get(key))
            ]
            if missing_footage:
                raise ValueError(
                    f"Missing Carter footage field(s): {', '.join(missing_footage)}."
                )

            ns_feet = self._parse_float("N-S Distance (ns_feet)", payload["ns_feet"])
            ew_feet = self._parse_float("E-W Distance (ew_feet)", payload["ew_feet"])
            if ns_feet < 0:
                raise ValueError("N-S Distance (ns_feet) cannot be negative.")
            if ew_feet < 0:
                raise ValueError("E-W Distance (ew_feet) cannot be negative.")

            ns_line = normalize_text(payload["ns_line"])
            ew_line = normalize_text(payload["ew_line"])
            if ns_line not in {"FSL", "FNL"}:
                raise ValueError("From N-S Line must be FSL or FNL.")
            if ew_line not in {"FWL", "FEL"}:
                raise ValueError("From E-W Line must be FWL or FEL.")
            return

        source_kind = FORMATS[source_fmt]["kind"]
        if source_kind == "geographic":
            if self._is_blank(payload.get("lon")) or self._is_blank(payload.get("lat")):
                raise ValueError("Longitude and Latitude are required.")
            parse_geographic_coordinate(payload["lon"], "lon")
            parse_geographic_coordinate(payload["lat"], "lat")
            return

        if self._is_blank(payload.get("x")) or self._is_blank(payload.get("y")):
            raise ValueError("X and Y coordinates are required.")
        self._parse_float("X", payload["x"])
        self._parse_float("Y", payload["y"])

    def convert_single(self, source_fmt: str, target_fmt: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        if source_fmt not in FORMATS:
            raise ValueError(f"Unsupported source format: {source_fmt}")
        if target_fmt not in FORMATS:
            raise ValueError(f"Unsupported target format: {target_fmt}")
        if target_fmt not in TARGET_FORMAT_KEYS:
            raise ValueError(f"{FORMATS[target_fmt]['label']} is input-only.")
        if source_fmt == target_fmt:
            raise ValueError("Source and target formats are the same. Choose different formats to convert.")

        self._validate_source_payload(source_fmt, payload)

        if source_fmt in CARTER_SOURCE_FORMATS:
            if (
                source_fmt == "CARTER_QUADRANT"
                and not self._is_blank(payload.get("quadrants"))
            ):
                carter = self.carter_quadrant_to_nad27(
                    payload["section"],
                    payload["township"],
                    payload["range"],
                    payload["quadrants"],
                )
            elif source_fmt == "CARTER" and any(
                not self._is_blank(payload.get(key))
                for key in ("ns_feet", "ew_feet")
            ):
                carter = self.carter_to_nad27(
                    payload["section"], payload["township"], payload["range"],
                    payload["ns_feet"], payload["ns_line"], payload["ew_feet"], payload["ew_line"],
                )
            else:
                carter = self.carter_area_center_to_nad27(
                    payload["township"],
                    payload["range"],
                    section=payload.get("section"),
                )
            if target_fmt == "CARTER":
                footage = self.nad27_to_carter(carter.nad27_lat, carter.nad27_lon)
                footage.carter_complete = carter.carter_complete
                footage.location_method = "derived_footage_from_carter_area_center"
                footage.location_note = (
                    "Footage notation derived from the center of the supplied legacy "
                    "Carter area; it does not add precision to the historical location."
                )
                out = self._carter_result_to_dict(footage)
                spc_x, spc_y = self.project(
                    carter.nad27_lon,
                    carter.nad27_lat,
                    "GEOGRAPHIC_NAD27",
                    "TNSPC_NAD27",
                )
                out["tnspc_nad27_x"] = spc_x
                out["tnspc_nad27_y"] = spc_y
                return out
            if target_fmt == "GEOGRAPHIC_NAD27":
                return self._compose_output(
                    target_fmt,
                    carter.nad27_lon,
                    carter.nad27_lat,
                    carter,
                )
            x, y = self.project(carter.nad27_lon, carter.nad27_lat, "GEOGRAPHIC_NAD27", target_fmt)
            return self._compose_output(target_fmt, x, y, carter)

        if target_fmt == "CARTER":
            lon27, lat27 = self._to_nad27_xy(source_fmt, payload)
            carter = self.nad27_to_carter(lat27, lon27)
            out = self._carter_result_to_dict(carter)
            spc_x, spc_y = self.project(lon27, lat27, "GEOGRAPHIC_NAD27", "TNSPC_NAD27")
            out["tnspc_nad27_x"] = spc_x
            out["tnspc_nad27_y"] = spc_y
            return out

        source_kind = FORMATS[source_fmt]["kind"]
        if source_kind == "geographic":
            lon = parse_geographic_coordinate(payload["lon"], "lon")
            lat = parse_geographic_coordinate(payload["lat"], "lat")
            x, y = self.project(lon, lat, source_fmt, target_fmt)
        else:
            x, y = self.project(float(payload["x"]), float(payload["y"]), source_fmt, target_fmt)

        return self._compose_output(target_fmt, x, y, None)

    def _to_nad27_xy(self, source_fmt: str, payload: Dict[str, Any]) -> Tuple[float, float]:
        if source_fmt == "GEOGRAPHIC_NAD27":
            return (
                parse_geographic_coordinate(payload["lon"], "lon"),
                parse_geographic_coordinate(payload["lat"], "lat"),
            )
        if FORMATS[source_fmt]["kind"] == "geographic":
            lon = parse_geographic_coordinate(payload["lon"], "lon")
            lat = parse_geographic_coordinate(payload["lat"], "lat")
            lon27, lat27 = self.project(lon, lat, source_fmt, "GEOGRAPHIC_NAD27")
            return lon27, lat27
        lon27, lat27 = self.project(float(payload["x"]), float(payload["y"]), source_fmt, "GEOGRAPHIC_NAD27")
        return lon27, lat27

    def _carter_result_to_dict(self, carter: CarterResult) -> Dict[str, Any]:
        result: Dict[str, Any] = {}
        if carter.section is not None:
            result["section"] = carter.section
        result["township"] = carter.township
        result["range"] = carter.range_
        if carter.ns_feet is not None:
            result["ns_feet"] = carter.ns_feet
            result["ns_line"] = carter.ns_line
            result["ew_feet"] = carter.ew_feet
            result["ew_line"] = carter.ew_line
        result["cartercord"] = carter.cartercord
        result["nad27_lon"] = carter.nad27_lon
        result["nad27_lat"] = carter.nad27_lat
        result["carter_complete"] = carter.carter_complete
        result["location_method"] = carter.location_method
        if carter.quadrants is not None:
            result["quadrants"] = carter.quadrants
            result["quadrant_order"] = "smallest_to_largest"
            result["quadrant_count"] = len(carter.quadrants.split())
            result["quadrant_point"] = carter.location_method
        if carter.location_note is not None:
            result["location_note"] = carter.location_note
        return result

    def _compose_output(self, fmt: str, x: float, y: float, carter: Optional[CarterResult]) -> Dict[str, Any]:
        if FORMATS[fmt]["kind"] == "geographic":
            # JSON preserves insertion order: the x-like longitude always
            # precedes the y-like latitude, matching projected x/y outputs.
            out = {"lon": x, "lat": y}
        else:
            out = {"x": x, "y": y}
        out["format"] = fmt
        out["format_label"] = FORMATS[fmt]["label"]
        if carter is not None:
            out.update(self._carter_result_to_dict(carter))
        return out

    def convert_record(self, record: Dict[str, Any], source_fmt: str, target_fmt: str) -> Dict[str, Any]:
        payload = parse_record_payload(record, source_fmt)
        result = self.convert_single(source_fmt, target_fmt, payload)
        merged = dict(record)
        for k, v in result.items():
            merged[k] = v
        merged["source_format"] = source_fmt
        merged["target_format"] = target_fmt
        return merged


def _first(record: Dict[str, Any], keys: Iterable[str], default: Any = None) -> Any:
    lowered = {str(k).strip().lower(): v for k, v in record.items()}
    for key in keys:
        if key.lower() in lowered and lowered[key.lower()] not in (None, ""):
            return lowered[key.lower()]
    return default


def parse_record_payload(record: Dict[str, Any], source_fmt: str) -> Dict[str, Any]:
    if source_fmt in CARTER_SOURCE_FORMATS:
        payload = {
            "section": _first(record, ["section"]),
            "township": _first(record, ["township"]),
            "range": _first(record, ["range", "range_"]),
        }
        if source_fmt == "CARTER_QUADRANT":
            payload["quadrants"] = _first(
                record,
                ["quadrants", "quadrant", "quarter_calls", "quarter_quadrants"],
            )
        else:
            payload.update(
                {
                    "ns_feet": _first(record, ["ns_feet", "north_south_feet"]),
                    "ns_line": _first(record, ["fsl_fnl", "ns_line"]),
                    "ew_feet": _first(record, ["ew_feet", "east_west_feet"]),
                    "ew_line": _first(record, ["fwl_fel", "ew_line"]),
                }
            )
        return payload
    if FORMATS[source_fmt]["kind"] == "geographic":
        return {
            "lon": _first(record, ["lon", "longitude", "x_lon27", "x_lon83", "x"]),
            "lat": _first(record, ["lat", "latitude", "y_lat27", "y_lat83", "y"]),
        }
    return {
        "x": _first(record, ["x", "easting", "lon", "longitude"]),
        "y": _first(record, ["y", "northing", "lat", "latitude"]),
    }


def detect_source_format(record: Dict[str, Any]) -> str:
    keys = {str(k).strip().lower() for k in record.keys()}
    if "township" in keys and ({"range", "range_"} & keys):
        if {
            "quadrants",
            "quadrant",
            "quarter_calls",
            "quarter_quadrants",
        } & keys:
            return "CARTER_QUADRANT"
        return "CARTER"
    if "y_lat27" in keys or "x_lon27" in keys:
        return "GEOGRAPHIC_NAD27"
    if "lat" in keys and "lon" in keys:
        return "GEOGRAPHIC_NAD27"
    if "latitude" in keys and "longitude" in keys:
        return "GEOGRAPHIC_NAD27"
    raise ValueError("Could not auto-detect source format from columns.")


def result_coordinate_pair(
    target_fmt: str,
    result: Dict[str, Any],
) -> Tuple[Any, Any]:
    """Return the result's x-like and y-like values in that order."""

    kind = FORMATS[target_fmt]["kind"]
    if kind == "geographic":
        return result["lon"], result["lat"]
    if kind == "projected":
        return result["x"], result["y"]
    if "tnspc_nad27_x" in result and "tnspc_nad27_y" in result:
        # Carter is not itself an x/y format, so Carter target results use the
        # Tennessee State Plane NAD27 pair already included in the output.
        return result["tnspc_nad27_x"], result["tnspc_nad27_y"]
    raise ValueError("Converted result did not include a copyable coordinate pair.")


def format_coordinate_for_clipboard(value: Any) -> str:
    """Format one coordinate without adding labels or locale separators."""

    if isinstance(value, float):
        return repr(value)
    return str(value)


def format_coordinate_pair_for_clipboard(
    x: Any,
    y: Any,
    order: str = "xy",
) -> str:
    """Format a comma-separated pair in x,y or y,x order."""

    if order not in {"xy", "yx"}:
        raise ValueError("Coordinate copy order must be 'xy' or 'yx'.")
    first, second = (x, y) if order == "xy" else (y, x)
    return (
        f"{format_coordinate_for_clipboard(first)},"
        f"{format_coordinate_for_clipboard(second)}"
    )


def read_records(path: Path) -> List[Dict[str, Any]]:
    suffix = path.suffix.lower()
    if suffix == ".csv":
        with path.open("r", encoding="utf-8-sig", newline="") as f:
            return list(csv.DictReader(f))
    if suffix == ".json":
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            return data
        if isinstance(data, dict) and isinstance(data.get("records"), list):
            return data["records"]
        raise ValueError("JSON input must be a list of objects or an object with a 'records' list.")
    raise ValueError("Input file must be .csv or .json")


def write_records(path: Path, records: List[Dict[str, Any]]) -> None:
    suffix = path.suffix.lower()
    if suffix == ".json":
        with path.open("w", encoding="utf-8") as f:
            json.dump(records, f, indent=2)
        return
    if suffix == ".csv":
        fieldnames: List[str] = []
        seen = set()
        for row in records:
            for key in row.keys():
                if key not in seen:
                    seen.add(key)
                    fieldnames.append(key)
        with path.open("w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(records)
        return
    raise ValueError("Output file must be .csv or .json")


def batch_convert(converter: CoordinateConverter, input_path: Path, output_path: Path, source_fmt: str, target_fmt: str) -> int:
    input_path = Path(input_path)
    output_path = Path(output_path)

    if not input_path.exists() or not input_path.is_file():
        raise FileNotFoundError(f"Input file not found: {input_path}")
    if input_path.suffix.lower() not in {".csv", ".json"}:
        raise ValueError("Input file must be .csv or .json")
    if output_path.suffix.lower() not in {".csv", ".json"}:
        raise ValueError("Output file must be .csv or .json")
    if not output_path.parent.exists():
        raise FileNotFoundError(f"Output directory not found: {output_path.parent}")
    if input_path.resolve() == output_path.resolve():
        raise ValueError("Input and output files must be different.")

    if target_fmt not in FORMATS:
        raise ValueError(f"Unsupported target format: {target_fmt}")
    if target_fmt not in TARGET_FORMAT_KEYS:
        raise ValueError(f"{FORMATS[target_fmt]['label']} is input-only.")

    records = read_records(input_path)
    if not records:
        write_records(output_path, [])
        return 0

    if source_fmt == "AUTO":
        source_fmt = detect_source_format(records[0])
    elif source_fmt not in FORMATS:
        raise ValueError(f"Unsupported source format: {source_fmt}")

    if source_fmt == target_fmt:
        raise ValueError("Source and target formats are the same. Choose different formats to convert.")

    out_rows = [converter.convert_record(row, source_fmt, target_fmt) for row in records]
    write_records(output_path, out_rows)
    return len(out_rows)


class App:
    def __init__(self, root: tk.Tk, converter: CoordinateConverter):
        self.root = root
        self.converter = converter
        self.map_view = MapViewController(Path(tempfile.gettempdir()) / "tn_coord_converter_mapview.json")
        self.active_map_lon_lat: Optional[Tuple[float, float]] = None
        root.title(APP_TITLE)
        root.geometry("980x760")
        root.minsize(900, 680)

        self.single_source_var = tk.StringVar(value=FORMATS["CARTER"]["label"])
        self.single_target_var = tk.StringVar(value=FORMATS["TNSPC_NAD27"]["label"])
        self.batch_source_var = tk.StringVar(value="AUTO")
        self.batch_target_var = tk.StringVar(value=FORMATS["GEOGRAPHIC_NAD27"]["label"])
        self.input_path_var = tk.StringVar()
        self.output_path_var = tk.StringVar()
        self.active_copy_xy: Optional[Tuple[Any, Any]] = None
        self.active_copy_target_fmt: Optional[str] = None
        self.invert_copy_var = tk.BooleanVar(value=False)
        self.geographic_display_var = tk.StringVar(value="DD")

        self._build_ui()
        self._update_single_mode()
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

    def _build_ui(self) -> None:
        notebook = ttk.Notebook(self.root)
        notebook.pack(fill="both", expand=True, padx=12, pady=12)

        single_tab = ttk.Frame(notebook)
        batch_tab = ttk.Frame(notebook)
        about_tab = ttk.Frame(notebook)
        notebook.add(single_tab, text="Single Conversion")
        notebook.add(batch_tab, text="Batch Conversion")
        notebook.add(about_tab, text="About")

        self._build_single_tab(single_tab)
        self._build_batch_tab(batch_tab)
        self._build_about_tab(about_tab)

    def _build_single_tab(self, parent: ttk.Frame) -> None:
        top = ttk.LabelFrame(parent, text="Conversion Settings")
        top.pack(fill="x", padx=8, pady=8)

        ttk.Label(top, text="Source format").grid(row=0, column=0, sticky="w", padx=6, pady=6)
        src_combo = ttk.Combobox(top, textvariable=self.single_source_var, values=SOURCE_FORMAT_LABELS, state="readonly", width=42)
        src_combo.grid(row=0, column=1, sticky="ew", padx=6, pady=6)
        src_combo.bind("<<ComboboxSelected>>", lambda _e: self._update_single_mode())

        ttk.Label(top, text="Target format").grid(row=0, column=2, sticky="w", padx=6, pady=6)
        tgt_combo = ttk.Combobox(top, textvariable=self.single_target_var, values=TARGET_FORMAT_LABELS, state="readonly", width=42)
        tgt_combo.grid(row=0, column=3, sticky="ew", padx=6, pady=6)
        tgt_combo.bind("<<ComboboxSelected>>", lambda _e: self._on_single_target_changed())
        top.columnconfigure(1, weight=1)
        top.columnconfigure(3, weight=1)

        self.single_inputs_frame = ttk.Frame(parent)
        self.single_inputs_frame.pack(fill="x", padx=8, pady=8)
        self.single_inputs_frame.columnconfigure(0, weight=1)

        self.carter_frame = ttk.LabelFrame(self.single_inputs_frame, text="Carter Coordinate Inputs")
        self.carter_frame.grid(row=0, column=0, sticky="ew")
        for col in (1, 3, 5):
            self.carter_frame.columnconfigure(col, weight=1)

        self.carter_vars = {
            "section": tk.StringVar(),
            "township": tk.StringVar(),
            "range": tk.StringVar(),
            "ns_feet": tk.StringVar(),
            "ns_line": tk.StringVar(value="FSL"),
            "ew_feet": tk.StringVar(),
            "ew_line": tk.StringVar(value="FWL"),
            "quadrants": tk.StringVar(),
        }

        carter_top_fields = [
            ("Section (optional)", "section"),
            ("Township", "township"),
            ("Range", "range"),
        ]
        for idx, (label, key) in enumerate(carter_top_fields):
            ttk.Label(self.carter_frame, text=label).grid(row=0, column=idx * 2, sticky="w", padx=6, pady=6)
            ttk.Entry(self.carter_frame, textvariable=self.carter_vars[key], width=18).grid(
                row=0, column=idx * 2 + 1, sticky="ew", padx=6, pady=6
            )

        self.footage_frame = ttk.LabelFrame(self.carter_frame, text="Footage from Section Lines")
        self.footage_frame.grid(row=1, column=0, columnspan=6, sticky="ew", padx=6, pady=6)
        for col in (1, 3):
            self.footage_frame.columnconfigure(col, weight=1)

        footage_fields = [
            ("N-S Distance", "ns_feet"),
            ("From N-S Line", "ns_line"),
            ("E-W Distance", "ew_feet"),
            ("From E-W Line", "ew_line"),
        ]
        for idx, (label, key) in enumerate(footage_fields):
            row = idx // 2
            col = (idx % 2) * 2
            ttk.Label(self.footage_frame, text=label).grid(row=row, column=col, sticky="w", padx=6, pady=6)
            if key in {"ns_line", "ew_line"}:
                values = ["FSL", "FNL"] if key == "ns_line" else ["FWL", "FEL"]
                widget = ttk.Combobox(
                    self.footage_frame,
                    textvariable=self.carter_vars[key],
                    values=values,
                    state="readonly",
                    width=14,
                )
            else:
                widget = ttk.Entry(
                    self.footage_frame,
                    textvariable=self.carter_vars[key],
                    width=18,
                )
            widget.grid(row=row, column=col + 1, sticky="ew", padx=6, pady=6)

        self.quadrant_frame = ttk.LabelFrame(
            self.carter_frame,
            text="Legacy Quadrant Location",
        )
        self.quadrant_frame.grid(row=1, column=0, columnspan=6, sticky="ew", padx=6, pady=6)
        self.quadrant_frame.columnconfigure(1, weight=1)
        ttk.Label(self.quadrant_frame, text="Quadrants").grid(
            row=0, column=0, sticky="w", padx=6, pady=6
        )
        self.quadrant_entry = ttk.Entry(
            self.quadrant_frame,
            textvariable=self.carter_vars["quadrants"],
            width=30,
        )
        self.quadrant_entry.grid(row=0, column=1, sticky="ew", padx=6, pady=6)
        ttk.Label(
            self.quadrant_frame,
            text=(
                "Calls are smallest to largest: 1 call = largest; 2 calls = middle, largest; "
                "3 calls = smallest, middle, largest. The resolved area center is used. Example: SW NW SE"
            ),
        ).grid(row=1, column=0, columnspan=2, sticky="w", padx=6, pady=(0, 6))

        self.xy_frame = ttk.LabelFrame(self.single_inputs_frame, text="Coordinate Inputs")
        self.xy_frame.grid(row=0, column=0, sticky="ew")
        self.xy_x_label = ttk.Label(self.xy_frame, text="Longitude / X")
        self.xy_y_label = ttk.Label(self.xy_frame, text="Latitude / Y")
        self.xy_x_label.grid(row=0, column=0, sticky="w", padx=6, pady=6)
        self.xy_y_label.grid(row=0, column=2, sticky="w", padx=6, pady=6)
        self.xy_x_var = tk.StringVar()
        self.xy_y_var = tk.StringVar()
        ttk.Entry(self.xy_frame, textvariable=self.xy_x_var, width=28).grid(row=0, column=1, sticky="ew", padx=6, pady=6)
        ttk.Entry(self.xy_frame, textvariable=self.xy_y_var, width=28).grid(row=0, column=3, sticky="ew", padx=6, pady=6)
        self.xy_frame.columnconfigure(1, weight=1)
        self.xy_frame.columnconfigure(3, weight=1)

        button_row = ttk.Frame(parent)
        button_row.pack(fill="x", padx=8, pady=8)
        ttk.Button(button_row, text="Convert", command=self.convert_single).pack(side="left")
        ttk.Button(button_row, text="Clear", command=self.clear_single).pack(side="left", padx=(8, 0))
        self.view_on_map_button = ttk.Button(button_row, text="View on map", command=self.view_on_map, state="disabled")
        self.view_on_map_button.pack(side="left", padx=(8, 0))

        copy_row = ttk.Frame(button_row)
        copy_row.pack(side="right")
        ttk.Label(copy_row, text="Copy format:").pack(side="left", padx=(0, 6))
        self.geographic_display_combo = ttk.Combobox(
            copy_row,
            textvariable=self.geographic_display_var,
            values=GEOGRAPHIC_DISPLAY_FORMATS,
            state="disabled",
            width=20,
        )
        self.geographic_display_combo.pack(side="left", padx=(0, 6))
        self.copy_x_button = ttk.Button(
            copy_row,
            text="Copy X",
            command=lambda: self.copy_coordinate("x"),
            state="disabled",
        )
        self.copy_x_button.pack(side="left")
        self.copy_y_button = ttk.Button(
            copy_row,
            text="Copy Y",
            command=lambda: self.copy_coordinate("y"),
            state="disabled",
        )
        self.copy_y_button.pack(side="left", padx=(6, 0))
        self.copy_pair_button = ttk.Button(
            copy_row,
            text="Copy X,Y",
            command=lambda: self.copy_coordinate("pair"),
            state="disabled",
        )
        self.copy_pair_button.pack(side="left", padx=(6, 0))
        self.invert_copy_checkbox = ttk.Checkbutton(
            copy_row,
            text="Invert",
            variable=self.invert_copy_var,
            command=self.update_copy_pair_label,
        )
        self.invert_copy_checkbox.pack(side="left", padx=(6, 0))

        self.single_output = ScrolledText(parent, height=20, wrap="word")
        self.single_output.pack(fill="both", expand=True, padx=8, pady=8)

    def _build_batch_tab(self, parent: ttk.Frame) -> None:
        settings = ttk.LabelFrame(parent, text="Batch Settings")
        settings.pack(fill="x", padx=8, pady=8)

        ttk.Label(settings, text="Input file (.csv or .json)").grid(row=0, column=0, sticky="w", padx=6, pady=6)
        ttk.Entry(settings, textvariable=self.input_path_var).grid(row=0, column=1, sticky="ew", padx=6, pady=6)
        ttk.Button(settings, text="Browse", command=self.browse_input).grid(row=0, column=2, padx=6, pady=6)

        ttk.Label(settings, text="Output file (.csv or .json)").grid(row=1, column=0, sticky="w", padx=6, pady=6)
        ttk.Entry(settings, textvariable=self.output_path_var).grid(row=1, column=1, sticky="ew", padx=6, pady=6)
        ttk.Button(settings, text="Browse", command=self.browse_output).grid(row=1, column=2, padx=6, pady=6)

        ttk.Label(settings, text="Source format").grid(row=2, column=0, sticky="w", padx=6, pady=6)
        ttk.Combobox(settings, textvariable=self.batch_source_var, values=["AUTO", *SOURCE_FORMAT_LABELS], state="readonly", width=40).grid(row=2, column=1, sticky="w", padx=6, pady=6)

        ttk.Label(settings, text="Target format").grid(row=3, column=0, sticky="w", padx=6, pady=6)
        ttk.Combobox(settings, textvariable=self.batch_target_var, values=TARGET_FORMAT_LABELS, state="readonly", width=40).grid(row=3, column=1, sticky="w", padx=6, pady=6)

        settings.columnconfigure(1, weight=1)

        help_text = (
            "Choose Carter Quadrant or Carter Footage input. Both require township and range; "
            "incomplete areas resolve to their center.\n"
            "Supported geographic-style input columns: lat/lon, latitude/longitude, or y_lat27/x_lon27.\n"
            "For projected coordinates, use generic x and y columns and choose the source format explicitly."
        )
        ttk.Label(parent, text=help_text, justify="left").pack(fill="x", padx=12, pady=(0, 8))

        action_row = ttk.Frame(parent)
        action_row.pack(fill="x", padx=8, pady=8)
        ttk.Button(action_row, text="Run Batch Conversion", command=self.run_batch).pack(side="left")

        self.batch_output = tk.Text(parent, height=22, wrap="word")
        self.batch_output.pack(fill="both", expand=True, padx=8, pady=8)

    def _build_about_tab(self, parent: ttk.Frame) -> None:
        navigation = ttk.Frame(parent)
        navigation.pack(fill="x", padx=8, pady=(8, 0))
        self.about_back_button = ttk.Button(
            navigation,
            text="Back",
            command=lambda: self._navigate_about_history(-1),
            state="disabled",
        )
        self.about_back_button.pack(side="left")
        self.about_forward_button = ttk.Button(
            navigation,
            text="Forward",
            command=lambda: self._navigate_about_history(1),
            state="disabled",
        )
        self.about_forward_button.pack(side="left", padx=(6, 0))
        self.about_title_var = tk.StringVar(value=README_FILENAME)
        ttk.Label(navigation, textvariable=self.about_title_var).pack(
            side="left", padx=(12, 0)
        )

        text = ScrolledText(
            parent,
            wrap="word",
            padx=18,
            pady=14,
            borderwidth=0,
            highlightthickness=0,
        )
        text.pack(fill="both", expand=True, padx=8, pady=8)
        self.about_text = text
        self.about_history: List[Path] = []
        self.about_history_index = -1
        self.about_current_path: Optional[Path] = None

        base_font = tkfont.nametofont("TkDefaultFont").copy()
        fixed_font = tkfont.nametofont("TkFixedFont").copy()
        base_size = abs(int(base_font.cget("size")))
        heading1_font = base_font.copy()
        heading1_font.configure(size=base_size + 8, weight="bold")
        heading2_font = base_font.copy()
        heading2_font.configure(size=base_size + 5, weight="bold")
        heading3_font = base_font.copy()
        heading3_font.configure(size=base_size + 2, weight="bold")
        strong_font = base_font.copy()
        strong_font.configure(weight="bold")
        table_title_font = base_font.copy()
        table_title_font.configure(weight="bold")
        table_label_font = base_font.copy()
        table_label_font.configure(weight="bold")

        # Retain references to the copied Tk fonts for the life of the window.
        self.about_fonts = (
            base_font,
            fixed_font,
            heading1_font,
            heading2_font,
            heading3_font,
            strong_font,
            table_title_font,
            table_label_font,
        )

        text.configure(font=base_font)
        text.tag_configure(
            "heading1",
            font=heading1_font,
            foreground="#17365D",
            spacing1=8,
            spacing3=10,
        )
        text.tag_configure(
            "heading2",
            font=heading2_font,
            foreground="#1F4E79",
            spacing1=14,
            spacing3=7,
        )
        text.tag_configure(
            "heading3",
            font=heading3_font,
            foreground="#2F5597",
            spacing1=10,
            spacing3=5,
        )
        text.tag_configure("strong", font=strong_font)
        text.tag_configure(
            "inline_code",
            font=fixed_font,
            background="#EEF1F4",
        )
        text.tag_configure(
            "code_block",
            font=fixed_font,
            background="#F3F5F7",
            lmargin1=18,
            lmargin2=18,
            rmargin=18,
            spacing1=2,
            spacing3=2,
        )
        text.tag_configure(
            "link",
            foreground="#0563C1",
            underline=True,
        )
        text.tag_bind("link", "<Enter>", lambda _event: text.configure(cursor="hand2"))
        text.tag_bind("link", "<Leave>", lambda _event: text.configure(cursor="arrow"))
        text.tag_configure(
            "list_marker",
            foreground="#1F4E79",
            lmargin1=12,
        )
        text.tag_configure(
            "table_title",
            font=table_title_font,
            foreground="#17365D",
            spacing1=4,
        )
        text.tag_configure("table_label", font=table_label_font)
        text.tag_configure("markdown_image", justify="center", spacing1=6, spacing3=6)
        text.tag_configure(
            "image_error",
            foreground="#7F6000",
            lmargin1=18,
            lmargin2=18,
            spacing1=6,
            spacing3=6,
        )

        readme_text, readme_asset_directory = resolve_readme_document()
        readme_path = (
            (readme_asset_directory / README_FILENAME).resolve()
            if readme_asset_directory is not None
            else None
        )
        self._display_about_document(readme_text, readme_path, record_history=True)

    def _display_about_document(
        self,
        markdown_text: str,
        document_path: Optional[Path],
        *,
        record_history: bool,
    ) -> None:
        if document_path is not None:
            document_path = Path(document_path).resolve()
        if record_history and document_path is not None:
            self.about_history = self.about_history[: self.about_history_index + 1]
            self.about_history.append(document_path)
            self.about_history_index = len(self.about_history) - 1

        self.about_current_path = document_path
        self.about_title_var.set(document_path.name if document_path else "Help")
        self.about_text.configure(state="normal")
        for tag_name in self.about_text.tag_names():
            if tag_name.startswith("markdown_link_"):
                self.about_text.tag_delete(tag_name)
        self.about_text.delete("1.0", "end")
        setattr(self.about_text, "_markdown_image_references", [])
        setattr(self.about_text, "_markdown_link_serial", 0)
        render_markdown(
            self.about_text,
            markdown_text,
            document_path.parent if document_path is not None else None,
            self._open_about_link,
        )
        self.about_text.configure(state="disabled")
        self.about_text.yview_moveto(0.0)
        self._update_about_navigation_buttons()

    def _load_about_document(self, path: Path, *, record_history: bool) -> bool:
        path = Path(path).resolve()
        try:
            markdown_text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            messagebox.showerror(APP_TITLE, f"Could not open help document:\n{path}\n\n{exc}")
            return False
        self._display_about_document(
            markdown_text,
            path,
            record_history=record_history,
        )
        return True

    def _update_about_navigation_buttons(self) -> None:
        can_go_back = self.about_history_index > 0
        can_go_forward = self.about_history_index + 1 < len(self.about_history)
        self.about_back_button.configure(state="normal" if can_go_back else "disabled")
        self.about_forward_button.configure(
            state="normal" if can_go_forward else "disabled"
        )

    def _navigate_about_history(self, offset: int) -> None:
        target_index = self.about_history_index + offset
        if not (0 <= target_index < len(self.about_history)):
            return
        previous_index = self.about_history_index
        self.about_history_index = target_index
        if not self._load_about_document(
            self.about_history[target_index],
            record_history=False,
        ):
            self.about_history_index = previous_index
            self._update_about_navigation_buttons()

    def _scroll_about_fragment(self, fragment: str) -> None:
        heading_text = unquote(fragment).replace("-", " ").strip()
        if not heading_text:
            self.about_text.yview_moveto(0.0)
            return
        position = self.about_text.search(
            heading_text,
            "1.0",
            stopindex="end",
            nocase=True,
        )
        if position:
            self.about_text.see(position)

    def _open_about_link(self, target: str) -> None:
        parsed = urlsplit(target)
        if parsed.scheme and not Path(target).is_absolute():
            try:
                opened = webbrowser.open(target, new=2)
                if not opened:
                    raise RuntimeError("No application accepted the link.")
            except Exception as exc:
                messagebox.showerror(APP_TITLE, f"Could not open link:\n{target}\n\n{exc}")
            return

        relative_path = unquote(parsed.path)
        if not relative_path:
            self._scroll_about_fragment(parsed.fragment)
            return
        if self.about_current_path is None:
            messagebox.showerror(APP_TITLE, f"Could not resolve local link: {target}")
            return

        local_path = Path(relative_path)
        if not local_path.is_absolute():
            local_path = self.about_current_path.parent / local_path
        local_path = local_path.resolve()
        if not local_path.is_file():
            messagebox.showerror(APP_TITLE, f"Linked file was not found:\n{local_path}")
            return

        if local_path.suffix.lower() == ".md":
            if self._load_about_document(local_path, record_history=True):
                self._scroll_about_fragment(parsed.fragment)
            return

        try:
            open_path_with_default_application(local_path)
        except (OSError, RuntimeError) as exc:
            messagebox.showerror(
                APP_TITLE,
                f"Could not open linked file:\n{local_path}\n\n{exc}",
            )

    def _update_single_mode(self) -> None:
        source_key = FORMAT_LABEL_TO_KEY.get(self.single_source_var.get(), self.single_source_var.get())
        if source_key in CARTER_SOURCE_FORMATS:
            self.carter_frame.configure(text=f"{FORMATS[source_key]['label']} Inputs")
            self.xy_frame.grid_remove()
            self.carter_frame.grid()
            if source_key == "CARTER_QUADRANT":
                self.footage_frame.grid_remove()
                self.quadrant_frame.grid()
            else:
                self.quadrant_frame.grid_remove()
                self.footage_frame.grid()
            self.xy_x_label.configure(text="Longitude / X")
            self.xy_y_label.configure(text="Latitude / Y")
        else:
            self.carter_frame.grid_remove()
            self.xy_frame.grid()
            fmt = FORMATS[source_key]
            if fmt["kind"] == "geographic":
                self.xy_x_label.configure(text="Longitude")
                self.xy_y_label.configure(text="Latitude")
            else:
                self.xy_x_label.configure(text="X / Easting")
                self.xy_y_label.configure(text="Y / Northing")
            self.xy_frame.configure(text=f"Coordinate Inputs for {fmt['label']}")

    def _on_single_target_changed(self) -> None:
        self._clear_active_copy_pair()
        self._clear_active_map_point()
        target_fmt = FORMAT_LABEL_TO_KEY.get(
            self.single_target_var.get(), self.single_target_var.get()
        )
        is_geographic = target_fmt in FORMATS and FORMATS[target_fmt]["kind"] == "geographic"
        self.geographic_display_combo.configure(
            state="readonly" if is_geographic else "disabled"
        )
        self.update_copy_pair_label()

    def _crs_metadata(self, fmt_key: str) -> Optional[Dict[str, Any]]:
        fmt = FORMATS[fmt_key]
        if fmt["kind"] == "carter":
            return None

        crs = CRS.from_user_input(fmt["crs"])
        epsg = crs.to_epsg()
        if epsg is not None:
            epsg_text = f"EPSG:{epsg}"
        else:
            epsg_text = str(fmt["crs"])

        axis_units = [axis.unit_name for axis in crs.axis_info if axis.unit_name]
        if not axis_units:
            units: Any = None
        elif len(set(axis_units)) == 1:
            units = axis_units[0]
        else:
            units = axis_units

        if crs.is_geographic:
            projection_name = "Geographic (unprojected)"
        elif crs.coordinate_operation is not None:
            projection_name = crs.coordinate_operation.name
        else:
            projection_name = crs.name

        return {
            "epsg_code": epsg_text,
            "projection_name": projection_name,
            "units": units,
        }

    def _single_output_payload(
        self,
        source_fmt: str,
        target_fmt: str,
        input_values: Dict[str, Any],
        output_values: Dict[str, Any],
    ) -> Dict[str, Any]:
        display_outputs = dict(output_values)
        if source_fmt in CARTER_SOURCE_FORMATS and target_fmt != "CARTER":
            carter_input_keys = {
                "section",
                "township",
                "range",
                "ns_feet",
                "ns_line",
                "ew_feet",
                "ew_line",
                "cartercord",
                "quadrants",
                "quadrant_order",
                "quadrant_point",
                "nad27_lon",
                "nad27_lat",
            }
            display_outputs = {k: v for k, v in display_outputs.items() if k not in carter_input_keys}

        source_meta: Dict[str, Any] = {
            "format": source_fmt,
            "format_label": FORMATS[source_fmt]["label"],
        }
        source_crs = self._crs_metadata(source_fmt)
        if source_crs is not None:
            source_meta["pyproj"] = source_crs

        target_meta: Dict[str, Any] = {
            "format": target_fmt,
            "format_label": FORMATS[target_fmt]["label"],
        }
        target_crs = self._crs_metadata(target_fmt)
        if target_crs is not None:
            target_meta["pyproj"] = target_crs

        return {
            "inputs": {
                "source": source_meta,
                "target": target_meta,
                "values": input_values,
            },
            "outputs": {
                "values": display_outputs,
            },
        }

    def _clear_active_map_point(self) -> None:
        self.active_map_lon_lat = None
        self.view_on_map_button.configure(state="disabled")

    def _clear_active_copy_pair(self) -> None:
        self.active_copy_xy = None
        self.active_copy_target_fmt = None
        self.copy_x_button.configure(state="disabled")
        self.copy_y_button.configure(state="disabled")
        self.copy_pair_button.configure(state="disabled")

    def _update_copy_pair_from_result(
        self,
        target_fmt: str,
        result: Dict[str, Any],
    ) -> None:
        try:
            self.active_copy_xy = result_coordinate_pair(target_fmt, result)
        except (KeyError, ValueError):
            self._clear_active_copy_pair()
            return
        self.active_copy_target_fmt = target_fmt
        self.geographic_display_combo.configure(
            state="readonly" if FORMATS[target_fmt]["kind"] == "geographic" else "disabled"
        )
        self.copy_x_button.configure(state="normal")
        self.copy_y_button.configure(state="normal")
        self.copy_pair_button.configure(state="normal")
        self.update_copy_pair_label()

    def update_copy_pair_label(self) -> None:
        target_fmt = self.active_copy_target_fmt
        if target_fmt is None:
            target_fmt = FORMAT_LABEL_TO_KEY.get(
                self.single_target_var.get(), self.single_target_var.get()
            )
        geographic = target_fmt in FORMATS and FORMATS[target_fmt]["kind"] == "geographic"
        x_label, y_label = ("Lon", "Lat") if geographic else ("X", "Y")
        self.copy_x_button.configure(text=f"Copy {x_label}")
        self.copy_y_button.configure(text=f"Copy {y_label}")
        label = (
            f"{y_label},{x_label}"
            if self.invert_copy_var.get()
            else f"{x_label},{y_label}"
        )
        self.copy_pair_button.configure(text=f"Copy {label}")

    def copy_coordinate(self, component: str) -> None:
        if self.active_copy_xy is None:
            return
        x, y = self.active_copy_xy
        geographic = (
            self.active_copy_target_fmt is not None
            and FORMATS[self.active_copy_target_fmt]["kind"] == "geographic"
        )
        if geographic:
            output_format = self.geographic_display_var.get()
            x_text = format_geographic_coordinate_for_clipboard(x, "lon", output_format)
            y_text = format_geographic_coordinate_for_clipboard(y, "lat", output_format)
        else:
            x_text = format_coordinate_for_clipboard(x)
            y_text = format_coordinate_for_clipboard(y)
        if component == "x":
            text = x_text
        elif component == "y":
            text = y_text
        elif component == "pair":
            first, second = (
                (y_text, x_text) if self.invert_copy_var.get() else (x_text, y_text)
            )
            text = f"{first},{second}"
        else:
            raise ValueError(f"Unsupported coordinate component: {component}")
        self.root.clipboard_clear()
        self.root.clipboard_append(text)
        self.root.update_idletasks()

    def _result_to_wgs84_lon_lat(self, target_fmt: str, result: Dict[str, Any]) -> Tuple[float, float]:
        if "lon" in result and "lat" in result:
            lon = float(result["lon"])
            lat = float(result["lat"])
            source_geo_fmt = target_fmt
        elif "nad27_lon" in result and "nad27_lat" in result:
            lon = float(result["nad27_lon"])
            lat = float(result["nad27_lat"])
            source_geo_fmt = "GEOGRAPHIC_NAD27"
        elif "x" in result and "y" in result:
            lon, lat = self.converter.project(float(result["x"]), float(result["y"]), target_fmt, "GEOGRAPHIC_WGS84")
            source_geo_fmt = "GEOGRAPHIC_WGS84"
        else:
            raise ValueError("Converted result did not include plottable coordinates.")

        if source_geo_fmt != "GEOGRAPHIC_WGS84":
            lon, lat = self.converter.project(lon, lat, source_geo_fmt, "GEOGRAPHIC_WGS84")
        return lon, lat

    def _update_map_point_from_result(self, target_fmt: str, result: Dict[str, Any]) -> None:
        try:
            lon, lat = self._result_to_wgs84_lon_lat(target_fmt, result)
        except Exception:
            self._clear_active_map_point()
            return

        if not (-180 <= lon <= 180 and -90 <= lat <= 90):
            self._clear_active_map_point()
            return

        self.active_map_lon_lat = (lon, lat)
        self.view_on_map_button.configure(state="normal")

    def view_on_map(self) -> None:
        if self.active_map_lon_lat is None:
            messagebox.showinfo(APP_TITLE, 'Run a conversion first, then click "View on map".')
            return

        lon, lat = self.active_map_lon_lat
        try:
            self.map_view.open_or_update(lon, lat)
        except Exception as exc:
            messagebox.showerror(APP_TITLE, str(exc))
            return

    def clear_single(self) -> None:
        for var in self.carter_vars.values():
            if isinstance(var, tk.StringVar):
                var.set("")
        self.carter_vars["ns_line"].set("FSL")
        self.carter_vars["ew_line"].set("FWL")
        self.xy_x_var.set("")
        self.xy_y_var.set("")
        self.geographic_display_var.set("DD")
        self.invert_copy_var.set(False)
        self.update_copy_pair_label()
        self.single_output.delete("1.0", "end")
        self._clear_active_map_point()
        self._clear_active_copy_pair()

    def convert_single(self) -> None:
        try:
            source_fmt = FORMAT_LABEL_TO_KEY.get(self.single_source_var.get(), self.single_source_var.get())
            target_fmt = FORMAT_LABEL_TO_KEY.get(self.single_target_var.get(), self.single_target_var.get())
            if source_fmt not in FORMATS:
                raise ValueError(f"Unsupported source format: {source_fmt}")
            if target_fmt not in FORMATS:
                raise ValueError(f"Unsupported target format: {target_fmt}")
            if source_fmt == target_fmt:
                raise ValueError("Source and target formats are the same. Choose different formats to convert.")

            if source_fmt in CARTER_SOURCE_FORMATS:
                common_carter_payload = {
                    "section": self.carter_vars["section"].get(),
                    "township": self.carter_vars["township"].get(),
                    "range": self.carter_vars["range"].get(),
                }
                if source_fmt == "CARTER_QUADRANT":
                    payload = {
                        **common_carter_payload,
                        "quadrants": self.carter_vars["quadrants"].get(),
                    }
                else:
                    payload = {
                        **common_carter_payload,
                        "ns_feet": self.carter_vars["ns_feet"].get(),
                        "ns_line": self.carter_vars["ns_line"].get(),
                        "ew_feet": self.carter_vars["ew_feet"].get(),
                        "ew_line": self.carter_vars["ew_line"].get(),
                    }
            elif FORMATS[source_fmt]["kind"] == "geographic":
                payload = {"lon": self.xy_x_var.get(), "lat": self.xy_y_var.get()}
            else:
                payload = {"x": self.xy_x_var.get(), "y": self.xy_y_var.get()}

            result = self.converter.convert_single(source_fmt, target_fmt, payload)
            display = self._single_output_payload(source_fmt, target_fmt, payload, result)
            self.single_output.delete("1.0", "end")
            self.single_output.insert("1.0", json.dumps(display, indent=2))
            self.single_output.see("end")
            self._update_copy_pair_from_result(target_fmt, result)
            self._update_map_point_from_result(target_fmt, result)
        except Exception as exc:
            self._clear_active_map_point()
            self._clear_active_copy_pair()
            messagebox.showerror(APP_TITLE, str(exc))

    def on_close(self) -> None:
        self.map_view.close()
        self.root.destroy()

    def browse_input(self) -> None:
        path = filedialog.askopenfilename(filetypes=[("Data files", "*.csv *.json"), ("All files", "*.*")])
        if path:
            self.input_path_var.set(path)
            if not self.output_path_var.get():
                suffix = Path(path).suffix.lower()
                self.output_path_var.set(str(Path(path).with_name(Path(path).stem + "_converted" + suffix)))

    def browse_output(self) -> None:
        path = filedialog.asksaveasfilename(defaultextension=".csv", filetypes=[("CSV", "*.csv"), ("JSON", "*.json")])
        if path:
            self.output_path_var.set(path)

    def run_batch(self) -> None:
        try:
            input_text = self.input_path_var.get().strip()
            output_text = self.output_path_var.get().strip()
            if not input_text:
                raise ValueError("Input file is required.")
            if not output_text:
                raise ValueError("Output file is required.")

            input_path = Path(input_text)
            output_path = Path(output_text)
            src_value = self.batch_source_var.get()
            source_fmt = "AUTO" if src_value == "AUTO" else FORMAT_LABEL_TO_KEY.get(src_value, src_value)
            target_fmt = FORMAT_LABEL_TO_KEY.get(self.batch_target_var.get(), self.batch_target_var.get())
            if source_fmt != "AUTO" and source_fmt == target_fmt:
                raise ValueError("Source and target formats are the same. Choose different formats to convert.")
            count = batch_convert(self.converter, input_path, output_path, source_fmt, target_fmt)
            self.batch_output.delete("1.0", "end")
            self.batch_output.insert("1.0", f"Converted {count} record(s).\nOutput written to:\n{output_path}")
            messagebox.showinfo(APP_TITLE, f"Converted {count} record(s).")
        except Exception as exc:
            messagebox.showerror(APP_TITLE, str(exc))


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=APP_TITLE)
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    parser.add_argument("--input", help="Input CSV or JSON file for batch conversion")
    parser.add_argument("--output", help="Output CSV or JSON file for batch conversion")
    parser.add_argument("--source-format", default="AUTO", choices=["AUTO", *FORMATS.keys()], help="Source coordinate format for batch conversion")
    parser.add_argument("--target-format", choices=TARGET_FORMAT_KEYS, help="Target coordinate format for batch conversion")
    parser.add_argument("--no-gui", action="store_true", help="Run without the Tkinter GUI")
    parser.add_argument("--mapview-browser", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument(
        "--mapview-command-file",
        default=str(Path(tempfile.gettempdir()) / "tn_coord_converter_mapview.json"),
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--mapview-scale-bin",
        default=MAPVIEW_DEFAULT_SCALE_BIN,
        help=argparse.SUPPRESS,
    )
    return parser


def run_mapview_child(command_file: str, scale_bin: str) -> int:
    """Run the bundled pywebview child process used by the main GUI."""

    error_path = Path(command_file).with_suffix(".mapview-error.log")
    try:
        error_path.unlink(missing_ok=True)
        from ngmdb_mapview_window import run_browser

        run_browser(command_file, scale_bin)
        return 0
    except Exception:
        error_path.write_text(traceback.format_exc(), encoding="utf-8")
        if sys.stderr is not None:
            print(
                f"MapView failed. Details were written to {error_path}",
                file=sys.stderr,
            )
        return 1


def main() -> int:
    parser = build_arg_parser()
    args = parser.parse_args()

    if args.mapview_browser:
        return run_mapview_child(
            args.mapview_command_file,
            args.mapview_scale_bin,
        )

    converter = CoordinateConverter()

    if args.no_gui or args.input or args.output or args.target_format:
        if not (args.input and args.output and args.target_format):
            parser.error("Batch mode requires --input, --output, and --target-format")
        count = batch_convert(converter, Path(args.input), Path(args.output), args.source_format, args.target_format)
        print(f"Converted {count} record(s) to {args.output}")
        return 0

    if tk is None:
        parser.error("Tkinter is not available in this Python environment. Use batch mode or install Tk support.")

    root = tk.Tk()
    App(root, converter)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
