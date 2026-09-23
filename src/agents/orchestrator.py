"""Multi-agent orchestration layer powered by LangGraph."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
import logging

from src.agents.collaboration import (
    collaboration_suffix,
    peer_by_name,
    resolve_entrance,
    resolve_exclusive_zone,
    resolve_master_zone,
)
from src.agents.construction_builder import generate_construction_builder_output
from src.agents.graph import design_graph, geologist_foundation_guidance
from src.agents.site_engineer import calculate_site_access_decision, normalize_road_facing
from src.models.schemas import AnalyzePlotRequest, DesignDecision
from src.utils.knowledge import load_vastu_rules

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AgentResult:
    name: str
    decision: str
    reasoning: str
    score: float
    weight: float
    details: dict = field(default_factory=dict)


class BaseAgent(ABC):
    """Foundation contract for all SmartPlot specialist agents.

    Subclasses are expected to:
    1. Override ``name`` and ``weight`` metadata.
    2. Implement ``run`` with their domain-specific decision logic.
    3. Use ``result`` to return consistently shaped outputs.
    """

    name = "base"
    weight = 0.5

    def __init_subclass__(cls, **kwargs) -> None:
        super().__init_subclass__(**kwargs)
        if not isinstance(cls.name, str) or not cls.name:
            raise ValueError("Agent subclasses must define a non-empty string 'name'")
        if not isinstance(cls.weight, (int, float)):
            raise ValueError("Agent subclasses must define 'weight' between 0.0 and 1.0")
        if not 0.0 <= cls.weight <= 1.0:
            raise ValueError("Agent subclasses must define 'weight' between 0.0 and 1.0")

    def require_environment(self, environmental: dict, required_keys: tuple[str, ...]) -> None:
        missing = [key for key in required_keys if key not in environmental]
        if missing:
            raise KeyError(f"Missing environmental keys for {self.name}: {', '.join(missing)}")

    def result(self, decision: str, reasoning: str, score: float, details: dict | None = None) -> AgentResult:
        return AgentResult(self.name, decision, reasoning, score, self.weight, dict(details or {}))

    def revise(
        self,
        payload: AnalyzePlotRequest,
        environmental: dict,
        peers: list[AgentResult] | None = None,
        brief: dict | None = None,
    ) -> AgentResult | None:
        """Re-evaluate after every specialist has spoken during this run."""
        del brief
        return self.run(payload, environmental, peers)

    @abstractmethod
    def run(
        self,
        payload: AnalyzePlotRequest,
        environmental: dict,
        peers: list[AgentResult] | None = None,
    ) -> AgentResult:
        raise NotImplementedError


class ArchitectAgent(BaseAgent):
    name = "architect"
    weight = 1.0

    def run(
        self,
        payload: AnalyzePlotRequest,
        environmental: dict,
        peers: list[AgentResult] | None = None,
    ) -> AgentResult:
        self.require_environment(environmental, ("solar",))
        solar = environmental["solar"]
        if "preferred_exposure" not in solar:
            raise KeyError("preferred_exposure")
        preferred = solar["preferred_exposure"]
        return self.result(
            f"Primary living spaces aligned to {preferred}",
            "Optimized for natural daylight"
            + collaboration_suffix(peers, "meteorologist", "geologist", "site_engineer"),
            8.5,
            {"living_exposure": str(preferred).strip().lower(), "style": payload.requirements.style},
        )


class MeteorologistAgent(BaseAgent):
    name = "meteorologist"
    weight = 0.9

    def run(
        self,
        payload: AnalyzePlotRequest,
        environmental: dict,
        peers: list[AgentResult] | None = None,
    ) -> AgentResult:
        self.require_environment(environmental, ("wind",))
        wind = environmental["wind"]
        if "prevailing_direction" not in wind:
            raise KeyError("Missing environmental keys for meteorologist: wind.prevailing_direction")
        direction = wind["prevailing_direction"]
        return self.result(
            f"Cross-ventilation windows oriented towards {direction}",
            "Uses prevailing wind data" + collaboration_suffix(peers, "architect"),
            8.2,
            {"ventilation_direction": direction},
        )


class GeologistAgent(BaseAgent):
    name = "geologist"
    weight = 0.95

    def run(
        self,
        payload: AnalyzePlotRequest,
        environmental: dict,
        peers: list[AgentResult] | None = None,
    ) -> AgentResult:
        self.require_environment(environmental, ("elevation_m",))
        elevation = environmental["elevation_m"]
        decision, reasoning = geologist_foundation_guidance(elevation)
        return self.result(
            decision,
            reasoning + collaboration_suffix(peers, "architect", "meteorologist"),
            8.0,
            {"foundation": decision, "elevation_m": elevation},
        )


class StructuralEngineerAgent(BaseAgent):
    name = "structural_engineer"
    weight = 1.0

    def run(
        self,
        payload: AnalyzePlotRequest,
        environmental: dict,
        peers: list[AgentResult] | None = None,
    ) -> AgentResult:
        self.require_environment(environmental, ("wind", "rainfall_mm", "elevation_m"))
        from src.agents.structural import calculate_structural_decision

        structural = calculate_structural_decision(environmental)
        foundation = peer_by_name(peers, "geologist")
        reasoning = structural.reasoning + collaboration_suffix(peers, "geologist", "architect")
        if foundation is not None:
            reasoning += " Foundation type stays with the geologist recommendation."

        return self.result(
            f"Load-bearing walls set to {structural.wall_thickness_mm}mm for regional resilience",
            reasoning,
            structural.score,
            {"wall_thickness_mm": structural.wall_thickness_mm},
        )


class SiteEngineerAgent(BaseAgent):
    name = "site_engineer"
    weight = 0.85

    def run(
        self,
        payload: AnalyzePlotRequest,
        environmental: dict,
        peers: list[AgentResult] | None = None,
    ) -> AgentResult:
        road_edge = normalize_road_facing(payload.plot.road_facing)
        access_plan = calculate_site_access_decision(payload.plot.road_facing)
        return self.result(
            access_plan,
            "Supports practical site access and safe material movement"
            + collaboration_suffix(peers, "architect", "geologist"),
            7.8,
            {"road_edge": road_edge, "gate": access_plan},
        )


class VastuExpertAgent(BaseAgent):
    name = "vastu_expert"
    weight = 0.7

    def run(
        self,
        payload: AnalyzePlotRequest,
        environmental: dict,
        peers: list[AgentResult] | None = None,
    ) -> AgentResult:
        if not payload.requirements.apply_vastu:
            return self.result(
                "Vastu optional adjustments skipped",
                "User disabled vastu preferences",
                0.0,
                {"applied": False},
            )
        rules = load_vastu_rules()
        kitchen_rule = rules.get("kitchen", "Prefer south-east placement")
        architect = peer_by_name(peers, "architect")
        living = None
        science_weight = 1.0
        if architect is not None:
            science_weight = architect.weight
            living = str((architect.details or {}).get("living_exposure") or "").strip().lower() or None
        kitchen_zone, kitchen_yielded = resolve_exclusive_zone(
            "south-east",
            living,
            science_weight,
            self.weight,
            ("north-west", "south", "north", "east", "west"),
        )
        master_zone, master_yielded = resolve_master_zone(living, science_weight, self.weight)
        site = peer_by_name(peers, "site_engineer")
        road_edge = None
        site_weight = 0.0
        if site is not None:
            site_weight = site.weight
            road_edge = str((site.details or {}).get("road_edge") or "").strip().lower() or None
        entrance_zone, entrance_yielded = resolve_entrance("east", road_edge, site_weight, self.weight)
        if kitchen_zone == "south-east":
            decision = "Kitchen placed in south-east zone"
        else:
            decision = f"Kitchen placed in {kitchen_zone} zone"
        reasoning = f"Follows tradition-based adjustments where practical ({kitchen_rule})"
        notes: list[str] = []
        if architect is not None and living:
            if kitchen_yielded:
                notes.append(
                    f"Collaboration review yielded the {living} zone to the architect because "
                    f"science weight {science_weight} outranks tradition weight {self.weight}"
                )
            else:
                notes.append(
                    f"Collaboration review kept the kitchen compatible with the architect's {living} living exposure"
                )
        if master_yielded and living:
            notes.append(
                f"Master bedroom moved to {master_zone} so the {living} daylight facade stays with the architect"
            )
        if entrance_yielded and road_edge:
            notes.append(
                f"Entrance follows the site engineer road edge {entrance_zone} because site weight "
                f"{site_weight} outranks tradition weight {self.weight}"
            )
        if notes:
            reasoning = reasoning + ". " + ". ".join(notes)
        return self.result(
            decision,
            reasoning,
            7.6,
            {
                "applied": True,
                "kitchen_zone": kitchen_zone,
                "master_zone": master_zone,
                "entrance_zone": entrance_zone,
                "yielded_to_science": kitchen_yielded or master_yielded or entrance_yielded,
            },
        )


class InteriorDesignerAgent(BaseAgent):
    name = "interior_designer"
    weight = 0.75

    def run(
        self,
        payload: AnalyzePlotRequest,
        environmental: dict,
        peers: list[AgentResult] | None = None,
    ) -> AgentResult:
        bedrooms = payload.requirements.bedrooms
        bathrooms = payload.requirements.bathrooms
        return self.result(
            f"Circulation spine optimized for {bedrooms}BR/{bathrooms}BA with comfort zoning",
            "Reduces travel distance across common spaces and improves day-to-day comfort"
            + collaboration_suffix(peers, "architect", "vastu_expert", "site_engineer"),
            8.1,
            {"bedrooms": bedrooms, "bathrooms": bathrooms, "style": payload.requirements.style},
        )


class ConstructionBuilderAgent(BaseAgent):
    name = "construction_builder"
    weight = 0.9

    def run(
        self,
        payload: AnalyzePlotRequest,
        environmental: dict,
        peers: list[AgentResult] | None = None,
    ) -> AgentResult:
        self.require_environment(environmental, ("rainfall_mm", "weather"))
        decision, reasoning, score = generate_construction_builder_output(payload, environmental)
        structural = peer_by_name(peers, "structural_engineer")
        thickness = None
        if structural is not None:
            thickness = (structural.details or {}).get("wall_thickness_mm")
        note = collaboration_suffix(peers, "structural_engineer", "geologist", "meteorologist")
        if thickness:
            note += f" Walls coordinated at {thickness}mm."
        return self.result(
            decision,
            reasoning + note,
            score,
            {"wall_thickness_mm": thickness} if thickness else {},
        )


class GraphExecutionError(RuntimeError):
    """Raised when the LangGraph design workflow fails to execute."""


class OrchestratorAgent:
    """Coordinates specialized agents via a LangGraph StateGraph workflow."""

    def execute(self, payload: AnalyzePlotRequest, environmental: dict) -> list[DesignDecision]:
        initial_state = {
            "payload": payload,
            "environmental": environmental,
            "agent_results": [],
            "decisions": [],
        }
        try:
            final_state = design_graph.invoke(initial_state)
        except Exception as exc:
            logger.exception("LangGraph design workflow execution failed")
            raise GraphExecutionError(f"Design workflow failed to execute: {exc}") from exc
        return final_state["decisions"]
