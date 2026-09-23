"""LangGraph workflow where specialists review each other during the run."""

from __future__ import annotations

import logging
from typing import Annotated, NotRequired, TypedDict

from langgraph.graph import END, StateGraph
from langgraph.graph.state import CompiledStateGraph

from src.models.schemas import AnalyzePlotRequest, DesignDecision

logger = logging.getLogger(__name__)

ELEVATION_LOW_THRESHOLD = 150.0
ELEVATION_MID_THRESHOLD = 600.0

# Review pass walks dependencies so later specialists see revised peers.
REVIEW_ORDER = (
    "meteorologist",
    "geologist",
    "site_engineer",
    "architect",
    "vastu_expert",
    "structural_engineer",
    "interior_designer",
    "construction_builder",
)


def geologist_foundation_guidance(elevation: float) -> tuple[str, str]:
    if elevation < ELEVATION_LOW_THRESHOLD:
        return (
            f"Raised plinth foundation for low elevation site ({elevation}m)",
            "Low-lying terrain needs moisture and settlement safeguards",
        )
    if elevation < ELEVATION_MID_THRESHOLD:
        return (
            f"Reinforced strip footing for mid-elevation site ({elevation}m)",
            "Balanced soil pressure and drainage profile support standard reinforcement",
        )
    return (
        f"Stepped reinforced foundation for high elevation site ({elevation}m)",
        "Steeper terrain needs terrace-adaptive foundation stability",
    )


class AgentResultState(TypedDict, total=False):
    name: str
    decision: str
    reasoning: str
    score: float
    weight: float
    details: dict


def _append_result(existing: list[AgentResultState] | None, new: list[AgentResultState]) -> list[AgentResultState]:
    """Reducer that appends new agent results to the accumulated list."""
    return list(existing or []) + list(new or [])


def _merge_brief(existing: dict | None, new: dict | None) -> dict:
    merged = dict(existing or {})
    merged.update(new or {})
    return merged


class DesignGraphState(TypedDict):
    """Shared state passed through every node of the design workflow graph."""

    payload: AnalyzePlotRequest
    environmental: dict
    agent_results: Annotated[list[AgentResultState], _append_result]
    decisions: list[DesignDecision]
    design_brief: NotRequired[Annotated[dict, _merge_brief]]


_AGENTS: dict | None = None


def _agents() -> dict:
    """Lazy import avoids a cycle between this module and the agent classes."""
    global _AGENTS
    if _AGENTS is None:
        from src.agents.orchestrator import (
            ArchitectAgent,
            ConstructionBuilderAgent,
            GeologistAgent,
            InteriorDesignerAgent,
            MeteorologistAgent,
            SiteEngineerAgent,
            StructuralEngineerAgent,
            VastuExpertAgent,
        )

        _AGENTS = {
            "architect": ArchitectAgent(),
            "meteorologist": MeteorologistAgent(),
            "geologist": GeologistAgent(),
            "structural_engineer": StructuralEngineerAgent(),
            "site_engineer": SiteEngineerAgent(),
            "vastu_expert": VastuExpertAgent(),
            "interior_designer": InteriorDesignerAgent(),
            "construction_builder": ConstructionBuilderAgent(),
        }
    return _AGENTS


def _to_agent_result(raw: AgentResultState):
    from src.agents.orchestrator import AgentResult

    return AgentResult(
        name=raw["name"],
        decision=raw["decision"],
        reasoning=raw["reasoning"],
        score=raw["score"],
        weight=raw["weight"],
        details=dict(raw.get("details") or {}),
    )


def _dump_result(result) -> AgentResultState:
    return {
        "name": result.name,
        "decision": result.decision,
        "reasoning": result.reasoning,
        "score": result.score,
        "weight": result.weight,
        "details": dict(result.details or {}),
    }


def _latest_results(state: DesignGraphState) -> dict[str, AgentResultState]:
    latest: dict[str, AgentResultState] = {}
    for raw in state.get("agent_results") or []:
        latest[raw["name"]] = raw
    return latest


def _run_specialist(name: str, state: DesignGraphState) -> dict:
    peers = [_to_agent_result(raw) for raw in _latest_results(state).values()]
    result = _agents()[name].run(state["payload"], state["environmental"], peers)
    dumped = _dump_result(result)
    logger.info("Specialist %s proposed during the design run", name)
    return {"agent_results": [dumped], "design_brief": dict(dumped.get("details") or {})}


def architect_node(state: DesignGraphState) -> dict:
    return _run_specialist("architect", state)


def meteorologist_node(state: DesignGraphState) -> dict:
    return _run_specialist("meteorologist", state)


def geologist_node(state: DesignGraphState) -> dict:
    return _run_specialist("geologist", state)


def structural_engineer_node(state: DesignGraphState) -> dict:
    return _run_specialist("structural_engineer", state)


def site_engineer_node(state: DesignGraphState) -> dict:
    return _run_specialist("site_engineer", state)


def vastu_expert_node(state: DesignGraphState) -> dict:
    return _run_specialist("vastu_expert", state)


def interior_designer_node(state: DesignGraphState) -> dict:
    return _run_specialist("interior_designer", state)


def construction_builder_node(state: DesignGraphState) -> dict:
    return _run_specialist("construction_builder", state)


def collaborate_node(state: DesignGraphState) -> dict:
    """Second pass: each specialist revises with the full peer set in view."""
    latest = _latest_results(state)
    brief = dict(state.get("design_brief") or {})
    revisions: list[AgentResultState] = []
    payload = state["payload"]
    environmental = state["environmental"]
    agents = _agents()

    for name in REVIEW_ORDER:
        if name not in latest:
            continue
        others = [
            _to_agent_result(latest[peer_name])
            for peer_name in REVIEW_ORDER
            if peer_name != name and peer_name in latest
        ]
        revised = agents[name].revise(payload, environmental, others, brief)
        if revised is None:
            continue
        dumped = _dump_result(revised)
        latest[name] = dumped
        revisions.append(dumped)
        brief.update(dumped.get("details") or {})

    logger.info("Collaboration review updated %s specialist positions", len(revisions))
    return {"agent_results": revisions, "design_brief": brief}


def compile_decisions_node(state: DesignGraphState) -> dict:
    """Keep the latest position from each specialist and rank by weighted score."""
    latest = _latest_results(state)
    ordered = sorted(
        latest.values(),
        key=lambda result: result["score"] * result["weight"],
        reverse=True,
    )
    decisions = [
        DesignDecision(
            agent=result["name"],
            decision=result["decision"],
            reasoning=result["reasoning"],
            score=round(result["score"] * result["weight"], 2),
            details=dict(result.get("details") or {}),
        )
        for result in ordered
    ]
    return {"decisions": decisions}


def build_design_graph() -> CompiledStateGraph:
    """Construct and compile the LangGraph design workflow."""
    workflow = StateGraph(DesignGraphState)

    workflow.add_node("architect", architect_node)
    workflow.add_node("meteorologist", meteorologist_node)
    workflow.add_node("geologist", geologist_node)
    workflow.add_node("structural_engineer", structural_engineer_node)
    workflow.add_node("site_engineer", site_engineer_node)
    workflow.add_node("vastu_expert", vastu_expert_node)
    workflow.add_node("interior_designer", interior_designer_node)
    workflow.add_node("construction_builder", construction_builder_node)
    workflow.add_node("collaborate", collaborate_node)
    workflow.add_node("compile_decisions", compile_decisions_node)

    # Forward pass proposes; collaborate revises with every peer visible; then rank.
    workflow.set_entry_point("architect")
    workflow.add_edge("architect", "meteorologist")
    workflow.add_edge("meteorologist", "geologist")
    workflow.add_edge("geologist", "structural_engineer")
    workflow.add_edge("structural_engineer", "site_engineer")
    workflow.add_edge("site_engineer", "vastu_expert")
    workflow.add_edge("vastu_expert", "interior_designer")
    workflow.add_edge("interior_designer", "construction_builder")
    workflow.add_edge("construction_builder", "collaborate")
    workflow.add_edge("collaborate", "compile_decisions")
    workflow.add_edge("compile_decisions", END)

    return workflow.compile()


try:
    design_graph: CompiledStateGraph = build_design_graph()
except Exception as exc:  # pragma: no cover - defensive initialization guard
    raise RuntimeError("Failed to build design graph during module import") from exc
