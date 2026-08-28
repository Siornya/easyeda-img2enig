"""Convert a prepared black/white image into EasyEDA Pro ENIG artwork."""

from __future__ import annotations

import argparse
import json
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
    "bottom-copper": 2,
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
class PreparedImage:
    width_mm: float
    height_mm: float
    pixel_width_mm: float
    pixel_height_mm: float
    rectangles: list[PixelRectangle]


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


def read_binary_image(path: str | Path, width_mm: float, height_mm: float | None) -> PreparedImage:
    source = Path(path)
    if not source.is_file():
        raise FileNotFoundError(f"Image does not exist: {source}")
    if width_mm <= 0:
        raise ValueError("width_mm must be greater than zero")
    if height_mm is not None and height_mm <= 0:
        raise ValueError("height_mm must be greater than zero")

    encoded = np.fromfile(source, dtype=np.uint8)
    image = cv2.imdecode(encoded, cv2.IMREAD_UNCHANGED)
    if image is None:
        raise ValueError(f"Unsupported or damaged image: {source}")

    if image.ndim == 2:
        gray = image
    else:
        if image.shape[2] == 4:
            color = image[:, :, :3].astype(np.float32)
            alpha = image[:, :, 3:4].astype(np.float32) / 255.0
            image = np.clip(
                color * alpha + 255.0 * (1.0 - alpha),
                0,
                255,
            ).astype(np.uint8)
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)

    values = np.unique(gray)
    if not np.all(np.isin(values, (0, 255))):
        sample = ", ".join(str(int(value)) for value in values[:8])
        raise ValueError(
            "Input must already be a pure black/white image. "
            f"Found pixel values including: {sample}"
        )

    height_px, width_px = gray.shape
    physical_height = height_mm or width_mm * height_px / width_px
    rectangles = active_rectangles(gray == 0)
    if not rectangles:
        raise ValueError("Input contains no black pixels to convert")
    return PreparedImage(
        width_mm=width_mm,
        height_mm=physical_height,
        pixel_width_mm=width_mm / width_px,
        pixel_height_mm=physical_height / height_px,
        rectangles=rectangles,
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


def write_pcb_defaults(writer: LogWriter, width_units: float, height_units: float) -> None:
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
            {"defaultColor": "#000000", "baseColor": "#FFFFFF"},
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
    return cleaned.strip() or "easyeda-img2enig"


def build_project(
    image: PreparedImage,
    project_name: str,
    side: str,
    margin_mm: float,
    include_outline: bool,
) -> ProjectArtifact:
    if side not in ("top", "bottom"):
        raise ValueError("side must be top or bottom")
    if margin_mm < 0:
        raise ValueError("margin_mm must not be negative")

    project_uuid = secrets.token_hex(8)
    board_uuid = secrets.token_hex(8)
    pcb_uuid = secrets.token_hex(8)
    writer = LogWriter(secrets.token_hex(8))
    now_ms = int(time.time() * 1000)
    safe_name = safe_project_name(project_name)

    board_width_mm = image.width_mm + margin_mm * 2
    board_height_mm = image.height_mm + margin_mm * 2
    board_width_units = board_width_mm * UNITS_PER_MM
    board_height_units = board_height_mm * UNITS_PER_MM
    margin_units = margin_mm * UNITS_PER_MM
    pixel_width_units = image.pixel_width_mm * UNITS_PER_MM
    pixel_height_units = image.pixel_height_mm * UNITS_PER_MM

    writer.document("BOARD", board_uuid, now_ms)
    writer.record("META", {"title": "Board1", "zIndex": None}, "META")
    writer.record("META_MODIFY", {"updateTime": now_ms}, "META_MODIFY")

    writer.document("PCB", pcb_uuid, now_ms)
    write_pcb_defaults(writer, board_width_units, board_height_units)
    if side == "top":
        target_layers = (LAYER_IDS["top-copper"], LAYER_IDS["top-mask"])
    else:
        target_layers = (LAYER_IDS["bottom-copper"], LAYER_IDS["bottom-mask"])

    fill_count = len(image.rectangles) * 2
    if fill_count:
        writer.record(
            "ELE_PLACEHOLDER",
            {"dataType": "FILL", "max": fill_count},
            "placeholder1",
        )

    primitive_count = 0
    for rectangle in image.rectangles:
        path = rectangle_path(
            margin_units + rectangle.x0 * pixel_width_units,
            margin_units + rectangle.y0 * pixel_height_units,
            margin_units + rectangle.x1 * pixel_width_units,
            margin_units + rectangle.y1 * pixel_height_units,
        )
        for layer_id in target_layers:
            primitive_count += 1
            write_fill(
                writer,
                f"e{primitive_count}",
                layer_id,
                path,
                primitive_count,
            )

    if include_outline:
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
            "title": safe_name,
            "cbb_project": False,
            "editorVersion": EDITOR_VERSION,
            "introduction": "Generated by easyeda-img2enig",
            "description": "Binary artwork converted to copper and solder-mask opening geometry.",
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
    for line in lines:
        outer, inner = parse_log_line(line)
        if outer.get("type") == "DOCHEAD":
            document_types.append(str(inner.get("docType", "")))
        elif outer.get("type") == "FILL":
            fill_layers.add(int(inner["layerId"]))
    missing = {"BOARD", "PCB", "CONFIG"}.difference(document_types)
    if missing:
        raise ValueError(f"Missing required documents: {sorted(missing)}")
    return {
        "title": project_json.get("title"),
        "editorVersion": project_json.get("editorVersion"),
        "documents": document_types,
        "records": len(lines),
        "fillLayers": sorted(fill_layers),
        "epru": epru_names[0],
    }


def convert(
    source: str | Path,
    output: str | Path | None,
    width_mm: float,
    height_mm: float | None,
    side: str,
    margin_mm: float,
    include_outline: bool,
    project_name: str | None,
) -> dict[str, Any]:
    source_path = Path(source)
    image = read_binary_image(source_path, width_mm, height_mm)
    artifact = build_project(
        image,
        project_name or source_path.stem,
        side,
        margin_mm,
        include_outline,
    )
    output_path = write_epro2(output or source_path.with_suffix(".epro2"), artifact)
    validation = validate_epro2(output_path)
    expected_layers = {1, 5} if side == "top" else {2, 6}
    if set(validation["fillLayers"]) != expected_layers:
        raise ValueError("Generated project does not contain the expected ENIG layers")
    return {
        "output": str(output_path),
        "width_mm": image.width_mm,
        "height_mm": image.height_mm,
        "rectangles": len(image.rectangles),
        "primitives": artifact.primitive_count,
        "validation": validation,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Convert an already-processed black/white image into matching copper "
            "and solder-mask opening geometry for ENIG artwork."
        )
    )
    parser.add_argument("source", type=Path, help="prepared black/white image or epro2")
    parser.add_argument("-o", "--output", type=Path)
    parser.add_argument("--width-mm", type=float, default=50.0)
    parser.add_argument("--height-mm", type=float)
    parser.add_argument("--side", choices=("top", "bottom"), default="top")
    parser.add_argument("--margin-mm", type=float, default=1.0)
    parser.add_argument("--no-outline", action="store_true")
    parser.add_argument("--project-name")
    parser.add_argument("--inspect", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.inspect:
            result = validate_epro2(args.source)
        else:
            result = convert(
                source=args.source,
                output=args.output,
                width_mm=args.width_mm,
                height_mm=args.height_mm,
                side=args.side,
                margin_mm=args.margin_mm,
                include_outline=not args.no_outline,
                project_name=args.project_name,
            )
        print(json.dumps(result, ensure_ascii=False, indent=4))
        return 0
    except Exception as error:
        print(f"easyeda-img2enig: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
