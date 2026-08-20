import pytest

from tn_coord_converter_module import (
    carter_area_center_to_nad27,
    carter_quadrant_to_nad27,
    carter_to_nad27,
    nad27_to_carter,
    normalize_carter_quadrants,
    section_southwest_corner,
)


def test_documented_carter_coordinate_converts_to_nad27():
    coordinate = carter_to_nad27(
        section=11,
        township="2S",
        range_="47E",
        ns_feet=1750,
        ns_line="FSL",
        ew_feet=1900,
        ew_line="FWL",
    )

    assert coordinate.nad27_lat == pytest.approx(36.3714736806, abs=1e-10)
    assert coordinate.nad27_lon == pytest.approx(-85.5935471530, abs=1e-10)


def test_carter_round_trip_preserves_location():
    coordinate = carter_to_nad27(11, "2S", "47E", 1750, "FSL", 1900, "FWL")
    carter = nad27_to_carter(coordinate.nad27_lat, coordinate.nad27_lon)

    assert carter.section == 11
    assert carter.township == "2S"
    assert carter.range_ == "47E"
    assert carter.ns_feet == pytest.approx(1750, abs=0.01)
    assert carter.ew_feet == pytest.approx(1900, abs=0.01)


@pytest.mark.parametrize(
    ("quadrants", "east_fraction", "north_fraction"),
    [
        ("SE", 0.75, 0.25),
        ("NE SE", 0.875, 0.375),
        ("NE NE SE", 0.9375, 0.4375),
    ],
)
def test_bulletin_62_partial_quadrants_use_supplied_hierarchy(
    quadrants,
    east_fraction,
    north_fraction,
):
    southwest = section_southwest_corner(11, "A", "54E")
    coordinate = carter_quadrant_to_nad27(
        section=11,
        township="A",
        range_="54E",
        quadrants=quadrants,
    )

    assert coordinate.nad27_lon == pytest.approx(
        southwest.nad27_lon + east_fraction / 60.0
    )
    assert coordinate.nad27_lat == pytest.approx(
        southwest.nad27_lat + north_fraction / 60.0
    )


def test_partial_carter_areas_resolve_to_bounding_centers():
    township_range = carter_area_center_to_nad27("A", "54E")
    section = carter_area_center_to_nad27("A", "54E", section=11)

    assert township_range.nad27_lon == pytest.approx(-85.04166666666667)
    assert township_range.nad27_lat == pytest.approx(36.54166666666667)
    assert section.nad27_lon == pytest.approx(-85.00833333333334)
    assert section.nad27_lat == pytest.approx(36.54166666666667)


@pytest.mark.parametrize("value", ["NE NE SE", "NE-NE-SE", "NENESE"])
def test_quadrant_call_normalization_accepts_common_notation(value):
    assert normalize_carter_quadrants(value) == ("NE", "NE", "SE")


def test_legacy_quadrants_reject_more_than_three_levels():
    with pytest.raises(ValueError, match="at most three"):
        normalize_carter_quadrants("NE NE NE SE")

