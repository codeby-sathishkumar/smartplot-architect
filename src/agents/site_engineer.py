"""Shared site engineering decision helpers."""

from __future__ import annotations


def normalize_road_facing(road_facing: str) -> str:
    return road_facing.strip().lower()


def calculate_site_access_decision(road_facing: str) -> str:
    normalized = normalize_road_facing(road_facing)
    return {
        "north": "Main construction gate on north edge with east-side unloading pocket",
        "south": "Main construction gate on south edge with west-side unloading pocket",
        "east": "Main construction gate on east edge with north-side unloading pocket",
        "west": "Main construction gate on west edge with south-side unloading pocket",
    }.get(normalized, f"Main construction gate aligned to {normalized} road edge")
