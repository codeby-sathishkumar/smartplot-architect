"""Peer review helpers used while the design graph is running.

Specialists read each other's decisions in-process. When a lower-weight
tradition claim and a higher-weight scientific claim want the same zone,
tradition yields. That resolution happens inside the graph run, before the
floor plan is drawn.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol


class _Peer(Protocol):
    name: str
    decision: str
    weight: float
    details: dict


def peer_by_name(peers: Sequence[_Peer] | None, name: str) -> _Peer | None:
    if not peers:
        return None
    for peer in reversed(list(peers)):
        if peer.name == name:
            return peer
    return None


def collaboration_suffix(peers: Sequence[_Peer] | None, *names: str) -> str:
    """Short note listing peers this specialist actually reviewed."""
    if not peers:
        return ""
    reviewed = [name for name in names if peer_by_name(peers, name) is not None]
    if not reviewed:
        return ""
    return ". Collaboration review considered " + ", ".join(reviewed) + " during this run."


def resolve_exclusive_zone(
    tradition_zone: str,
    science_zone: str | None,
    science_weight: float,
    tradition_weight: float,
    fallbacks: tuple[str, ...],
) -> tuple[str, bool]:
    """Yield a tradition zone when a heavier science claim wants that exact zone."""
    if not science_zone or science_weight <= tradition_weight:
        return tradition_zone, False
    if science_zone.strip().lower() != tradition_zone.strip().lower():
        return tradition_zone, False
    blocked = science_zone.strip().lower()
    for candidate in fallbacks:
        if candidate.strip().lower() != blocked:
            return candidate, True
    return fallbacks[-1], True


def living_claims_private_corner(living_exposure: str, corner: str) -> bool:
    """A sleeping corner conflicts when it sits on the architect's daylight facade."""
    living = living_exposure.strip().lower()
    parts = [part for part in corner.strip().lower().split("-") if part]
    if not parts:
        return False
    if len(parts) == 1:
        return living == parts[0]
    return living in parts


def resolve_master_zone(
    living_exposure: str | None,
    science_weight: float,
    tradition_weight: float,
) -> tuple[str, bool]:
    preferred = "south-west"
    if not living_exposure or science_weight <= tradition_weight:
        return preferred, False
    if not living_claims_private_corner(living_exposure, preferred):
        return preferred, False
    for candidate in ("north-west", "north-east", "north"):
        if not living_claims_private_corner(living_exposure, candidate):
            return candidate, True
    return "north", True


def resolve_entrance(
    tradition_edge: str,
    road_edge: str | None,
    site_weight: float,
    tradition_weight: float,
) -> tuple[str, bool]:
    """Site access outranks a traditional entrance edge when they disagree."""
    preferred = tradition_edge.strip().lower()
    if not road_edge or site_weight <= tradition_weight:
        return preferred, False
    road = road_edge.strip().lower()
    road_parts = set(road.split("-"))
    if road == preferred or preferred in road_parts:
        return preferred, False
    return road, True
