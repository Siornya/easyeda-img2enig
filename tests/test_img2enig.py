from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import numpy as np

from image_binarizer import write_image
from img2enig import (
    PixelRectangle,
    build_project,
    convert,
    parse_log_line,
    read_binary_image,
)


class Img2EnigTests(unittest.TestCase):
    def make_asymmetric_image(self, directory: str) -> Path:
        source = Path(directory) / "方向测试.png"
        image = np.full((3, 4), 255, dtype=np.uint8)
        image[0, 0] = 0
        image[2, 3] = 0
        write_image(source, image)
        return source

    def test_raster_y_axis_is_flipped_without_flipping_x(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = self.make_asymmetric_image(directory)
            prepared = read_binary_image(source, 4.0, 3.0)
            self.assertEqual(
                set(prepared.rectangles),
                {
                    PixelRectangle(3, 0, 4, 1),
                    PixelRectangle(0, 2, 1, 3),
                },
            )

    def test_primitive_ids_are_unique_and_outline_follows_fills(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = self.make_asymmetric_image(directory)
            prepared = read_binary_image(source, 4.0, 3.0)
            artifact = build_project(prepared, "test", "top", 1.0, True)
            primitive_ids = []
            primitive_types = []
            for line in artifact.log_text.splitlines():
                outer, _inner = parse_log_line(line)
                if outer["type"] in {"FILL", "POLY"}:
                    primitive_ids.append(outer["id"])
                    primitive_types.append(outer["type"])
            self.assertEqual(len(primitive_ids), 5)
            self.assertEqual(len(set(primitive_ids)), 5)
            self.assertEqual(primitive_types[-1], "POLY")

    def test_top_and_bottom_outputs_have_expected_layers(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = self.make_asymmetric_image(directory)
            for side, layers in (("top", [1, 5]), ("bottom", [2, 6])):
                with self.subTest(side=side):
                    result = convert(
                        source=source,
                        output=Path(directory) / f"{side}.epro2",
                        width_mm=4.0,
                        height_mm=3.0,
                        side=side,
                        margin_mm=1.0,
                        include_outline=True,
                        project_name=None,
                    )
                    self.assertEqual(result["validation"]["fillLayers"], layers)
                    self.assertEqual(result["primitives"], 5)

    def test_silkscreen_only_and_combined_artwork_layers(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = self.make_asymmetric_image(directory)
            silk_only = convert(
                source=source,
                output=Path(directory) / "silk.epro2",
                width_mm=4.0,
                height_mm=3.0,
                side="top",
                margin_mm=1.0,
                include_outline=True,
                project_name=None,
                source_type="silk",
            )
            self.assertEqual(silk_only["validation"]["fillLayers"], [3])
            self.assertEqual(silk_only["primitives"], 3)

            combined = convert(
                source=source,
                output=Path(directory) / "combined.epro2",
                width_mm=4.0,
                height_mm=3.0,
                side="top",
                margin_mm=1.0,
                include_outline=True,
                project_name=None,
                silk_source=source,
            )
            self.assertEqual(combined["validation"]["fillLayers"], [1, 3, 5])
            self.assertEqual(combined["primitives"], 7)

if __name__ == "__main__":
    unittest.main()
