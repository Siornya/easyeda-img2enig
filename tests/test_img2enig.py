from __future__ import annotations

import base64
import io
import json
import tempfile
import unittest
import zipfile
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

import cv2
import numpy as np

from img2enig import main, parse_log_line, read_binary_image, read_manifest


def write_image(path: Path, image: np.ndarray) -> None:
    success, encoded = cv2.imencode(path.suffix, image)
    if not success:
        raise ValueError(f"Cannot encode test image: {path}")
    path.write_bytes(encoded.tobytes())


class Img2EnigTests(unittest.TestCase):
    def make_binary_image(self, directory: str) -> Path:
        source = Path(directory) / "沉金.png"
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

    def test_enig_input_requires_cpp_processed_black_and_white_grayscale(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = self.make_binary_image(directory)
            image = read_binary_image(source)
            self.assertEqual((image.width_px, image.height_px), (4, 3))
            self.assertEqual(
                {(item.x0, item.y0, item.x1, item.y1) for item in image.rectangles},
                {(3, 0, 4, 1), (0, 2, 1, 3)},
            )

            color = Path(directory) / "未处理彩色图.png"
            write_image(color, np.zeros((2, 2, 3), dtype=np.uint8))
            with self.assertRaisesRegex(ValueError, r"C\+\+-processed grayscale"):
                read_binary_image(color)

            gray = Path(directory) / "未二值化灰度图.png"
            write_image(gray, np.full((2, 2), 127, dtype=np.uint8))
            with self.assertRaisesRegex(ValueError, "pure black/white"):
                read_binary_image(gray)

    def test_manifest_preserves_layers_positions_colors_and_dimensions(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            enig = self.make_binary_image(directory)
            silk = self.make_color_image(directory)
            manifest = Path(directory) / "layers.json"
            manifest.write_text(json.dumps({
                "canvas": {
                    "width": 10,
                    "height": 8,
                    "widthMm": 10,
                    "heightMm": 8,
                },
                "projectName": "多图层测试",
                "solderMaskColor": "#164D73",
                "layers": [
                    {"source": enig.name, "type": "enig", "x": 1, "y": 2},
                    {"source": silk.name, "type": "silk", "x": 5, "y": 4},
                    {"source": enig.name, "type": "enig", "side": "back",
                     "x": 2, "y": 1},
                    {"source": silk.name, "type": "silk", "side": "back",
                     "x": 0, "y": 0},
                    {"source": "ignored.png", "type": "silk", "x": 0, "y": 0,
                     "visible": False},
                ],
            }), encoding="utf-8")
            specs, settings = read_manifest(manifest)
            self.assertEqual(
                [item.source for item in specs], [enig, silk, enig, silk]
            )
            self.assertEqual(
                [item.side for item in specs], ["front", "front", "back", "back"]
            )
            self.assertEqual(settings["canvas_width_px"], 10)

            output = Path(directory) / "layers.epro2"
            command_output = io.StringIO()
            with redirect_stdout(command_output):
                exit_code = main(["--manifest", str(manifest), "-o", str(output)])
            self.assertEqual(exit_code, 0)
            report = json.loads(command_output.getvalue())
            self.assertEqual((report["width_mm"], report["height_mm"]), (10.0, 8.0))

            records = self.read_records(output)
            self.assertEqual(records["layers"], {1, 2, 3, 4, 5, 6})
            primitive_ids = [
                outer["id"] for outer, _inner in records["all"]
                if outer["type"] in {"FILL", "OBJ", "POLY"}
            ]
            self.assertEqual(len(primitive_ids), len(set(primitive_ids)))
            primitive_types = [
                outer["type"] for outer, _inner in records["all"]
                if outer["type"] in {"FILL", "OBJ", "POLY"}
            ]
            self.assertEqual(primitive_types[-1], "POLY")

            scale = 1 / 0.254
            copper_boxes = {
                tuple(round(value / scale) for value in (
                    fill["path"][0][0], fill["path"][0][1],
                    fill["path"][0][3], fill["path"][0][6],
                ))
                for fill in records["fills"]
                if fill["layerId"] == 1
            }
            self.assertEqual(copper_boxes, {(2, 6, 3, 7), (5, 4, 6, 5)})

            color_object = next(
                item for item in records["objects"] if item["layerId"] == 3
            )
            self.assertAlmostEqual(color_object["startX"], 6 * scale)
            self.assertAlmostEqual(color_object["startY"], 2 * scale)
            self.assertAlmostEqual(color_object["width"], 4 * scale)
            self.assertAlmostEqual(color_object["height"], 3 * scale)
            payload = color_object["path"].split(",", 1)[1]
            decoded = cv2.imdecode(
                np.frombuffer(base64.b64decode(payload), dtype=np.uint8),
                cv2.IMREAD_UNCHANGED,
            )
            self.assertEqual(decoded[1, 1].tolist(), [0, 255, 0, 192])

            self.assertEqual(
                {item["layerId"] for item in records["objects"]}, {3, 4}
            )
            self.assertTrue(any(fill["layerId"] == 2 for fill in records["fills"]))
            self.assertTrue(any(fill["layerId"] == 6 for fill in records["fills"]))

            mask_colors = {
                inner["activeColor"]
                for outer, inner in records["all"]
                if outer["type"] == "LAYER" and inner["layerType"] in {
                    "TOP_SOLDER_MASK", "BOT_SOLDER_MASK"
                }
            }
            self.assertEqual(mask_colors, {"#164D73"})

    def test_repeated_layer_arguments_remain_available(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            enig = self.make_binary_image(directory)
            output = Path(directory) / "direct.epro2"
            command_output = io.StringIO()
            with redirect_stdout(command_output):
                exit_code = main([
                    "--layer", str(enig), "enig", "2", "1",
                    "--canvas-width", "8",
                    "--canvas-height", "6",
                    "-o", str(output),
                ])
            self.assertEqual(exit_code, 0)
            self.assertTrue(output.is_file())
            report = json.loads(command_output.getvalue())
            self.assertAlmostEqual(report["width_mm"], 8 / 300 * 25.4)
            self.assertAlmostEqual(report["height_mm"], 6 / 300 * 25.4)
            records = self.read_records(output)
            mask_colors = {
                inner["activeColor"]
                for outer, inner in records["all"]
                if outer["type"] == "LAYER" and inner["layerType"] in {
                    "TOP_SOLDER_MASK", "BOT_SOLDER_MASK"
                }
            }
            self.assertEqual(mask_colors, {"#ECEBE6"})

    def test_missing_layer_input_fails(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "missing.epro2"
            with redirect_stderr(io.StringIO()):
                exit_code = main([
                    "--canvas-width", "8",
                    "--canvas-height", "6",
                    "-o", str(output),
                ])
            self.assertEqual(exit_code, 1)
            self.assertFalse(output.exists())

    @staticmethod
    def read_records(path: Path) -> dict[str, object]:
        with zipfile.ZipFile(path, "r") as archive:
            epru = next(name for name in archive.namelist() if name.endswith(".epru"))
            records = [
                parse_log_line(line)
                for line in archive.read(epru).decode().splitlines()
            ]
        return {
            "all": records,
            "layers": {
                inner["layerId"]
                for outer, inner in records
                if outer["type"] in {"FILL", "OBJ"}
            },
            "objects": [inner for outer, inner in records if outer["type"] == "OBJ"],
            "fills": [inner for outer, inner in records if outer["type"] == "FILL"],
        }


if __name__ == "__main__":
    unittest.main()
