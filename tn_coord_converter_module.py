#!/usr/bin/env python3
"""
Standalone Tennessee Carter coordinate and NAD27 latitude/longitude converter.

This module has no third-party dependencies and does not use a lookup table.
The Carter grid is generated arithmetically, and one-minute ground distances
are calculated on the Clarke 1866 ellipsoid used by NAD27.

Example
-------
tn_coord_converter_module.py normal use is:

    from tn_coord_converter_module import carter_to_nad27

    coordinate = carter_to_nad27(
        section=11,
        township="2S",
        range_="47E",
        ns_feet=1750,
        ns_line="FSL",
        ew_feet=1900,
        ew_line="FWL",
    )
    print(coordinate.nad27_lat, coordinate.nad27_lon)

The result is a NamedTuple, so it can also be unpacked:

    latitude, longitude = coordinate

Reverse conversion is available through ``nad27_to_carter(latitude, longitude)``.
"""

from __future__ import annotations

import math
import re
from typing import Any, Dict, NamedTuple, Tuple

__all__ = [
    "CarterCoordinate",
    "MinuteDimensions",
    "NAD27Coordinate",
    "carter_to_nad27",
    "feet_per_minute",
    "nad27_to_carter",
    "section_southwest_corner",
]

# NAD27 uses the Clarke 1866 ellipsoid.
_CLARKE_1866_SEMIMAJOR_METERS = 6_378_206.4
_CLARKE_1866_INVERSE_FLATTENING = 294.9786982
_RADIANS_PER_MINUTE = math.pi / 10_800.0

# Carter footage is expressed in U.S. survey feet.
_US_SURVEY_FEET_PER_METER = 3_937.0 / 1_200.0

# The southwest corner of Carter Township 19S, Range 1E is
# 34 degrees 55 minutes N, 89 degrees 30 minutes W.
_TOWNSHIP_19S_SOUTH_MINUTES = 34 * 60 + 55
_RANGE_1E_WEST_MINUTES = -(89 * 60 + 30)

_TOWNSHIP_RE = re.compile(r"^([1-9]|1[0-9])S$")
_RANGE_RE = re.compile(r"^([1-9][0-9]*)([EW])$")


# Valid range-block indexes for each Tennessee Carter township.  Range 1E has
# index 0, Range 2E index 1, and Range 1W index -1.  This compact outline
# replaces 43,600 individual minute-minute Carter-keys while retaining its coverage
# checks.
_VALID_RANGE_INTERVALS: Dict[str, Tuple[Tuple[int, int], ...]] = {
    "19S": ((-10, 15), (26, 62)),
    "18S": ((-10, 62),),
    "17S": ((-9, 62),),
    "16S": ((-8, 64),),
    "15S": ((-9, 65),),
    "14S": ((-9, 65),),
    "13S": ((-9, 67),),
    "12S": ((-7, 72),),
    "11S": ((-6, 74),),
    "10S": ((-6, 76),),
    "9S": ((-6, 78),),
    "8S": ((-4, 79),),
    "7S": ((-3, 80), (82, 84)),
    "6S": ((-3, 85),),
    "5S": ((-3, 89),),
    "4S": ((-3, 90),),
    "3S": ((-3, 91),),
    "2S": ((-2, 93),),
    "1S": ((-1, 93),),
    "A": ((1, 93),),
    "B": ((17, 94),),
    "C": ((17, 19),),
}


class MinuteDimensions(NamedTuple):
    """Ground length of one minute of latitude and longitude, in survey feet."""

    latitude_feet: float
    longitude_feet: float


class NAD27Coordinate(NamedTuple):
    """NAD27 geographic coordinate in decimal degrees."""

    nad27_lat: float
    nad27_lon: float

    @property
    def latitude(self) -> float:
        return self.nad27_lat

    @property
    def longitude(self) -> float:
        return self.nad27_lon

    def as_dict(self) -> Dict[str, float]:
        return {
            "nad27_lat": self.nad27_lat,
            "nad27_lon": self.nad27_lon,
        }


class CarterCoordinate(NamedTuple):
    """Carter coordinate and its source NAD27 decimal-degree coordinate."""

    section: int
    township: str
    range_: str
    ns_feet: float
    ns_line: str
    ew_feet: float
    ew_line: str
    nad27_lat: float
    nad27_lon: float

    @property
    def cartercord(self) -> str:
        return f"{self.section}-{self.township}-{self.range_}"

    def as_dict(self) -> Dict[str, Any]:
        return {
            "section": self.section,
            "township": self.township,
            "range": self.range_,
            "ns_feet": self.ns_feet,
            "ns_line": self.ns_line,
            "ew_feet": self.ew_feet,
            "ew_line": self.ew_line,
            "cartercord": self.cartercord,
            "nad27_lat": self.nad27_lat,
            "nad27_lon": self.nad27_lon,
        }


def _normalize_text(value: Any) -> str:
    return str(value).strip().upper()


def _parse_section(section: Any) -> int:
    text = str(section).strip()
    try:
        parsed = int(text)
    except (TypeError, ValueError) as exc:
        raise ValueError("Section must be a whole number from 1 through 25.") from exc
    if str(parsed) != text.lstrip("+") or not 1 <= parsed <= 25:
        raise ValueError("Section must be a whole number from 1 through 25.")
    return parsed


def _township_index(township: Any) -> Tuple[str, int]:
    normalized = _normalize_text(township)
    match = _TOWNSHIP_RE.fullmatch(normalized)
    if match:
        number = int(match.group(1))
        if number > 19:
            raise ValueError("Carter township must be 1S through 19S, A, B, or C.")
        return normalized, 19 - number
    if normalized in {"A", "B", "C"}:
        return normalized, 19 + (ord(normalized) - ord("A"))
    raise ValueError("Carter township must be 1S through 19S, A, B, or C.")


def _range_index(range_: Any) -> Tuple[str, int]:
    normalized = _normalize_text(range_)
    match = _RANGE_RE.fullmatch(normalized)
    if not match:
        raise ValueError("Carter range must be a positive number followed by E or W.")
    number = int(match.group(1))
    direction = match.group(2)
    index = number - 1 if direction == "E" else -number
    return normalized, index


def _validate_carter_key(township: str, range_index: int, range_: str) -> None:
    intervals = _VALID_RANGE_INTERVALS[township]
    if not any(start <= range_index <= end for start, end in intervals):
        raise ValueError(
            f"Carter township/range is outside the supported Tennessee coverage: "
            f"{township}, {range_}."
        )


def _finite_nonnegative(name: str, value: Any) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be a number.") from exc
    if not math.isfinite(parsed):
        raise ValueError(f"{name} must be finite.")
    if parsed < 0.0:
        raise ValueError(f"{name} cannot be negative.")
    return parsed


def feet_per_minute(latitude: Any) -> MinuteDimensions:
    """
    Return local one-minute latitude/longitude lengths in U.S. survey feet.

    ``latitude`` is an NAD27 latitude in decimal degrees.  The calculation
    uses the meridional and prime-vertical radii of curvature of the Clarke
    1866 ellipsoid.  It is therefore useful independently of Carter section
    conversion.
    """

    try:
        latitude = float(latitude)
    except (TypeError, ValueError) as exc:
        raise ValueError("Latitude must be a number in decimal degrees.") from exc
    if not math.isfinite(latitude) or not -90.0 < latitude < 90.0:
        raise ValueError("Latitude must be finite and strictly between -90 and 90.")

    flattening = 1.0 / _CLARKE_1866_INVERSE_FLATTENING
    eccentricity_squared = 2.0 * flattening - flattening * flattening
    latitude_radians = math.radians(latitude)
    sin_latitude = math.sin(latitude_radians)
    denominator = 1.0 - eccentricity_squared * sin_latitude * sin_latitude

    meridional_radius = (
        _CLARKE_1866_SEMIMAJOR_METERS
        * (1.0 - eccentricity_squared)
        / denominator**1.5
    )
    prime_vertical_radius = (
        _CLARKE_1866_SEMIMAJOR_METERS / math.sqrt(denominator)
    )

    latitude_meters = meridional_radius * _RADIANS_PER_MINUTE
    longitude_meters = (
        prime_vertical_radius
        * math.cos(latitude_radians)
        * _RADIANS_PER_MINUTE
    )
    return MinuteDimensions(
        latitude_feet=latitude_meters * _US_SURVEY_FEET_PER_METER,
        longitude_feet=longitude_meters * _US_SURVEY_FEET_PER_METER,
    )


def section_southwest_corner(
    section: Any,
    township: Any,
    range_: Any,
    *,
    validate_tennessee_coverage: bool = True,
) -> NAD27Coordinate:
    """
    Return the exact NAD27 southwest corner of a Carter one-minute section.

    Set ``validate_tennessee_coverage`` to ``False`` only when intentionally
    extending the regular Carter grid beyond the supported Tennessee coverage.
    """

    section_number = _parse_section(section)
    township_name, township_index = _township_index(township)
    range_name, range_index = _range_index(range_)
    if validate_tennessee_coverage:
        _validate_carter_key(township_name, range_index, range_name)

    # Carter sections snake east/west through five rows:
    #   5  4  3  2  1
    #   6  7  8  9 10
    #  15 14 13 12 11
    #  16 17 18 19 20
    #  25 24 23 22 21
    row_from_south, position = divmod(25 - section_number, 5)
    column_from_west = position if row_from_south % 2 == 0 else 4 - position

    latitude_minutes = (
        _TOWNSHIP_19S_SOUTH_MINUTES
        + township_index * 5
        + row_from_south
    )
    longitude_minutes = (
        _RANGE_1E_WEST_MINUTES
        + range_index * 5
        + column_from_west
    )
    return NAD27Coordinate(
        nad27_lat=latitude_minutes / 60.0,
        nad27_lon=longitude_minutes / 60.0,
    )


def carter_to_nad27(
    section: Any,
    township: Any,
    range_: Any,
    ns_feet: Any,
    ns_line: Any,
    ew_feet: Any,
    ew_line: Any,
    *,
    validate_tennessee_coverage: bool = True,
) -> NAD27Coordinate:
    """
    Convert one Tennessee Carter coordinate to NAD27 decimal degrees.

    ``ns_line`` must be ``FSL`` or ``FNL``.  ``ew_line`` must be ``FWL`` or
    ``FEL``.  Footages are checked against the calculated one-minute section
    dimensions so a result cannot silently fall outside its Carter section.
    """

    southwest = section_southwest_corner(
        section,
        township,
        range_,
        validate_tennessee_coverage=validate_tennessee_coverage,
    )
    ns_footage = _finite_nonnegative("NS footage", ns_feet)
    ew_footage = _finite_nonnegative("EW footage", ew_feet)
    normalized_ns_line = _normalize_text(ns_line)
    normalized_ew_line = _normalize_text(ew_line)
    if normalized_ns_line not in {"FSL", "FNL"}:
        raise ValueError("NS line must be FSL or FNL.")
    if normalized_ew_line not in {"FWL", "FEL"}:
        raise ValueError("EW line must be FWL or FEL.")

    dimensions = feet_per_minute(southwest.nad27_lat)
    if ns_footage > dimensions.latitude_feet:
        raise ValueError(
            f"NS footage ({ns_footage:g}) exceeds this section's calculated "
            f"height ({dimensions.latitude_feet:.3f} survey feet)."
        )
    if ew_footage > dimensions.longitude_feet:
        raise ValueError(
            f"EW footage ({ew_footage:g}) exceeds this section's calculated "
            f"width ({dimensions.longitude_feet:.3f} survey feet)."
        )

    north_fraction = ns_footage / dimensions.latitude_feet
    if normalized_ns_line == "FNL":
        north_fraction = 1.0 - north_fraction

    east_fraction = ew_footage / dimensions.longitude_feet
    if normalized_ew_line == "FEL":
        east_fraction = 1.0 - east_fraction

    return NAD27Coordinate(
        nad27_lat=southwest.nad27_lat + north_fraction / 60.0,
        nad27_lon=southwest.nad27_lon + east_fraction / 60.0,
    )


def nad27_to_carter(nad27_lat: Any, nad27_lon: Any) -> CarterCoordinate:
    """
    Convert NAD27 decimal degrees to the containing Tennessee Carter section.

    The returned footages use the nearest section line, matching the GUI's
    existing convention: FSL/FNL for north-south footage and FWL/FEL for
    east-west footage.
    """

    try:
        latitude = float(nad27_lat)
        longitude = float(nad27_lon)
    except (TypeError, ValueError) as exc:
        raise ValueError("NAD27 latitude and longitude must be numbers.") from exc
    if not math.isfinite(latitude) or not math.isfinite(longitude):
        raise ValueError("NAD27 latitude and longitude must be finite.")
    if not -90.0 <= latitude <= 90.0:
        raise ValueError("NAD27 latitude must be between -90 and 90.")
    if not -180.0 <= longitude <= 180.0:
        raise ValueError("NAD27 longitude must be between -180 and 180.")

    latitude_minute = math.floor(latitude * 60.0)
    longitude_minute = math.floor(longitude * 60.0)

    township_index, row_from_south = divmod(
        latitude_minute - _TOWNSHIP_19S_SOUTH_MINUTES,
        5,
    )
    if 0 <= township_index <= 18:
        township = f"{19 - township_index}S"
    elif 19 <= township_index <= 21:
        township = chr(ord("A") + township_index - 19)
    else:
        raise ValueError(
            f"No Tennessee Carter section contains NAD27 coordinate "
            f"({latitude:.8f}, {longitude:.8f})."
        )

    range_index, column_from_west = divmod(
        longitude_minute - _RANGE_1E_WEST_MINUTES,
        5,
    )
    range_ = f"{-range_index}W" if range_index < 0 else f"{range_index + 1}E"
    try:
        _validate_carter_key(township, range_index, range_)
    except ValueError as exc:
        raise ValueError(
            f"No Tennessee Carter section contains NAD27 coordinate "
            f"({latitude:.8f}, {longitude:.8f})."
        ) from exc

    if row_from_south % 2 == 0:
        section = 25 - row_from_south * 5 - column_from_west
    else:
        section = 21 - row_from_south * 5 + column_from_west

    southwest = section_southwest_corner(section, township, range_)
    dimensions = feet_per_minute(southwest.nad27_lat)

    north_fraction = (latitude - southwest.nad27_lat) * 60.0
    east_fraction = (longitude - southwest.nad27_lon) * 60.0
    ns_from_south = north_fraction * dimensions.latitude_feet
    ew_from_west = east_fraction * dimensions.longitude_feet

    if ns_from_south < dimensions.latitude_feet * 0.5:
        ns_feet = ns_from_south
        ns_line = "FSL"
    else:
        ns_feet = dimensions.latitude_feet - ns_from_south
        ns_line = "FNL"

    if ew_from_west < dimensions.longitude_feet * 0.5:
        ew_feet = ew_from_west
        ew_line = "FWL"
    else:
        ew_feet = dimensions.longitude_feet - ew_from_west
        ew_line = "FEL"

    return CarterCoordinate(
        section=section,
        township=township,
        range_=range_,
        ns_feet=ns_feet,
        ns_line=ns_line,
        ew_feet=ew_feet,
        ew_line=ew_line,
        nad27_lat=latitude,
        nad27_lon=longitude,
    )
