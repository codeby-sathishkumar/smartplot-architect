"""Scientific validators for generated designs."""

from __future__ import annotations

from src.models.schemas import AnalyzePlotRequest, DesignDecision, ValidationReport
from src.processors.layout import build_room_layout
from src.utils.knowledge import load_ibc_minimums


class ScientificValidator:
    """Applies rule-based checks to enforce science-first design quality."""

    def evaluate(self, request: AnalyzePlotRequest, environmental: dict, decisions: list[DesignDecision]) -> ValidationReport:
        preferred = str(environmental["solar"]["preferred_exposure"]).lower()
        living_aligned = any(
            decision.agent == "architect" and preferred in decision.decision.lower()
            for decision in decisions
        )
        plot_aligned = request.plot.orientation.lower().startswith(preferred[:1])
        orientation_match = 1.0 if living_aligned or plot_aligned else 0.6

        ventilation_match = any("ventilation" in decision.decision.lower() for decision in decisions)
        ventilation_score = 8.5 if ventilation_match else 6.0

        structural_match = any("load-bearing" in decision.decision.lower() for decision in decisions)
        structural_score = 9.0 if structural_match else 6.5

        sunlight_score = round(8.0 * orientation_match, 2)
        metric_scores = (sunlight_score, ventilation_score, structural_score)
        avg = sum(metric_scores) / len(metric_scores)

        issues: list[str] = []
        if not living_aligned and sunlight_score < 7.0:
            issues.append("Plot orientation is not optimal for local sun path")
        if ventilation_score < 7.0:
            issues.append("Cross-ventilation recommendation missing")
        if structural_score < 7.0:
            issues.append("Structural load validation recommendation missing")

        ibc = load_ibc_minimums()
        min_area = float(ibc.get("min_room_area_sqft", 70))
        undersized = [room.name for room in build_room_layout(request, decisions) if room.area < min_area]
        if undersized:
            issues.append("Rooms below IBC minimum area: " + ", ".join(undersized))

        if avg >= 8.5:
            energy = "A+"
        elif avg >= 8.0:
            energy = "A"
        else:
            energy = "B"

        return ValidationReport(
            sunlight_score=sunlight_score,
            ventilation_score=ventilation_score,
            structural_score=structural_score,
            energy_efficiency=energy,
            compliant=avg >= 7.5 and not undersized,
            issues=issues,
        )
