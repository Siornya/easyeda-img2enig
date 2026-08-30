from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import cv2
import numpy as np

from image_binarizer import (
    BinarizationOptions,
    ThresholdMethod,
    binarize_file,
    binarize_image,
    read_image,
)


class ImageBinarizerTests(unittest.TestCase):
    def test_all_threshold_methods_produce_pure_binary_images(self) -> None:
        gradient = np.tile(np.arange(0, 256, dtype=np.uint8), (64, 1))
        for method in ThresholdMethod:
            with self.subTest(method=method):
                result = binarize_image(
                    gradient,
                    BinarizationOptions(
                        threshold_method=method,
                        max_dimension=None,
                    ),
                )
                self.assertEqual(result.shape, gradient.shape)
                self.assertTrue(set(np.unique(result)).issubset({0, 255}))

    def test_horizontal_flip_does_not_change_vertical_direction(self) -> None:
        source = np.full((3, 4), 255, dtype=np.uint8)
        source[0, 0] = 0
        result = binarize_image(
            source,
            BinarizationOptions(
                threshold_method=ThresholdMethod.FIXED,
                threshold=127,
                flip_horizontal=True,
                max_dimension=None,
            ),
        )
        self.assertEqual(result[0, 3], 0)
        self.assertEqual(result[2, 3], 255)

    def test_alpha_is_composited_on_white(self) -> None:
        source = np.zeros((1, 2, 4), dtype=np.uint8)
        source[0, 0] = (0, 0, 0, 0)
        source[0, 1] = (0, 0, 0, 255)
        result = binarize_image(
            source,
            BinarizationOptions(
                threshold_method=ThresholdMethod.FIXED,
                threshold=127,
                max_dimension=None,
            ),
        )
        np.testing.assert_array_equal(result, np.array([[255, 0]], dtype=np.uint8))

    def test_unicode_paths_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "输入图片.png"
            output = root / "二值化结果.png"
            gradient = np.tile(np.arange(16, dtype=np.uint8) * 17, (16, 1))
            success, encoded = cv2.imencode(".png", gradient)
            self.assertTrue(success)
            encoded.tofile(source)
            binarize_file(
                source,
                output,
                BinarizationOptions(
                    threshold_method=ThresholdMethod.OTSU,
                    max_dimension=None,
                ),
            )
            loaded = read_image(output)
            self.assertEqual(loaded.shape, gradient.shape)
            self.assertTrue(set(np.unique(loaded)).issubset({0, 255}))

    def test_large_image_is_scaled_without_changing_aspect_ratio(self) -> None:
        source = np.zeros((100, 200), dtype=np.uint8)
        result = binarize_image(source, BinarizationOptions(max_dimension=50))
        self.assertEqual(result.shape, (25, 50))

    def test_lossy_output_format_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "input.png"
            output = Path(directory) / "output.jpg"
            success, encoded = cv2.imencode(".png", np.zeros((2, 2), dtype=np.uint8))
            self.assertTrue(success)
            encoded.tofile(source)
            with self.assertRaisesRegex(ValueError, "lossless"):
                binarize_file(source, output)


if __name__ == "__main__":
    unittest.main()
