import csv
import json

import pytest

from tn_coord_converter_gui import (
    APP_TITLE,
    CoordinateConverter,
    batch_convert,
    build_arg_parser,
    format_coordinate_pair_for_clipboard,
    format_geographic_coordinate_for_clipboard,
    parse_geographic_coordinate,
    result_coordinate_pair,
)
from tn_coord_converter_version import PRODUCT_NAME


def test_product_branding():
    assert PRODUCT_NAME == "Tennessee Coordinate Converter"
    assert APP_TITLE.startswith("Tennessee Coordinate Converter v")
    assert build_arg_parser().description == APP_TITLE


def test_batch_conversion_from_carter_csv(tmp_path):
    input_path = tmp_path / "input.csv"
    output_path = tmp_path / "output.csv"
    input_path.write_text(
        "section,township,range,ns_feet,fsl_fnl,ew_feet,fwl_fel\n"
        "11,2S,47E,1750,FSL,1900,FWL\n",
        encoding="utf-8",
    )

    count = batch_convert(
        CoordinateConverter(),
        input_path,
        output_path,
        "CARTER",
        "GEOGRAPHIC_NAD27",
    )

    with output_path.open(encoding="utf-8", newline="") as stream:
        row = next(csv.DictReader(stream))

    assert count == 1
    assert float(row["nad27_lat"]) == pytest.approx(36.3714736806, abs=1e-10)
    assert float(row["nad27_lon"]) == pytest.approx(-85.5935471530, abs=1e-10)
    assert row["source_format"] == "CARTER"
    assert row["target_format"] == "GEOGRAPHIC_NAD27"


def test_batch_conversion_from_legacy_carter_quadrant_csv(tmp_path):
    input_path = tmp_path / "quadrants.csv"
    output_path = tmp_path / "output.json"
    input_path.write_text(
        "section,township,range,quadrants\n"
        '11,A,54E,"NE NE SE"\n',
        encoding="utf-8",
    )

    count = batch_convert(
        CoordinateConverter(),
        input_path,
        output_path,
        "AUTO",
        "GEOGRAPHIC_NAD27",
    )

    rows = json.loads(output_path.read_text(encoding="utf-8"))
    assert count == 1
    assert rows[0]["quadrants"] == "NE NE SE"
    assert rows[0]["quadrant_order"] == "smallest_to_largest"
    assert rows[0]["lon"] == pytest.approx(-85.00104166666667)
    assert rows[0]["lat"] == pytest.approx(36.540625)


def test_batch_conversion_accepts_township_range_only_and_marks_it_incomplete(tmp_path):
    input_path = tmp_path / "partial.csv"
    output_path = tmp_path / "output.json"
    input_path.write_text("township,range\nA,54E\n", encoding="utf-8")

    count = batch_convert(
        CoordinateConverter(),
        input_path,
        output_path,
        "AUTO",
        "GEOGRAPHIC_NAD27",
    )

    row = json.loads(output_path.read_text(encoding="utf-8"))[0]
    assert count == 1
    assert row["carter_complete"] is False
    assert row["location_method"] == "center_of_township_range"
    assert "Incomplete Carter coordinate" in row["location_note"]
    assert row["lon"] == pytest.approx(-85.04166666666667)
    assert row["lat"] == pytest.approx(36.54166666666667)


@pytest.mark.parametrize(
    ("quadrants", "complete", "method"),
    [
        ("SE", False, "center_of_largest_quadrant"),
        ("NE SE", False, "center_of_middle_quadrant"),
        ("NE NE SE", True, "center_of_smallest_quadrant"),
    ],
)
def test_legacy_quadrant_completeness_metadata(quadrants, complete, method):
    result = CoordinateConverter().convert_single(
        "CARTER_QUADRANT",
        "GEOGRAPHIC_NAD27",
        {
            "section": 11,
            "township": "A",
            "range": "54E",
            "quadrants": quadrants,
        },
    )

    assert result["carter_complete"] is complete
    assert result["location_method"] == method
    assert result["quadrant_count"] == len(quadrants.split())


def test_legacy_quadrant_can_convert_to_carter_footage():
    converter = CoordinateConverter()
    quadrant_payload = {
        "section": 11,
        "township": "A",
        "range": "54E",
        "quadrants": "NE NE SE",
    }

    footage = converter.convert_single("CARTER_QUADRANT", "CARTER", quadrant_payload)
    quadrant_point = converter.convert_single(
        "CARTER_QUADRANT", "GEOGRAPHIC_NAD27", quadrant_payload
    )
    footage_point = converter.convert_single(
        "CARTER",
        "GEOGRAPHIC_NAD27",
        {
            "section": footage["section"],
            "township": footage["township"],
            "range": footage["range"],
            "ns_feet": footage["ns_feet"],
            "ns_line": footage["ns_line"],
            "ew_feet": footage["ew_feet"],
            "ew_line": footage["ew_line"],
        },
    )

    assert footage["location_method"] == "derived_footage_from_carter_area_center"
    assert "does not add precision" in footage["location_note"]
    assert "quadrants" not in footage
    assert footage_point["lon"] == pytest.approx(quadrant_point["lon"])
    assert footage_point["lat"] == pytest.approx(quadrant_point["lat"])


def test_carter_quadrant_is_not_an_output_format():
    target_action = next(
        action for action in build_arg_parser()._actions if action.dest == "target_format"
    )

    assert "CARTER" in target_action.choices
    assert "CARTER_QUADRANT" not in target_action.choices


def test_json_coordinate_pairs_are_ordered_x_then_y_for_every_xy_format():
    converter = CoordinateConverter()
    geographic = converter.convert_single(
        "CARTER",
        "GEOGRAPHIC_NAD27",
        {
            "section": 11,
            "township": "2S",
            "range": "47E",
            "ns_feet": 1750,
            "ns_line": "FSL",
            "ew_feet": 1900,
            "ew_line": "FWL",
        },
    )
    projected = converter.convert_single(
        "GEOGRAPHIC_NAD27",
        "TNSPC_NAD27",
        {"lon": geographic["lon"], "lat": geographic["lat"]},
    )
    carter = converter.convert_single(
        "GEOGRAPHIC_NAD27",
        "CARTER",
        {"lon": geographic["lon"], "lat": geographic["lat"]},
    )

    geographic_keys = list(geographic)
    projected_keys = list(projected)
    assert geographic_keys.index("lon") < geographic_keys.index("lat")
    assert projected_keys.index("x") < projected_keys.index("y")
    assert result_coordinate_pair("GEOGRAPHIC_NAD27", geographic) == (
        geographic["lon"],
        geographic["lat"],
    )
    assert result_coordinate_pair("TNSPC_NAD27", projected) == (
        projected["x"],
        projected["y"],
    )
    assert result_coordinate_pair("CARTER", carter) == (
        carter["tnspc_nad27_x"],
        carter["tnspc_nad27_y"],
    )


def test_coordinate_pair_copy_order_toggle_format():
    assert format_coordinate_pair_for_clipboard(123.5, 456.25, "xy") == "123.5,456.25"
    assert format_coordinate_pair_for_clipboard(123.5, 456.25, "yx") == "456.25,123.5"


@pytest.mark.parametrize(
    ("text", "axis", "expected"),
    [
        ("-85.593547153", "lon", -85.593547153),
        ('85\N{DEGREE SIGN} 35\' 36.77" W', "lon", -85.59354722222222),
        ("85 35 36.77 W", "lon", -85.59354722222222),
        ("36\N{DEGREE SIGN} 22.288' N", "lat", 36.37146666666667),
        ("N 36 22.288", "lat", 36.37146666666667),
    ],
)
def test_geographic_parser_accepts_dd_dms_and_ddm(text, axis, expected):
    assert parse_geographic_coordinate(text, axis) == pytest.approx(expected)


@pytest.mark.parametrize(
    ("output_format", "expected"),
    [
        ("DMS (symbols)", '85\N{DEGREE SIGN} 35\' 36.770" W'),
        ("DMS (spaces)", "85 35 36.770 W"),
        ("DDM (symbols)", "85\N{DEGREE SIGN} 35.613' W"),
        ("DDM (spaces)", "85 35.613 W"),
    ],
)
def test_geographic_clipboard_formats_use_direction_without_negative_sign(
    output_format, expected
):
    assert (
        format_geographic_coordinate_for_clipboard(
            -85.59354722222222, "lon", output_format
        )
        == expected
    )


def test_geographic_source_conversion_accepts_symbol_dms_input():
    result = CoordinateConverter().convert_single(
        "GEOGRAPHIC_NAD27",
        "TNSPC_NAD27",
        {
            "lon": '85\N{DEGREE SIGN} 35\' 36.77" W',
            "lat": '36\N{DEGREE SIGN} 22\' 17.31" N',
        },
    )
    decimal_result = CoordinateConverter().convert_single(
        "GEOGRAPHIC_NAD27",
        "TNSPC_NAD27",
        {"lon": -85.59354722222222, "lat": 36.371475},
    )

    assert result["x"] == pytest.approx(decimal_result["x"])
    assert result["y"] == pytest.approx(decimal_result["y"])

