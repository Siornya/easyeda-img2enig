from __future__ import annotations

import base64
import tempfile
import unittest
import zipfile
from pathlib import Path

import numpy as np
import cv2

from img2enig import (
    PixelRectangle,
    build_project,
    convert,
    parse_log_line,
    read_binary_image,
)


def write_image(path: Path, image: np.ndarray) -> None:
    success, encoded = cv2.imencode(path.suffix, image)
    if not success:
        raise ValueError(f"Cannot encode test image: {path}")
    path.write_bytes(encoded.tobytes())


class Img2EnigTests(unittest.TestCase):
    def make_asymmetric_image(self, directory: str) -> Path:
        source = Path(directory) / "方向测试.png"
        image = np.full((3, 4), 255, dtype=np.uint8)
        image[0, 0] = 0
        image[2, 3] = 0
        write_image(source, image)
        return source

    def make_color_image(self, directory: str) -> Path:
        source = Path(directory) / "彩色丝印.png"
        image = np.zeros((3, 4, 4), dtype=np.uint8)
        image[0, 0] = (0, 0, 255, 255)
        image[1, 1] = (0, 255, 0, 192)
        image[2, 3] = (255, 0, 0, 255)
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

    def test_full_color_silkscreen_and_solder_mask_color_are_exported(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            color_source = self.make_color_image(directory)
            output = Path(directory) / "color-silk.epro2"
            result = convert(
                source=color_source,
                output=output,
                width_mm=4.0,
                height_mm=3.0,
                side="top",
                margin_mm=1.0,
                include_outline=True,
                project_name=None,
                source_type="color-silk",
                solder_mask_color="#164d73",
            )
            self.assertEqual(result["validation"]["fillLayers"], [])
            self.assertEqual(result["validation"]["objectLayers"], [3])
            self.assertEqual(result["validation"]["artworkLayers"], [3])
            self.assertEqual(result["primitives"], 2)

            with zipfile.ZipFile(output, "r") as archive:
                epru = next(name for name in archive.namelist() if name.endswith(".epru"))
                records = [parse_log_line(line) for line in archive.read(epru).decode().splitlines()]
            color_objects = [inner for outer, inner in records if outer["type"] == "OBJ"]
            self.assertEqual(len(color_objects), 1)
            self.assertEqual(color_objects[0]["layerId"], 3)
            self.assertTrue(color_objects[0]["path"].startswith("data:image/png;base64,"))
            payload = color_objects[0]["path"].split(",", 1)[1]
            decoded = cv2.imdecode(
                np.frombuffer(base64.b64decode(payload), dtype=np.uint8),
                cv2.IMREAD_UNCHANGED,
            )
            self.assertEqual(decoded[0, 0].tolist(), [0, 0, 255, 255])
            self.assertEqual(decoded[1, 1].tolist(), [0, 255, 0, 192])
            self.assertEqual(decoded[2, 3].tolist(), [255, 0, 0, 255])

            mask_layers = [
                inner
                for outer, inner in records
                if outer["type"] == "LAYER" and inner["layerType"] in {
                    "TOP_SOLDER_MASK",
                    "BOT_SOLDER_MASK",
                }
            ]
            self.assertEqual({layer["activeColor"] for layer in mask_layers}, {"#164D73"})
            silk_options = [inner for outer, inner in records if outer["type"] == "SILK_OPTS"]
            self.assertEqual({options["baseColor"] for options in silk_options}, {"#164D73"})


if __name__ == "__main__":
    unittest.main()
