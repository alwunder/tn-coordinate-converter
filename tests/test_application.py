import csv

import pytest

from tn_coord_converter_gui import APP_TITLE, CoordinateConverter, batch_convert, build_arg_parser
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

