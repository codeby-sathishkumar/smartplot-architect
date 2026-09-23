"""Agents must review one another while the design graph is running."""

from __future__ import annotations

import unittest

from src.agents.graph import DesignGraphState, design_graph
from src.agents.orchestrator import ArchitectAgent, OrchestratorAgent, VastuExpertAgent
from src.models.schemas import AnalyzePlotRequest, DesignDecision
from src.processors.layout import build_room_layout
from src.services.environmental import EnvironmentalService


def _sample_request() -> AnalyzePlotRequest:
    return AnalyzePlotRequest.model_validate(
        {
            "location": {"address": "Bangalore", "coordinates": {"lat": 12.9716, "lon": 77.5946}},
            "plot": {
                "dimensions": {"length": 30, "width": 50, "unit": "feet"},
                "orientation": "north",
                "road_facing": "east",
            },
            "requirements": {
                "bedrooms": 3,
                "bathrooms": 2,
                "kitchen": 1,
                "living_room": 1,
                "dining_room": 1,
                "budget": "mid-range",
                "style": "modern",
                "apply_vastu": True,
            },
        }
    )


def _overlaps(left, right) -> bool:
    gap = 0.05
    separated = (
        left.x + left.width <= right.x + gap
        or right.x + right.width <= left.x + gap
        or left.y + left.depth <= right.y + gap
        or right.y + right.depth <= left.y + gap
    )
    return not separated


class CollaborationTests(unittest.TestCase):
    def test_graph_review_pass_records_peer_review_on_architect(self) -> None:
        request = _sample_request()
        environmental = EnvironmentalService().fetch_environmental_profile(request.location)
        initial: DesignGraphState = {
            "payload": request,
            "environmental": environmental,
            "agent_results": [],
            "decisions": [],
        }
        final = design_graph.invoke(initial)
        self.assertEqual(len(final["decisions"]), 8)
        architect = next(decision for decision in final["decisions"] if decision.agent == "architect")
        self.assertIn("south", architect.decision.lower())
        self.assertIn("collaboration review", architect.reasoning.lower())
        self.assertEqual(architect.details["living_exposure"], "south")
        structural = next(decision for decision in final["decisions"] if decision.agent == "structural_engineer")
        self.assertIn("wall_thickness_mm", structural.details)
        construction = next(decision for decision in final["decisions"] if decision.agent == "construction_builder")
        self.assertIn(str(structural.details["wall_thickness_mm"]), construction.reasoning)

    def test_vastu_yields_when_architect_claims_the_same_zone(self) -> None:
        architect = ArchitectAgent().run(
            _sample_request(),
            {"solar": {"preferred_exposure": "south-east"}},
        )
        result = VastuExpertAgent().run(_sample_request(), {}, [architect])
        self.assertNotIn("south-east", result.decision.lower())
        self.assertTrue(result.details["yielded_to_science"])
        self.assertIn("outranks tradition", result.reasoning.lower())
        self.assertIn("tradition-based", result.reasoning.lower())

    def test_vastu_keeps_south_east_kitchen_when_living_is_south(self) -> None:
        architect = ArchitectAgent().run(
            _sample_request(),
            {"solar": {"preferred_exposure": "south"}},
        )
        result = VastuExpertAgent().run(_sample_request(), {}, [architect])
        self.assertIn("south-east", result.decision.lower())
        self.assertEqual(result.details["kitchen_zone"], "south-east")
        self.assertEqual(result.details["master_zone"], "north-west")

    def test_layout_follows_collaborative_brief_without_overlaps(self) -> None:
        request = _sample_request()
        decisions = OrchestratorAgent().execute(
            request,
            EnvironmentalService().fetch_environmental_profile(request.location),
        )
        rooms = build_room_layout(request, decisions)
        plot_w = request.plot.dimensions.width
        plot_d = request.plot.dimensions.length
        self.assertGreaterEqual(len(rooms), 8)
        for room in rooms:
            self.assertGreaterEqual(room.x, -0.01)
            self.assertGreaterEqual(room.y, -0.01)
            self.assertLessEqual(room.x + room.width, plot_w + 0.01)
            self.assertLessEqual(room.y + room.depth, plot_d + 0.01)
            self.assertGreaterEqual(room.area, 70)
        for index, left in enumerate(rooms):
            for right in rooms[index + 1 :]:
                self.assertFalse(_overlaps(left, right), f"{left.name} overlaps {right.name}")
        living = next(room for room in rooms if room.name == "living_room")
        self.assertLess(living.y + living.depth / 2, plot_d / 2)
        self.assertTrue(any(opening.kind == "window" for room in rooms for opening in room.openings))
        self.assertTrue(any(opening.kind == "door" for room in rooms for opening in room.openings))

    def test_layout_turns_living_toward_requested_exposure(self) -> None:
        request = _sample_request()
        north_facing = [
            DesignDecision(
                agent="architect",
                decision="Primary living spaces aligned to north",
                reasoning="Optimized for natural daylight",
                score=8.5,
                details={"living_exposure": "north"},
            )
        ]
        rooms = build_room_layout(request, north_facing)
        living = next(room for room in rooms if room.name == "living_room")
        plot_d = request.plot.dimensions.length
        self.assertGreater(living.y + living.depth / 2, plot_d / 2)

        east_facing = [
            DesignDecision(
                agent="architect",
                decision="Primary living spaces aligned to east",
                reasoning="Optimized for natural daylight",
                score=8.5,
                details={"living_exposure": "east", "kitchen_zone": "south-east"},
            )
        ]
        eastern = build_room_layout(request, east_facing)
        living = next(room for room in eastern if room.name == "living_room")
        plot_w = request.plot.dimensions.width
        self.assertGreater(living.x + living.width / 2, plot_w / 2)
        for index, left in enumerate(eastern):
            self.assertLessEqual(left.x + left.width, plot_w + 0.01)
            self.assertLessEqual(left.y + left.depth, plot_d + 0.01)
            for right in eastern[index + 1 :]:
                self.assertFalse(_overlaps(left, right), f"{left.name} overlaps {right.name}")


if __name__ == "__main__":
    unittest.main()
