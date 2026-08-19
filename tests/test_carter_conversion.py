import pytest

from tn_coord_converter_module import carter_to_nad27, nad27_to_carter


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

