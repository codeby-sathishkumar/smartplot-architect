"""Design output assembly utilities."""

from __future__ import annotations

from pathlib import Path
from uuid import UUID, uuid4

from src.config.settings import settings
from src.models.schemas import AnalyzePlotRequest, DesignDecision, ValidationReport
from src.processors.artifacts import (
    write_bom,
    write_dxf,
    write_floor_plan_svg,
    write_gltf,
    write_pdf_report,
    write_sun_path_svg,
    write_ventilation_svg,
)
from src.processors.layout import build_room_layout


def _wall_thickness_mm(decisions: list[DesignDecision]) -> int:
    for decision in decisions:
        if decision.agent != "structural_engineer":
            continue
        thickness = decision.details.get("wall_thickness_mm")
        if isinstance(thickness, (int, float)):
            return int(thickness)
        if "mm" in decision.decision:
            digits = "".join(ch for ch in decision.decision.split("mm", 1)[0] if ch.isdigit())
            if digits:
                return int(digits)
    return 230


def _vastu_compliance(request: AnalyzePlotRequest, decisions: list[DesignDecision]) -> int:
    if not request.requirements.apply_vastu:
        return 0
    vastu = next((decision for decision in decisions if decision.agent == "vastu_expert"), None)
    if vastu is None or not vastu.details.get("applied", True):
        return 0
    if vastu.details.get("kitchen_zone", "south-east") == "south-east" and not _kitchen_yielded(vastu):
        return 92
    if vastu.details.get("yielded_to_science"):
        return 70
    return 80


def _kitchen_yielded(decision: DesignDecision) -> bool:
    zone = str(decision.details.get("kitchen_zone") or "south-east")
    return zone != "south-east"


class DesignProcessor:
    """Converts orchestrated decisions into deliverable files and metadata."""

    def __init__(self, artifacts_dir: str | None = None) -> None:
        self.artifacts_dir = Path(artifacts_dir or settings.artifacts_dir)

    def build_outputs(
        self,
        request: AnalyzePlotRequest,
        decisions: list[DesignDecision],
        validation: ValidationReport,
        environmental: dict,
        design_id: UUID | None = None,
    ) -> tuple[UUID, dict, dict]:
        design_id = design_id or uuid4()
        output_dir = self.artifacts_dir / str(design_id)
        output_dir.mkdir(parents=True, exist_ok=True)

        rooms = build_room_layout(request, decisions)
        plot_w = request.plot.dimensions.width
        plot_d = request.plot.dimensions.length
        wall_thickness = _wall_thickness_mm(decisions)

        write_floor_plan_svg(output_dir / "floor_plan.svg", rooms, plot_w, plot_d)
        write_dxf(output_dir / "floor_plan.dxf", rooms, plot_w, plot_d)
        write_gltf(output_dir / "model.gltf", rooms, plot_w, plot_d)
        write_sun_path_svg(
            output_dir / "sun_path.svg",
            environmental.get("solar", {}).get("preferred_exposure", "south"),
            request.location.coordinates.lat,
        )
        write_ventilation_svg(
            output_dir / "ventilation.svg",
            environmental.get("wind", {}).get("prevailing_direction", "SW"),
        )
        bom = write_bom(output_dir / "bom.json", rooms, wall_thickness)

        area = round(request.plot.dimensions.length * request.plot.dimensions.width, 2)
        summary = {
            "total_area": f"{area} sq {request.plot.dimensions.unit}",
            "room_count": len(rooms),
            "optimization_score": round(sum(decision.score for decision in decisions) / max(len(decisions), 1), 2),
            "energy_efficiency": validation.energy_efficiency,
            "vastu_compliance": _vastu_compliance(request, decisions),
            "conditioned_floor_area": bom["floor_area_sqft"],
        }
        write_pdf_report(output_dir / "design_report.pdf", request, decisions, validation, summary)

        files = {
            "floor_plan_2d": f"/artifacts/{design_id}/floor_plan.svg",
            "autocad_file": f"/artifacts/{design_id}/floor_plan.dxf",
            "3d_model": f"/artifacts/{design_id}/model.gltf",
            "documentation": f"/artifacts/{design_id}/design_report.pdf",
            "sun_analysis": f"/artifacts/{design_id}/sun_path.svg",
            "ventilation_analysis": f"/artifacts/{design_id}/ventilation.svg",
            "material_specifications": f"/artifacts/{design_id}/bom.json",
        }
        return design_id, files, summary
