"""Convert prepared black/white masks into EasyEDA Pro ENIG and silkscreen artwork."""

from __future__ import annotations

import argparse
import base64
import json
import re
import secrets
import sys
import time
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import cv2
import numpy as np


UNITS_PER_MM = 1.0 / 0.254
EDITOR_VERSION = "3.2"
LAYER_IDS = {
    "top-copper": 1,
    "top-silk": 3,
    "top-mask": 5,
    "bottom-mask": 6,
    "outline": 11,
}

LAYERS = (
    (1, "TOP", "Top Layer", "#ff0000", "#7f0000", True),
    (2, "BOTTOM", "Bottom Layer", "#0000ff", "#00007f", True),
    (3, "TOP_SILK", "Top Silkscreen Layer", "#ffcc00", "#7f6600", True),
    (4, "BOT_SILK", "Bottom Silkscreen Layer", "#66cc33", "#336619", True),
    (5, "TOP_SOLDER_MASK", "Top Solder Mask Layer", "#800080", "#400040", True),
    (6, "BOT_SOLDER_MASK", "Bottom Solder Mask Layer", "#aa00ff", "#55007f", True),
    (7, "TOP_PASTE_MASK", "Top Paste Mask Layer", "#808080", "#404040", True),
    (8, "BOT_PASTE_MASK", "Bottom Paste Mask Layer", "#800000", "#400000", True),
    (9, "TOP_ASSEMBLY", "Top Assembly Layer", "#33cc99", "#19664c", True),
    (10, "BOT_ASSEMBLY", "Bottom Assembly Layer", "#5555ff", "#2a2a7f", True),
    (11, "OUTLINE", "Board Outline Layer", "#ff00ff", "#7f007f", True),
    (12, "MULTI", "Multi-Layer", "#c0c0c0", "#606060", True),
    (13, "DOCUMENT", "Document Layer", "#ffffff", "#7f7f7f", True),
    (14, "MECHANICAL", "Mechanical Layer", "#f022f0", "#781178", True),
    (47, "HOLE", "Hole Layer", "#222222", "#111111", True),
    (361, "SUBSTRATE", "Dielectric1", "#000000", "#000000", False),
)

PRIMITIVES = (
    "ALL",
    "COMPONENT",
    "PROPERTY",
    "COMPONENTSILK",
    "TRACK",
    "VIA",
    "PAD",
    "NETWORK",
    "GROUP",
    "TEXT",
    "IMAGE",
    "FILL",
    "REGION",
    "POUR",
    "DIMENSION",
    "HOLE",
)


@dataclass(frozen=True)
class PixelRectangle:
    x0: int
    y0: int
    x1: int
    y1: int


@dataclass(frozen=True)
class BinaryImage:
    width_px: int
    height_px: int
    rectangles: list[PixelRectangle]


@dataclass(frozen=True)
class ColorSilkImage:
    width_px: int
    height_px: int
    file_name: str
    data_url: str


@dataclass(frozen=True)
class LayerSpec:
    source: Path
    kind: str
    x: float
    y: float


@dataclass(frozen=True)
class PositionedLayer:
    kind: str
    x: float
    y: float
    binary_image: BinaryImage | None = None
    color_image: ColorSilkImage | None = None


@dataclass(frozen=True)
class ProjectArtifact:
    log_text: str
    project_json: dict[str, Any]
    epru_name: str
    primitive_count: int


def compact_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        allow_nan=False,
    )


def compound_id(kind: str, value: Any) -> str:
    return compact_json([kind, value])


class LogWriter:
    def __init__(self, client_uuid: str) -> None:
        self.client_uuid = client_uuid
        self.ticket = 0
        self.lines: list[str] = []

    def next_ticket(self) -> int:
        self.ticket += 1
        return self.ticket

    def document(self, doc_type: str, uuid: str, now_ms: int) -> None:
        outer = {"type": "DOCHEAD", "ticket": self.next_ticket()}
        inner = {
            "docType": doc_type,
            "client": self.client_uuid,
            "uuid": uuid,
            "updateTime": now_ms,
            "version": str(now_ms),
            "user": {"uuid": uuid},
        }
        self.lines.append(f"{compact_json(outer)}||{compact_json(inner)}|")

    def record(self, record_type: str, data: Any, record_id: str | None = None) -> None:
        outer: dict[str, Any] = {
            "type": record_type,
            "ticket": self.next_ticket(),
        }
        if record_id is not None:
            outer["id"] = record_id
        self.lines.append(f"{compact_json(outer)}||{compact_json(data)}|")

    def text(self) -> str:
        return "\n".join(self.lines) + "\n"


def decode_image(path: str | Path) -> tuple[Path, np.ndarray]:
    source = Path(path)
    if not source.is_file():
        raise FileNotFoundError(f"Image does not exist: {source}")
    encoded = np.fromfile(source, dtype=np.uint8)
    image = cv2.imdecode(encoded, cv2.IMREAD_UNCHANGED)
    if image is None:
        raise ValueError(f"Unsupported or damaged image: {source}")
    return source, image


def read_binary_image(path: str | Path) -> BinaryImage:
    source, image = decode_image(path)
    if image.ndim != 2:
        raise ValueError(
            f"ENIG layer must be a C++-processed grayscale image: {source}"
        )
    values = np.unique(image)
    if not np.all(np.isin(values, (0, 255))):
        sample = ", ".join(str(int(value)) for value in values[:8])
        raise ValueError(
            "ENIG layer must be a pure black/white image. "
            f"Found pixel values including: {sample}"
        )
    height_px, width_px = image.shape
    rectangles = active_rectangles(np.flipud(image == 0))
    if not rectangles:
        raise ValueError("ENIG layer contains no black pixels")
    return BinaryImage(
        width_px=width_px,
        height_px=height_px,
        rectangles=rectangles,
    )


def read_color_silk_image(path: str | Path) -> ColorSilkImage:
    source, image = decode_image(path)
    height_px, width_px = image.shape[:2]
    success, png = cv2.imencode(".png", image)
    if not success:
        raise ValueError(f"Cannot encode color silkscreen image: {source}")
    data_url = (
        "data:image/png;base64,"
        + base64.b64encode(png.tobytes()).decode("ascii")
    )
    return ColorSilkImage(
        width_px=width_px,
        height_px=height_px,
        file_name=f"{source.stem}.png",
        data_url=data_url,
    )


def active_rectangles(active: np.ndarray) -> list[PixelRectangle]:
    """Losslessly merge equal horizontal black-pixel runs across rows."""

    if active.ndim != 2:
        raise ValueError("active mask must be two-dimensional")

    open_rectangles: dict[tuple[int, int], int] = {}
    rectangles: list[PixelRectangle] = []
    for y, row in enumerate(active):
        padded = np.concatenate(
            (np.array([False]), row.astype(bool), np.array([False]))
        )
        transitions = np.flatnonzero(padded[1:] != padded[:-1])
        runs = {
            (int(transitions[index]), int(transitions[index + 1]))
            for index in range(0, len(transitions), 2)
        }
        for run, start_y in list(open_rectangles.items()):
            if run not in runs:
                rectangles.append(PixelRectangle(run[0], start_y, run[1], y))
                del open_rectangles[run]
        for run in runs:
            open_rectangles.setdefault(run, y)

    final_y = active.shape[0]
    for run, start_y in open_rectangles.items():
        rectangles.append(PixelRectangle(run[0], start_y, run[1], final_y))
    rectangles.sort(key=lambda item: (item.y0, item.x0, item.y1, item.x1))
    return rectangles


def layer_payload(
    layer_type: str,
    name: str,
    active_color: str,
    inactive_color: str,
    use: bool,
) -> dict[str, Any]:
    return {
        "layerType": layer_type,
        "layerName": name,
        "use": use,
        "show": use,
        "locked": False,
        "activeColor": active_color,
        "activateTransparency": 1,
        "inactiveColor": inactive_color,
        "inactiveTransparency": 1,
    }


def normalize_color(value: str) -> str:
    if not re.fullmatch(r"#[0-9a-fA-F]{6}", value):
        raise ValueError("solder_mask_color must use #RRGGBB format")
    return value.upper()


def write_pcb_defaults(
    writer: LogWriter,
    width_units: float,
    height_units: float,
    solder_mask_color: str,
) -> None:
    writer.record(
        "CANVAS",
        {
            "originX": width_units / 2,
            "originY": height_units / 2,
            "unit": "mm",
            "gridXSize": 5,
            "gridYSize": 5,
            "snapXSize": 1,
            "snapYSize": 1,
            "altSnapXSize": 0.5,
            "altSnapYSize": 0.5,
            "gridType": "OUTLETS",
            "multiGridType": "NONE",
            "multiGridRatio": 5,
            "highlightValue": 0.5,
        },
        "CANVAS",
    )
    for layer_id, layer_type, name, active, inactive, use in LAYERS:
        if layer_id in (LAYER_IDS["top-mask"], LAYER_IDS["bottom-mask"]):
            active = solder_mask_color
            inactive = solder_mask_color
        writer.record(
            "LAYER",
            layer_payload(layer_type, name, active, inactive, use),
            compound_id("LAYER", layer_id),
        )

    physical_layers = (
        (3, None, 0.0, None, None, 1),
        (7, None, 0.0, None, None, 2),
        (5, "", 0.394, 3.3, 0.02, 3),
        (1, None, 1.379, None, None, 4),
        (361, "FR4", 59.449, 4.5, 0.0, 5),
        (2, None, 1.379, None, None, 6),
        (6, "", 0.394, 3.3, 0.02, 7),
        (8, None, 0.0, None, None, 8),
        (4, None, 0.0, None, None, 9),
    )
    for layer_id, material, thickness, permittivity, loss, z_index in physical_layers:
        writer.record(
            "LAYER_PHYS",
            {
                "material": material,
                "thickness": thickness,
                "permittivity": permittivity,
                "lossTangent": loss,
                "isKeepIsland": True,
                "zIndex": z_index,
            },
            compound_id("LAYER_PHYS", layer_id),
        )

    writer.record("ACTIVE_LAYER", {"layerId": 1}, "ACTIVE_LAYER")
    writer.record(
        "NET",
        {
            "netType": None,
            "specialColor": None,
            "retLine": True,
            "differentialName": None,
            "isPositiveNet": False,
            "equalLengthGroupName": None,
        },
        compound_id("NET", ""),
    )
    writer.record("RULE_TEMPLATE", {"name": ""}, "RULE_TEMPLATE")
    for primitive in PRIMITIVES:
        writer.record(
            "PRIMITIVE",
            {"display": True, "pick": primitive != "NETWORK"},
            compound_id("PRIMITIVE", primitive),
        )
    for silk_layer in (3, 4):
        writer.record(
            "SILK_OPTS",
            {"defaultColor": "#FFFFFF", "baseColor": solder_mask_color},
            compound_id("SILK_OPTS", silk_layer),
        )
    writer.record(
        "PREFERENCE",
        {
            "startTrackWidthFollowLast": True,
            "lastTrackWidth": 4.6,
            "snap": True,
            "routingMode": "OBSTRUCT",
            "routingCorner": "R90",
            "removeLoop": False,
            "trackFollow": False,
            "realTimeUpdateUnusedLayers": False,
        },
        "PREFERENCE",
    )
    writer.record(
        "PANELIZE",
        {
            "on": False,
            "row": 1,
            "column": 1,
            "rowSpacing": 0,
            "columnSpacing": 0,
            "onlyOutline": True,
        },
        "PANELIZE",
    )


def rectangle_path(x0: float, y0: float, x1: float, y1: float) -> list[list[Any]]:
    return [[x0, y0, "L", x1, y0, x1, y1, x0, y1, x0, y0]]


def write_fill(
    writer: LogWriter,
    element_id: str,
    layer_id: int,
    path: list[list[Any]],
    z_index: int,
) -> None:
    writer.record(
        "FILL",
        {
            "partitionId": "",
            "groupId": 0,
            "netName": "",
            "layerId": layer_id,
            "width": 0.2,
            "fillStyle": "SOLID",
            "path": path,
            "locked": False,
            "zIndex": z_index,
            "isBridgingCopper": False,
            "networkList": [],
            "refs": [],
        },
        element_id,
    )


def safe_project_name(name: str) -> str:
    cleaned = "".join(character for character in name if character not in "\\/:*?\"<>|")
    return cleaned.strip() or "img2enig"


def build_project(
    layers: list[PositionedLayer],
    canvas_width_px: int,
    canvas_height_px: int,
    width_mm: float,
    height_mm: float,
    project_name: str,
    solder_mask_color: str,
) -> ProjectArtifact:
    solder_mask_color = normalize_color(solder_mask_color)
    if canvas_width_px <= 0 or canvas_height_px <= 0:
        raise ValueError("Canvas dimensions must be greater than zero")
    if width_mm <= 0 or height_mm <= 0:
        raise ValueError("Physical dimensions must be greater than zero")

    project_uuid = secrets.token_hex(8)
    board_uuid = secrets.token_hex(8)
    pcb_uuid = secrets.token_hex(8)
    writer = LogWriter(secrets.token_hex(8))
    now_ms = int(time.time() * 1000)
    margin_mm = 1.0
    board_width_units = (width_mm + margin_mm * 2) * UNITS_PER_MM
    board_height_units = (height_mm + margin_mm * 2) * UNITS_PER_MM
    margin_units = margin_mm * UNITS_PER_MM
    pixel_width_units = width_mm / canvas_width_px * UNITS_PER_MM
    pixel_height_units = height_mm / canvas_height_px * UNITS_PER_MM

    writer.document("BOARD", board_uuid, now_ms)
    writer.record("META", {"title": "Board1", "zIndex": None}, "META")
    writer.record("META_MODIFY", {"updateTime": now_ms}, "META_MODIFY")
    writer.document("PCB", pcb_uuid, now_ms)
    write_pcb_defaults(writer, board_width_units, board_height_units, solder_mask_color)

    fill_count = sum(
        len(layer.binary_image.rectangles) * 2
        for layer in layers
        if layer.binary_image is not None
    )
    if fill_count:
        writer.record(
            "ELE_PLACEHOLDER",
            {"dataType": "FILL", "max": fill_count},
            "placeholder1",
        )

    primitive_count = 0

    def write_rectangles(layer: PositionedLayer) -> None:
        nonlocal primitive_count
        artwork = layer.binary_image
        if artwork is None:
            return
        bottom = canvas_height_px - layer.y - artwork.height_px
        for rectangle in artwork.rectangles:
            path = rectangle_path(
                margin_units + (layer.x + rectangle.x0) * pixel_width_units,
                margin_units + (bottom + rectangle.y0) * pixel_height_units,
                margin_units + (layer.x + rectangle.x1) * pixel_width_units,
                margin_units + (bottom + rectangle.y1) * pixel_height_units,
            )
            for layer_id in (LAYER_IDS["top-copper"], LAYER_IDS["top-mask"]):
                primitive_count += 1
                write_fill(
                    writer,
                    f"e{primitive_count}",
                    layer_id,
                    path,
                    primitive_count,
                )

    color_count = sum(layer.color_image is not None for layer in layers)
    if color_count:
        writer.record(
            "ELE_PLACEHOLDER",
            {"dataType": "OBJ", "max": color_count},
            "placeholder-color-silk",
        )

    for layer in reversed(layers):
        if layer.kind == "enig":
            write_rectangles(layer)
        elif layer.kind == "silk" and layer.color_image is not None:
            artwork = layer.color_image
            bottom = canvas_height_px - layer.y - artwork.height_px
            primitive_count += 1
            writer.record(
                "OBJ",
                {
                    "partitionId": None,
                    "groupId": 0,
                    "locked": False,
                    "zIndex": primitive_count,
                    "layerId": LAYER_IDS["top-silk"],
                    "fileName": artwork.file_name,
                    "startX": margin_units + layer.x * pixel_width_units,
                    "startY": margin_units + bottom * pixel_height_units,
                    "width": artwork.width_px * pixel_width_units,
                    "height": artwork.height_px * pixel_height_units,
                    "angle": 0,
                    "mirror": False,
                    "path": artwork.data_url,
                },
                f"e{primitive_count}",
            )

    writer.record(
        "ELE_PLACEHOLDER",
        {"dataType": "POLY", "max": 1},
        "placeholder2",
    )
    primitive_count += 1
    writer.record(
        "POLY",
        {
            "partitionId": "",
            "groupId": 0,
            "netName": "",
            "layerId": LAYER_IDS["outline"],
            "width": 1.0,
            "path": [
                0.0,
                0.0,
                "L",
                board_width_units,
                0.0,
                board_width_units,
                board_height_units,
                0.0,
                board_height_units,
                0.0,
                0.0,
            ],
            "locked": False,
            "zIndex": primitive_count,
            "polyType": "NORMAL",
        },
        f"e{primitive_count}",
    )

    writer.record(
        "META",
        {
            "title": "PCB1",
            "parent": "",
            "source": "",
            "board": board_uuid,
            "zIndex": None,
        },
        "META",
    )
    writer.document("CONFIG", "CONFIG", now_ms)
    writer.record(
        "UNIVERSAL",
        {
            "allowLibRename": True,
            "defaultNetName": True,
            "wireMultipleNet": True,
            "netFlagCrossLayerConnection": True,
            "netLabelCrossPageConnection": True,
            "busGenerateNetClass": True,
            "relevanceDisplayRow": "SINGLE",
            "relevanceBelongSchPage": "NAME",
            "relevanceLocation": "ZONE",
        },
        "UNIVERSAL",
    )
    writer.record("META", {"defaultSheet": pcb_uuid}, "META")

    return ProjectArtifact(
        log_text=writer.text(),
        project_json={
            "title": safe_project_name(project_name),
            "cbb_project": False,
            "editorVersion": EDITOR_VERSION,
            "introduction": "Generated by img2enig",
            "description": "Artwork converted to ENIG and full-color silkscreen geometry.",
            "tags": "[]",
        },
        epru_name=f"{project_uuid}.epru",
        primitive_count=primitive_count,
    )


def parse_log_line(line: str) -> tuple[dict[str, Any], Any]:
    if not line.endswith("|") or "||" not in line:
        raise ValueError("Invalid V3 log framing")
    outer_text, inner_text = line[:-1].split("||", 1)
    return json.loads(outer_text), json.loads(inner_text)


def write_epro2(path: str | Path, artifact: ProjectArtifact) -> Path:
    output = Path(path)
    if output.suffix.lower() != ".epro2":
        output = output.with_suffix(".epro2")
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            "project2.json",
            json.dumps(artifact.project_json, ensure_ascii=False, indent=4),
        )
        archive.writestr(artifact.epru_name, artifact.log_text)
    return output


def validate_epro2(path: str | Path) -> dict[str, Any]:
    with zipfile.ZipFile(path, "r") as archive:
        names = archive.namelist()
        if any(Path(name).is_absolute() or ".." in Path(name).parts for name in names):
            raise ValueError("Unsafe path in epro2 archive")
        if "project2.json" not in names:
            raise ValueError("epro2 is missing project2.json")
        epru_names = [name for name in names if name.lower().endswith(".epru")]
        if len(epru_names) != 1:
            raise ValueError("epro2 must contain exactly one epru log")
        project_json = json.loads(archive.read("project2.json"))
        lines = archive.read(epru_names[0]).decode("utf-8").splitlines()

    document_types: list[str] = []
    fill_layers: set[int] = set()
    object_layers: set[int] = set()
    for line in lines:
        outer, inner = parse_log_line(line)
        if outer.get("type") == "DOCHEAD":
            document_types.append(str(inner.get("docType", "")))
        elif outer.get("type") == "FILL":
            fill_layers.add(int(inner["layerId"]))
        elif outer.get("type") == "OBJ":
            object_layers.add(int(inner["layerId"]))
    missing = {"BOARD", "PCB", "CONFIG"}.difference(document_types)
    if missing:
        raise ValueError(f"Missing required documents: {sorted(missing)}")
    return {
        "title": project_json.get("title"),
        "editorVersion": project_json.get("editorVersion"),
        "documents": document_types,
        "records": len(lines),
        "fillLayers": sorted(fill_layers),
        "objectLayers": sorted(object_layers),
        "artworkLayers": sorted(fill_layers | object_layers),
        "epru": epru_names[0],
    }


def prepare_positioned_layers(
    specs: list[LayerSpec],
    canvas_width_px: int,
    canvas_height_px: int,
) -> list[PositionedLayer]:
    if not specs:
        raise ValueError("At least one layer is required")
    if canvas_width_px <= 0 or canvas_height_px <= 0:
        raise ValueError("Canvas dimensions must be greater than zero")
    layers: list[PositionedLayer] = []
    for spec in specs:
        if spec.kind not in ("enig", "silk"):
            raise ValueError("Layer type must be enig or silk")
        if not np.isfinite(spec.x) or not np.isfinite(spec.y):
            raise ValueError("Layer coordinates must be finite")
        if spec.x < 0 or spec.y < 0:
            raise ValueError("Layer coordinates must not be negative")
        if spec.kind == "enig":
            binary = read_binary_image(spec.source)
            width_px, height_px = binary.width_px, binary.height_px
            layer = PositionedLayer("enig", spec.x, spec.y, binary)
        else:
            color = read_color_silk_image(spec.source)
            width_px, height_px = color.width_px, color.height_px
            layer = PositionedLayer("silk", spec.x, spec.y, color_image=color)
        if (spec.x + width_px > canvas_width_px + 1e-9
                or spec.y + height_px > canvas_height_px + 1e-9):
            raise ValueError("Layer lies outside the canvas")
        layers.append(layer)
    return layers


def convert_layers(
    specs: list[LayerSpec],
    output: str | Path,
    canvas_width_px: int,
    canvas_height_px: int,
    width_mm: float | None = None,
    height_mm: float | None = None,
    project_name: str | None = None,
    solder_mask_color: str = "#ECEBE6",
) -> dict[str, Any]:
    layers = prepare_positioned_layers(specs, canvas_width_px, canvas_height_px)
    physical_width = 50.0 if width_mm is None else width_mm
    physical_height = (
        physical_width * canvas_height_px / canvas_width_px
        if height_mm is None else height_mm
    )
    artifact = build_project(
        layers,
        canvas_width_px,
        canvas_height_px,
        physical_width,
        physical_height,
        project_name or Path(output).stem,
        solder_mask_color,
    )
    output_path = write_epro2(output, artifact)
    validation = validate_epro2(output_path)
    expected_layers: set[int] = set()
    if any(layer.kind == "enig" for layer in layers):
        expected_layers.update((1, 5))
    if any(layer.kind == "silk" for layer in layers):
        expected_layers.add(3)
    if set(validation["artworkLayers"]) != expected_layers:
        raise ValueError("Generated project does not contain the expected artwork layers")
    return {
        "output": str(output_path),
        "width_mm": physical_width,
        "height_mm": physical_height,
        "layers": len(layers),
        "primitives": artifact.primitive_count,
        "validation": validation,
    }


def read_manifest(path: str | Path) -> tuple[list[LayerSpec], dict[str, Any]]:
    manifest_path = Path(path)
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not isinstance(data.get("layers"), list):
        raise ValueError("Manifest must contain a layers array")
    specs: list[LayerSpec] = []
    for item in data["layers"]:
        if not isinstance(item, dict):
            raise ValueError("Each manifest layer must be an object")
        if item.get("visible", True) is False:
            continue
        try:
            source = Path(item["source"])
            kind = str(item["type"])
            x = float(item["x"])
            y = float(item["y"])
        except (KeyError, TypeError, ValueError) as error:
            raise ValueError(
                "Each manifest layer requires source, type, x, and y"
            ) from error
        if not source.is_absolute():
            source = manifest_path.parent / source
        specs.append(LayerSpec(source, kind, x, y))
    canvas = data.get("canvas", {})
    if not isinstance(canvas, dict):
        raise ValueError("Manifest canvas must be an object")
    settings = {
        "canvas_width_px": canvas.get("width"),
        "canvas_height_px": canvas.get("height"),
        "width_mm": canvas.get("widthMm", data.get("widthMm")),
        "height_mm": canvas.get("heightMm", data.get("heightMm")),
        "project_name": data.get("projectName"),
        "solder_mask_color": data.get("solderMaskColor"),
    }
    return specs, settings


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Convert positioned ENIG masks and full-color silkscreen images into "
            "an EasyEDA Pro PCB artwork project."
        )
    )
    parser.add_argument("-o", "--output", type=Path, required=True)
    parser.add_argument("--width-mm", type=float)
    parser.add_argument("--height-mm", type=float)
    parser.add_argument("--canvas-width", type=int, help="canvas width in pixels")
    parser.add_argument("--canvas-height", type=int, help="canvas height in pixels")
    parser.add_argument(
        "--solder-mask-color",
        help="PCB solder-mask color as #RRGGBB",
    )
    parser.add_argument(
        "--layer",
        action="append",
        nargs=4,
        metavar=("IMAGE", "TYPE", "X", "Y"),
        help="repeatable layer: image, enig|silk, top-left X, top-left Y",
    )
    parser.add_argument("--manifest", type=Path, help="JSON layer manifest")
    parser.add_argument("--project-name")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if bool(args.layer) == bool(args.manifest):
            raise ValueError("Use either --layer or --manifest")
        specs: list[LayerSpec]
        settings: dict[str, Any] = {}
        if args.manifest:
            specs, settings = read_manifest(args.manifest)
        else:
            specs = [
                LayerSpec(Path(source), kind, float(x), float(y))
                for source, kind, x, y in args.layer
            ]

        def setting(name: str, value: Any, default: Any = None) -> Any:
            if value is not None:
                return value
            manifest_value = settings.get(name)
            return default if manifest_value is None else manifest_value

        canvas_width = setting("canvas_width_px", args.canvas_width)
        canvas_height = setting("canvas_height_px", args.canvas_height)
        if canvas_width is None or canvas_height is None:
            raise ValueError("Canvas width and height are required")
        result = convert_layers(
            specs=specs,
            output=args.output,
            canvas_width_px=int(canvas_width),
            canvas_height_px=int(canvas_height),
            width_mm=(
                float(value)
                if (value := setting("width_mm", args.width_mm)) is not None
                else None
            ),
            height_mm=(
                float(value)
                if (value := setting("height_mm", args.height_mm)) is not None
                else None
            ),
            project_name=setting("project_name", args.project_name),
            solder_mask_color=setting(
                "solder_mask_color", args.solder_mask_color, "#ECEBE6"
            ),
        )
        print(json.dumps(result, ensure_ascii=False, indent=4))
        return 0
    except Exception as error:
        print(f"img2enig: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
