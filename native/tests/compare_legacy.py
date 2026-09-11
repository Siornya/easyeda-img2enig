"""Optional migration parity check, using the existing Python environment."""
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from image_binarizer import BinarizationOptions, ThresholdMethod, binarize_image

with tempfile.TemporaryDirectory() as temporary:
	root = Path(temporary)
	source = np.random.default_rng(42).integers(0, 256, (128, 256), dtype=np.uint8)
	source.tofile(root / "input.raw")
	subprocess.run([sys.argv[1], str(root)], check=True)
	presets = [{}, {"exposure": 12, "contrast": -15, "gamma": 1.3},
		{"denoise_strength": 20, "sharpen": 15, "clahe": True},
		{"invert": True, "flip_horizontal": True, "flip_vertical": True},
		{"block_size": 15, "local_k": 0.35, "adaptive_c": -3, "threshold": 160}]
	worst = 0
	for preset, values in enumerate(presets):
		for index, method in enumerate(ThresholdMethod):
			expected = binarize_image(source, BinarizationOptions(
				threshold_method=method, max_dimension=None, **values))
			actual = np.fromfile(root / f"{preset}-{index}.raw", dtype=np.uint8).reshape(source.shape)
			difference = np.mean(actual != expected)
			worst = max(worst, difference)
			# OpenCV versions and float rounding may move pixels at the threshold.
			if difference > 0.002:
				raise AssertionError(f"{preset}/{method}: {difference:.2%} pixels differ")
	print(f"PASS: 35 legacy comparisons; largest pixel difference {worst:.4%}")
