"""Write design deliverables (SVG, DXF, glTF, PDF, BOM) without extra libraries."""

from __future__ import annotations

import json
from pathlib import Path

from src.models.schemas import AnalyzePlotRequest, DesignDecision, ValidationReport
from src.processors.layout import Room
from src.utils.knowledge import load_ibc_minimums, load_material_specs


def _svg_point(plot_d: float, pad: float, scale: float, x: float, y: float) -> tuple[float, float]:
    return pad + x * scale, pad + (plot_d - y) * scale


def _opening_markup(room: Room, plot_d: float, pad: float, scale: float) -> str:
    parts: list[str] = []
    for opening in room.openings:
        if opening.wall == "south":
            x1, y1 = _svg_point(plot_d, pad, scale, room.x + opening.offset, room.y)
            x2, y2 = _svg_point(plot_d, pad, scale, room.x + opening.offset + opening.width, room.y)
        elif opening.wall == "north":
            x1, y1 = _svg_point(plot_d, pad, scale, room.x + opening.offset, room.y + room.depth)
            x2, y2 = _svg_point(plot_d, pad, scale, room.x + opening.offset + opening.width, room.y + room.depth)
        elif opening.wall == "west":
            x1, y1 = _svg_point(plot_d, pad, scale, room.x, room.y + opening.offset)
            x2, y2 = _svg_point(plot_d, pad, scale, room.x, room.y + opening.offset + opening.width)
        else:
            x1, y1 = _svg_point(plot_d, pad, scale, room.x + room.width, room.y + opening.offset)
            x2, y2 = _svg_point(plot_d, pad, scale, room.x + room.width, room.y + opening.offset + opening.width)
        color = "#1d4e89" if opening.kind == "window" else "#b85c38"
        parts.append(
            f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" '
            f'stroke="{color}" stroke-width="4" stroke-linecap="round"/>'
        )
    return "".join(parts)


def write_floor_plan_svg(path: Path, rooms: list[Room], plot_w: float, plot_d: float) -> None:
    scale = 12.0
    pad = 40
    width = int(plot_w * scale + pad * 2)
    height = int(plot_d * scale + pad * 2)
    svg_rooms = []
    for room in rooms:
        x = pad + room.x * scale
        # SVG y grows downward; north is up so flip depth.
        y = pad + (plot_d - room.y - room.depth) * scale
        w = room.width * scale
        d = room.depth * scale
        label = f"{room.name.replace('_', ' ').title()} ({room.area} sf)"
        svg_rooms.append(
            f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{d:.1f}" '
            f'fill="#f7f1e3" stroke="#2c3e50" stroke-width="2"/>'
            f'<text x="{x + w / 2:.1f}" y="{y + d / 2:.1f}" text-anchor="middle" '
            f'dominant-baseline="middle" font-size="11" font-family="sans-serif">{label}</text>'
            f"{_opening_markup(room, plot_d, pad, scale)}"
        )
    body = "\n".join(svg_rooms)
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}">'
        f'<rect width="100%" height="100%" fill="#ffffff"/>'
        f'<text x="{pad}" y="24" font-size="16" font-family="sans-serif">VastuVision floor plan</text>'
        f'<text x="{width - pad}" y="24" text-anchor="end" font-size="12" font-family="sans-serif">N ↑</text>'
        f"{body}</svg>"
    )
    path.write_text(svg, encoding="utf-8")


def write_dxf(path: Path, rooms: list[Room], plot_w: float, plot_d: float) -> None:
    lines: list[str] = ["0", "SECTION", "2", "ENTITIES"]

    def add_rect(x: float, y: float, w: float, d: float) -> None:
        corners = [(x, y), (x + w, y), (x + w, y + d), (x, y + d)]
        for (x1, y1), (x2, y2) in zip(corners, corners[1:] + corners[:1]):
            lines.extend(
                [
                    "0",
                    "LINE",
                    "8",
                    "WALLS",
                    "10",
                    f"{x1:.3f}",
                    "20",
                    f"{y1:.3f}",
                    "11",
                    f"{x2:.3f}",
                    "21",
                    f"{y2:.3f}",
                ]
            )

    add_rect(0.0, 0.0, plot_w, plot_d)
    for room in rooms:
        add_rect(room.x, room.y, room.width, room.depth)
        for opening in room.openings:
            if opening.wall == "south":
                x1, y1 = room.x + opening.offset, room.y
                x2, y2 = x1 + opening.width, room.y
            elif opening.wall == "north":
                x1, y1 = room.x + opening.offset, room.y + room.depth
                x2, y2 = x1 + opening.width, room.y + room.depth
            elif opening.wall == "west":
                x1, y1 = room.x, room.y + opening.offset
                x2, y2 = room.x, y1 + opening.width
            else:
                x1, y1 = room.x + room.width, room.y + opening.offset
                x2, y2 = room.x + room.width, y1 + opening.width
            lines.extend(
                [
                    "0",
                    "LINE",
                    "8",
                    "OPENINGS",
                    "10",
                    f"{x1:.3f}",
                    "20",
                    f"{y1:.3f}",
                    "11",
                    f"{x2:.3f}",
                    "21",
                    f"{y2:.3f}",
                ]
            )
    lines.extend(["0", "ENDSEC", "0", "EOF"])
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_gltf(path: Path, rooms: list[Room], plot_w: float, plot_d: float) -> None:
    nodes = [{"name": "plot", "mesh": 0}]
    for room in rooms:
        nodes.append(
            {
                "name": room.name,
                "translation": [room.x + room.width / 2, 0.0, room.y + room.depth / 2],
                "scale": [room.width, 9.0, room.depth],
                "mesh": 1,
            }
        )
    gltf = {
        "asset": {"version": "2.0", "generator": "VastuVision AI"},
        "scenes": [{"nodes": list(range(len(nodes)))}],
        "nodes": nodes,
        "meshes": [
            {
                "name": "slab",
                "primitives": [{"attributes": {"POSITION": 0}, "mode": 4}],
            },
            {
                "name": "room_box",
                "primitives": [{"attributes": {"POSITION": 0}, "mode": 4}],
            },
        ],
        "accessors": [
            {
                "bufferView": 0,
                "componentType": 5126,
                "count": 3,
                "type": "VEC3",
                "max": [plot_w, 0.1, plot_d],
                "min": [0.0, 0.0, 0.0],
            }
        ],
        "bufferViews": [{"buffer": 0, "byteOffset": 0, "byteLength": 36}],
        "buffers": [{"byteLength": 36, "uri": "data:application/octet-stream;base64,AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA="}],
    }
    path.write_text(json.dumps(gltf, indent=2), encoding="utf-8")


def write_sun_path_svg(path: Path, preferred_exposure: str, lat: float) -> None:
    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" width="480" height="320">
  <rect width="100%" height="100%" fill="#0b1d36"/>
  <circle cx="240" cy="200" r="90" fill="none" stroke="#f4d35e" stroke-width="2"/>
  <circle cx="240" cy="110" r="18" fill="#f4d35e"/>
  <text x="240" y="28" fill="#fff" text-anchor="middle" font-size="16" font-family="sans-serif">Sun path ({lat:.2f}°)</text>
  <text x="240" y="300" fill="#f4d35e" text-anchor="middle" font-size="14" font-family="sans-serif">Preferred exposure: {preferred_exposure}</text>
</svg>
"""
    path.write_text(svg, encoding="utf-8")


def write_ventilation_svg(path: Path, wind_direction: str) -> None:
    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" width="480" height="280">
  <rect width="100%" height="100%" fill="#eef6fb"/>
  <rect x="90" y="70" width="300" height="140" fill="#fff" stroke="#1b4965" stroke-width="3"/>
  <line x1="40" y1="140" x2="440" y2="140" stroke="#5fa8d3" stroke-width="6" marker-end="url(#arrow)"/>
  <text x="240" y="36" text-anchor="middle" font-size="16" font-family="sans-serif">Cross ventilation</text>
  <text x="240" y="250" text-anchor="middle" font-size="14" font-family="sans-serif">Prevailing wind: {wind_direction}</text>
</svg>
"""
    path.write_text(svg, encoding="utf-8")


def write_bom(path: Path, rooms: list[Room], wall_thickness_mm: int) -> dict:
    specs = load_material_specs()
    ibc = load_ibc_minimums()
    floor_area = round(sum(room.area for room in rooms), 2)
    wall_length = round(sum(2 * (room.width + room.depth) for room in rooms), 2)
    window_count = sum(1 for room in rooms for opening in room.openings if opening.kind == "window")
    door_count = sum(1 for room in rooms for opening in room.openings if opening.kind == "door")
    bom = {
        "floor_area_sqft": floor_area,
        "estimated_wall_length_ft": wall_length,
        "wall_thickness_mm": wall_thickness_mm,
        "window_count": window_count,
        "door_count": door_count,
        "ibc_minimums": ibc,
        "materials": [
            {
                "component": name,
                "specification": spec.get("material"),
                "u_value": spec.get("u_value"),
                "qty_basis": "envelope",
            }
            for name, spec in specs.items()
        ],
        "rooms": [{"name": room.name, "area_sqft": room.area, "zone": room.zone} for room in rooms],
    }
    path.write_text(json.dumps(bom, indent=2), encoding="utf-8")
    return bom


def write_pdf_report(
    path: Path,
    request: AnalyzePlotRequest,
    decisions: list[DesignDecision],
    validation: ValidationReport,
    summary: dict,
) -> None:
    lines = [
        "VastuVision AI Design Report",
        f"Address: {request.location.address}",
        f"Plot: {request.plot.dimensions.length} x {request.plot.dimensions.width} {request.plot.dimensions.unit}",
        f"Orientation: {request.plot.orientation}; road facing: {request.plot.road_facing}",
        f"Total area: {summary.get('total_area')}",
        f"Energy: {validation.energy_efficiency}; compliant: {validation.compliant}",
        "",
        "Design decisions:",
    ]
    for decision in decisions:
        lines.append(f"- {decision.agent}: {decision.decision} ({decision.reasoning})")
        if decision.details.get("yielded_to_science"):
            lines.append("  conflict resolved toward the higher-weight scientific guidance")
    if validation.issues:
        lines.append("")
        lines.append("Issues: " + "; ".join(validation.issues))
    text = "\n".join(lines)
    _write_minimal_pdf(path, text)


def _write_minimal_pdf(path: Path, text: str) -> None:
    escaped = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    content = f"BT /F1 11 Tf 48 750 Td 14 TL ({escaped.replace(chr(10), ') Tj T* (')}) Tj ET"
    objects = [
        "<< /Type /Catalog /Pages 2 0 R >>",
        "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
        f"<< /Length {len(content.encode('latin-1', 'replace'))} >>\nstream\n{content}\nendstream",
        "<< /Type /Font /Subtype /Type1 /BaseFont /Courier >>",
    ]
    pdf = ["%PDF-1.4"]
    offsets = [0]
    cursor = 9
    for index, obj in enumerate(objects, start=1):
        encoded = f"{index} 0 obj\n{obj}\nendobj\n"
        offsets.append(cursor)
        pdf.append(encoded.rstrip("\n"))
        cursor += len(encoded.encode("latin-1", "replace"))
    xref_pos = cursor
    xref = ["xref", "0 6", "0000000000 65535 f "]
    for offset in offsets[1:]:
        xref.append(f"{offset:010d} 00000 n ")
    trailer = f"trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n{xref_pos}\n%%EOF"
    pdf.append("\n".join(xref))
    pdf.append(trailer)
    path.write_bytes("\n".join(pdf).encode("latin-1", "replace"))
