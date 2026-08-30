"""Reusable image preprocessing and binarization pipeline."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

import cv2
import numpy as np


class ThresholdMethod(str, Enum):
    FIXED = "fixed"
    ADAPTIVE = "adaptive"
    OTSU = "otsu"
    SAUVOLA = "sauvola"
    WOLF = "wolf"
    NICK = "nick"
    BERNSEN = "bernsen"

    def __str__(self) -> str:
        return self.value


class DenoiseMethod(str, Enum):
    GAUSSIAN = "gaussian"
    MEDIAN = "median"
    BILATERAL = "bilateral"
    NL_MEANS = "nlmeans"

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True)
class BinarizationOptions:
    threshold_method: ThresholdMethod = ThresholdMethod.ADAPTIVE
    threshold: int = 127
    block_size: int = 31
    adaptive_c: float = 5.0
    local_k: float = 0.2
    denoise_method: DenoiseMethod = DenoiseMethod.GAUSSIAN
    denoise_strength: int = 0
    exposure: int = 0
    contrast: int = 0
    gamma: float = 1.0
    smooth: int = 0
    sharpen: int = 0
    equalize: bool = False
    clahe: bool = False
    detail_enhance: int = 0
    edge_enhance: int = 0
    local_contrast: int = 0
    invert: bool = False
    flip_horizontal: bool = False
    flip_vertical: bool = False
    max_dimension: int | None = 3840

    def validate(self) -> None:
        if not 0 <= self.threshold <= 255:
            raise ValueError("threshold must be between 0 and 255")
        if self.block_size < 3 or self.block_size % 2 == 0:
            raise ValueError("block_size must be an odd integer of at least 3")
        if not -100.0 <= self.adaptive_c <= 100.0:
            raise ValueError("adaptive_c must be between -100 and 100")
        if not -1.0 <= self.local_k <= 1.0:
            raise ValueError("local_k must be between -1 and 1")
        if not 0 <= self.denoise_strength <= 100:
            raise ValueError("denoise_strength must be between 0 and 100")
        if not -100 <= self.exposure <= 100:
            raise ValueError("exposure must be between -100 and 100")
        if not -100 <= self.contrast <= 100:
            raise ValueError("contrast must be between -100 and 100")
        if self.gamma <= 0:
            raise ValueError("gamma must be greater than zero")
        for name in (
            "smooth",
            "sharpen",
            "detail_enhance",
            "edge_enhance",
            "local_contrast",
        ):
            value = getattr(self, name)
            if not 0 <= value <= 100:
                raise ValueError(f"{name} must be between 0 and 100")
        if self.max_dimension is not None and self.max_dimension < 1:
            raise ValueError("max_dimension must be positive or None")


def read_image(path: str | Path) -> np.ndarray:
    """Read an image while supporting non-ASCII paths on every platform."""

    source = Path(path)
    if not source.is_file():
        raise FileNotFoundError(f"Image does not exist: {source}")
    encoded = np.fromfile(source, dtype=np.uint8)
    image = cv2.imdecode(encoded, cv2.IMREAD_UNCHANGED)
    if image is None:
        raise ValueError(f"Unsupported or damaged image: {source}")
    return image


def write_image(path: str | Path, image: np.ndarray) -> Path:
    """Write a lossless image that remains safe for the PCB converter."""

    destination = Path(path)
    if not destination.suffix:
        destination = destination.with_suffix(".png")
    extension = destination.suffix.lower()
    if extension not in {".png", ".bmp", ".tif", ".tiff"}:
        raise ValueError("Output must use a lossless PNG, BMP, or TIFF format")
    destination.parent.mkdir(parents=True, exist_ok=True)
    success, encoded = cv2.imencode(extension, image)
    if not success:
        raise ValueError(f"Unsupported output format: {extension}")
    encoded.tofile(destination)
    return destination


def binarize_file(
    source: str | Path,
    destination: str | Path,
    options: BinarizationOptions | None = None,
) -> Path:
    result = binarize_image(read_image(source), options)
    return write_image(destination, result)


def binarize_image(
    image: np.ndarray,
    options: BinarizationOptions | None = None,
) -> np.ndarray:
    """Return a contiguous uint8 image containing only 0 and 255."""

    settings = options or BinarizationOptions()
    settings.validate()
    gray = _to_grayscale(image)
    gray = _limit_size(gray, settings.max_dimension)
    gray = _adjust_tone(gray, settings)
    gray = _apply_denoise(gray, settings)
    gray = _apply_enhancements(gray, settings)
    binary = _apply_threshold(gray, settings)

    if settings.invert:
        binary = cv2.bitwise_not(binary)
    if settings.flip_horizontal:
        binary = cv2.flip(binary, 1)
    if settings.flip_vertical:
        binary = cv2.flip(binary, 0)
    return np.ascontiguousarray(binary, dtype=np.uint8)


def _to_grayscale(image: np.ndarray) -> np.ndarray:
    if image.size == 0:
        raise ValueError("Image is empty")
    if image.dtype != np.uint8:
        image = np.clip(image, 0, 255).astype(np.uint8)
    if image.ndim == 2:
        return image.copy()
    if image.ndim != 3:
        raise ValueError("Image must be grayscale, BGR, or BGRA")
    if image.shape[2] == 3:
        return cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    if image.shape[2] != 4:
        raise ValueError("Image must have one, three, or four channels")

    color = image[:, :, :3].astype(np.float32)
    alpha = image[:, :, 3:4].astype(np.float32) / 255.0
    composited = np.clip(color * alpha + 255.0 * (1.0 - alpha), 0, 255)
    return cv2.cvtColor(composited.astype(np.uint8), cv2.COLOR_BGR2GRAY)


def _limit_size(image: np.ndarray, max_dimension: int | None) -> np.ndarray:
    if max_dimension is None or max(image.shape[:2]) <= max_dimension:
        return image
    scale = max_dimension / max(image.shape[:2])
    width = max(1, round(image.shape[1] * scale))
    height = max(1, round(image.shape[0] * scale))
    return cv2.resize(image, (width, height), interpolation=cv2.INTER_AREA)


def _adjust_tone(image: np.ndarray, options: BinarizationOptions) -> np.ndarray:
    working = image.astype(np.float32)
    if options.exposure:
        working *= 2.0 ** (options.exposure / 50.0)
    if options.contrast:
        factor = max(0.0, 1.0 + options.contrast / 50.0)
        working = (working - 127.5) * factor + 127.5
    working = np.clip(working, 0, 255)
    if options.gamma != 1.0:
        working = 255.0 * np.power(working / 255.0, 1.0 / options.gamma)
    return np.clip(working, 0, 255).astype(np.uint8)


def _odd_kernel(strength: int, maximum: int = 21) -> int:
    if strength <= 0:
        return 1
    return min(maximum, 2 * max(1, round(strength / 10)) + 1)


def _apply_denoise(image: np.ndarray, options: BinarizationOptions) -> np.ndarray:
    result = image
    strength = options.denoise_strength
    if strength:
        kernel = _odd_kernel(strength)
        if options.denoise_method is DenoiseMethod.GAUSSIAN:
            result = cv2.GaussianBlur(result, (kernel, kernel), 0)
        elif options.denoise_method is DenoiseMethod.MEDIAN:
            result = cv2.medianBlur(result, kernel)
        elif options.denoise_method is DenoiseMethod.BILATERAL:
            sigma = max(10, strength * 2)
            result = cv2.bilateralFilter(result, kernel, sigma, sigma)
        elif options.denoise_method is DenoiseMethod.NL_MEANS:
            result = cv2.fastNlMeansDenoising(result, None, float(strength), 7, 21)
    if options.smooth:
        kernel = _odd_kernel(options.smooth)
        result = cv2.GaussianBlur(result, (kernel, kernel), 0)
    return result


def _apply_enhancements(image: np.ndarray, options: BinarizationOptions) -> np.ndarray:
    result = image
    if options.clahe:
        result = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8)).apply(result)
    elif options.equalize:
        result = cv2.equalizeHist(result)

    unsharp_amount = (options.sharpen + options.detail_enhance) / 100.0
    if unsharp_amount:
        blurred = cv2.GaussianBlur(result, (0, 0), 1.2)
        result = cv2.addWeighted(result, 1.0 + unsharp_amount, blurred, -unsharp_amount, 0)

    if options.edge_enhance:
        amount = options.edge_enhance / 200.0
        laplacian = cv2.Laplacian(result, cv2.CV_32F, ksize=3)
        result = np.clip(result.astype(np.float32) - amount * laplacian, 0, 255).astype(np.uint8)

    if options.local_contrast:
        clip_limit = 1.0 + options.local_contrast / 25.0
        enhanced = cv2.createCLAHE(clipLimit=clip_limit, tileGridSize=(8, 8)).apply(result)
        blend = options.local_contrast / 100.0
        result = cv2.addWeighted(result, 1.0 - blend, enhanced, blend, 0)
    return result


def _local_statistics(image: np.ndarray, block_size: int) -> tuple[np.ndarray, np.ndarray]:
    source = image.astype(np.float32)
    mean = cv2.boxFilter(source, cv2.CV_32F, (block_size, block_size), normalize=True)
    square_mean = cv2.boxFilter(
        source * source,
        cv2.CV_32F,
        (block_size, block_size),
        normalize=True,
    )
    standard_deviation = np.sqrt(np.maximum(square_mean - mean * mean, 0.0))
    return mean, standard_deviation


def _apply_threshold(image: np.ndarray, options: BinarizationOptions) -> np.ndarray:
    method = options.threshold_method
    if method is ThresholdMethod.FIXED:
        _, result = cv2.threshold(image, options.threshold, 255, cv2.THRESH_BINARY)
        return result
    if method is ThresholdMethod.OTSU:
        _, result = cv2.threshold(image, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        return result
    if method is ThresholdMethod.ADAPTIVE:
        return cv2.adaptiveThreshold(
            image,
            255,
            cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY,
            options.block_size,
            options.adaptive_c,
        )

    mean, deviation = _local_statistics(image, options.block_size)
    source = image.astype(np.float32)
    if method is ThresholdMethod.SAUVOLA:
        threshold_map = mean * (1.0 + options.local_k * (deviation / 128.0 - 1.0))
    elif method is ThresholdMethod.WOLF:
        maximum_deviation = max(float(deviation.max()), 1e-6)
        minimum_gray = float(source.min())
        threshold_map = mean + options.local_k * (
            deviation / maximum_deviation - 1.0
        ) * (mean - minimum_gray)
    elif method is ThresholdMethod.NICK:
        nick_k = -abs(options.local_k)
        threshold_map = mean + nick_k * np.sqrt(deviation * deviation + mean * mean)
    elif method is ThresholdMethod.BERNSEN:
        kernel = np.ones((options.block_size, options.block_size), dtype=np.uint8)
        local_minimum = cv2.erode(image, kernel).astype(np.float32)
        local_maximum = cv2.dilate(image, kernel).astype(np.float32)
        local_contrast = local_maximum - local_minimum
        threshold_map = (local_minimum + local_maximum) / 2.0
        threshold_map = np.where(local_contrast < 15.0, options.threshold, threshold_map)
    else:
        raise ValueError(f"Unsupported threshold method: {method}")
    return np.where(source > threshold_map, 255, 0).astype(np.uint8)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Convert an image to a pure black/white PNG.",
    )
    parser.add_argument("input", type=Path, help="source image")
    parser.add_argument("-o", "--output", type=Path, help="output image")
    parser.add_argument(
        "--method",
        type=ThresholdMethod,
        choices=list(ThresholdMethod),
        default=ThresholdMethod.ADAPTIVE,
        help="threshold method (default: adaptive)",
    )
    parser.add_argument("--threshold", type=int, default=127)
    parser.add_argument("--block-size", type=int, default=31)
    parser.add_argument("--adaptive-c", type=float, default=5.0)
    parser.add_argument("--local-k", type=float, default=0.2)
    parser.add_argument(
        "--denoise-method",
        type=DenoiseMethod,
        choices=list(DenoiseMethod),
        default=DenoiseMethod.GAUSSIAN,
    )
    parser.add_argument("--denoise", type=int, default=0, metavar="0..100")
    parser.add_argument("--exposure", type=int, default=0, metavar="-100..100")
    parser.add_argument("--contrast", type=int, default=0, metavar="-100..100")
    parser.add_argument("--gamma", type=float, default=1.0)
    parser.add_argument("--smooth", type=int, default=0, metavar="0..100")
    parser.add_argument("--sharpen", type=int, default=0, metavar="0..100")
    parser.add_argument("--equalize", action="store_true")
    parser.add_argument("--clahe", action="store_true")
    parser.add_argument("--detail", type=int, default=0, metavar="0..100")
    parser.add_argument("--edge", type=int, default=0, metavar="0..100")
    parser.add_argument("--local-contrast", type=int, default=0, metavar="0..100")
    parser.add_argument("--invert", action="store_true")
    parser.add_argument("--flip-horizontal", action="store_true")
    parser.add_argument("--flip-vertical", action="store_true")
    parser.add_argument(
        "--max-dimension",
        type=int,
        default=3840,
        help="downscale larger images; use 0 to keep the original size",
    )
    return parser


def default_output(source: Path) -> Path:
    return source.with_name(f"{source.stem}.binary.png")


def cli_main(argv: list[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    output = arguments.output or default_output(arguments.input)
    options = BinarizationOptions(
        threshold_method=arguments.method,
        threshold=arguments.threshold,
        block_size=arguments.block_size,
        adaptive_c=arguments.adaptive_c,
        local_k=arguments.local_k,
        denoise_method=arguments.denoise_method,
        denoise_strength=arguments.denoise,
        exposure=arguments.exposure,
        contrast=arguments.contrast,
        gamma=arguments.gamma,
        smooth=arguments.smooth,
        sharpen=arguments.sharpen,
        equalize=arguments.equalize,
        clahe=arguments.clahe,
        detail_enhance=arguments.detail,
        edge_enhance=arguments.edge,
        local_contrast=arguments.local_contrast,
        invert=arguments.invert,
        flip_horizontal=arguments.flip_horizontal,
        flip_vertical=arguments.flip_vertical,
        max_dimension=arguments.max_dimension or None,
    )
    try:
        destination = binarize_file(arguments.input, output, options)
    except (FileNotFoundError, OSError, ValueError) as error:
        print(f"image_binarizer: {error}", file=sys.stderr)
        return 1
    print(
        json.dumps(
            {
                "input": str(arguments.input),
                "output": str(destination),
                "method": options.threshold_method.value,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(cli_main())
