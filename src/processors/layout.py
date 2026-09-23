"""Deterministic residential room layout driven by the collaborative design brief."""

from __future__ import annotations

from dataclasses import dataclass, replace

from src.models.schemas import AnalyzePlotRequest, DesignDecision
from src.utils.knowledge import load_ibc_minimums


@dataclass(frozen=True)
class Opening:
    kind: str
    wall: str
    offset: float
    width: float


@dataclass(frozen=True)
class Room:
    name: str
    x: float
    y: float
    width: float
    depth: float
    zone: str
    openings: tuple[Opening, ...] = ()

    @property
    def area(self) -> float:
        return round(self.width * self.depth, 2)


def _split_evenly(count: int, start: float, span: float, gap: float) -> list[tuple[float, float]]:
    usable = span - gap * max(count - 1, 0)
    each = usable / count
    boxes: list[tuple[float, float]] = []
    cursor = start
    for _ in range(count):
        boxes.append((cursor, each))
        cursor += each + gap
    return boxes


def _legacy_layout(request: AnalyzePlotRequest) -> list[Room]:
    """Pack rooms on a north-up plan with living along the south edge."""
    plot_w = request.plot.dimensions.width
    plot_d = request.plot.dimensions.length
    reqs = request.requirements
    gap = 1.0
    south_band = plot_d * 0.42
    north_band = plot_d - south_band - gap

    kitchen_w = min(14.0, plot_w * 0.28)
    living_w = plot_w - kitchen_w - gap
    dining_d = min(12.0, south_band * 0.38)
    living_d = south_band - dining_d - gap

    rooms = [
        Room("living_room", 0.0, 0.0, living_w, living_d, "south"),
        Room("dining_room", 0.0, living_d + gap, living_w, dining_d, "south"),
        Room("kitchen", living_w + gap, 0.0, kitchen_w, south_band, "south-east"),
    ]

    bath_d = min(8.0, north_band * 0.28)
    bedroom_d = north_band - bath_d - gap
    bedroom_y = south_band + gap
    bath_y = bedroom_y + bedroom_d + gap

    bedroom_boxes = _split_evenly(reqs.bedrooms, 0.0, plot_w, gap)
    for index, (x, width) in enumerate(bedroom_boxes):
        name = "master_bedroom" if index == 0 else f"bedroom_{index + 1}"
        zone = "south-west" if index == 0 else "north"
        rooms.append(Room(name, x, bedroom_y, width, bedroom_d, zone))

    bath_boxes = _split_evenly(reqs.bathrooms, 0.0, plot_w, gap)
    for index, (x, width) in enumerate(bath_boxes):
        rooms.append(Room(f"bathroom_{index + 1}", x, bath_y, width, bath_d, "north"))
    return rooms


def _brief_from_decisions(decisions: list[DesignDecision] | None) -> dict:
    brief: dict = {}
    if not decisions:
        return brief
    for decision in decisions:
        details = getattr(decision, "details", None) or {}
        if isinstance(details, dict):
            brief.update(details)
    return brief


def _primary_cardinal(value: str) -> str:
    text = str(value or "south").strip().lower()
    for name in ("south", "north", "east", "west"):
        if text == name or text.startswith(name):
            return name
    return "south"


def _swapped_request(request: AnalyzePlotRequest) -> AnalyzePlotRequest:
    dims = request.plot.dimensions
    return request.model_copy(
        update={
            "plot": request.plot.model_copy(
                update={"dimensions": dims.model_copy(update={"length": dims.width, "width": dims.length})}
            )
        }
    )


def _map_geometry(x: float, y: float, width: float, depth: float, plot_w: float, plot_d: float, side: str):
    if side == "north":
        return x, plot_d - (y + depth), width, depth
    if side == "west":
        return y, x, depth, width
    if side == "east":
        return plot_w - (y + depth), x, depth, width
    return x, y, width, depth


def _orient_rooms(rooms: list[Room], plot_w: float, plot_d: float, side: str) -> list[Room]:
    oriented: list[Room] = []
    for room in rooms:
        x, y, width, depth = _map_geometry(room.x, room.y, room.width, room.depth, plot_w, plot_d, side)
        oriented.append(replace(room, x=x, y=y, width=width, depth=depth))
    return oriented


def _zone_target(zone: str, plot_w: float, plot_d: float) -> tuple[float, float]:
    text = zone.strip().lower()
    x = plot_w if "east" in text else 0.0 if "west" in text else plot_w / 2
    y = plot_d if "north" in text else 0.0 if "south" in text else plot_d / 2
    return x, y


def _distance_to_zone(room: Room, zone: str, plot_w: float, plot_d: float) -> float:
    target_x, target_y = _zone_target(zone, plot_w, plot_d)
    center_x = room.x + room.width / 2
    center_y = room.y + room.depth / 2
    return (center_x - target_x) ** 2 + (center_y - target_y) ** 2


def _swap_geometry(rooms: list[Room], left_name: str, right: Room) -> list[Room]:
    swapped: list[Room] = []
    left = next(room for room in rooms if room.name == left_name)
    for room in rooms:
        if room.name == left.name:
            swapped.append(replace(room, x=right.x, y=right.y, width=right.width, depth=right.depth))
        elif room.name == right.name:
            swapped.append(replace(room, x=left.x, y=left.y, width=left.width, depth=left.depth))
        else:
            swapped.append(room)
    return swapped


def _move_room_toward_zone(rooms: list[Room], name: str, zone: str, plot_w: float, plot_d: float) -> list[Room]:
    subject = next((room for room in rooms if room.name == name), None)
    if subject is None:
        return rooms
    closest = min(rooms, key=lambda room: _distance_to_zone(room, zone, plot_w, plot_d))
    if closest.name == subject.name:
        return rooms
    return _swap_geometry(rooms, subject.name, closest)


def _rename_master(rooms: list[Room], master_zone: str, plot_w: float, plot_d: float) -> list[Room]:
    bedrooms = [room for room in rooms if "bedroom" in room.name]
    if not bedrooms:
        return rooms
    chosen = min(bedrooms, key=lambda room: _distance_to_zone(room, master_zone, plot_w, plot_d))
    if chosen.name == "master_bedroom":
        return rooms
    renamed: list[Room] = []
    for room in rooms:
        if room.name == chosen.name:
            renamed.append(replace(room, name="master_bedroom"))
        elif room.name == "master_bedroom":
            renamed.append(replace(room, name=chosen.name))
        else:
            renamed.append(room)
    return renamed


def geometric_zone(room: Room, plot_w: float, plot_d: float) -> str:
    touches_south = room.y <= 0.05
    touches_north = abs((room.y + room.depth) - plot_d) <= 0.05
    touches_west = room.x <= 0.05
    touches_east = abs((room.x + room.width) - plot_w) <= 0.05
    wide = room.width >= plot_w * 0.5
    tall = room.depth >= plot_d * 0.5
    north_south = "south" if touches_south and not touches_north else "north" if touches_north and not touches_south else ""
    east_west = "west" if touches_west and not touches_east else "east" if touches_east and not touches_west else ""
    if wide and north_south:
        return north_south
    if tall and east_west:
        return east_west
    if north_south and east_west:
        return f"{north_south}-{east_west}"
    return north_south or east_west or "center"


def _exterior_walls(room: Room, plot_w: float, plot_d: float) -> set[str]:
    walls: set[str] = set()
    if room.y <= 0.05:
        walls.add("south")
    if abs((room.y + room.depth) - plot_d) <= 0.05:
        walls.add("north")
    if room.x <= 0.05:
        walls.add("west")
    if abs((room.x + room.width) - plot_w) <= 0.05:
        walls.add("east")
    return walls


def _wall_length(room: Room, wall: str) -> float:
    if wall in {"north", "south"}:
        return room.width
    return room.depth


def _wind_walls(direction: str | None) -> set[str]:
    text = str(direction or "SW").strip().upper()
    return {
        "N": {"north"},
        "S": {"south"},
        "E": {"east"},
        "W": {"west"},
        "NE": {"north", "east"},
        "NW": {"north", "west"},
        "SE": {"south", "east"},
        "SW": {"south", "west"},
    }.get(text, {"south", "west"})


def _with_openings(rooms: list[Room], plot_w: float, plot_d: float, brief: dict) -> list[Room]:
    ibc = load_ibc_minimums()
    door_width = max(float(ibc.get("egress_door_width_in", 32)) / 12.0, 2.5)
    living_side = _primary_cardinal(str(brief.get("living_exposure") or "south"))
    windy = _wind_walls(brief.get("ventilation_direction"))
    road = str(brief.get("road_edge") or "east").strip().lower()
    road_cardinal = _primary_cardinal(road)

    entrance_host = None
    entrance_span = -1.0
    for room in rooms:
        if "bath" in room.name:
            continue
        walls = _exterior_walls(room, plot_w, plot_d)
        if road_cardinal not in walls and road not in walls:
            continue
        span = _wall_length(room, road_cardinal if road_cardinal in walls else next(iter(walls)))
        if span > entrance_span:
            entrance_host = room.name
            entrance_span = span

    opened: list[Room] = []
    for room in rooms:
        walls = _exterior_walls(room, plot_w, plot_d)
        openings: list[Opening] = []
        for wall in sorted(walls):
            length = _wall_length(room, wall)
            if length < 3:
                continue
            wants_window = wall in windy or (room.name == "living_room" and wall == living_side)
            wants_door = room.name == entrance_host and (wall == road_cardinal or wall == road)
            cursor = length * 0.15
            if wants_door:
                width = min(door_width, length * 0.45)
                openings.append(Opening("door", wall, cursor, width))
                cursor += width + length * 0.1
            if wants_window and cursor + 2 < length:
                width = min(4.0, length * 0.35, length - cursor - length * 0.1)
                if width >= 2:
                    openings.append(Opening("window", wall, cursor, width))
        opened.append(replace(room, openings=tuple(openings), zone=geometric_zone(room, plot_w, plot_d)))
    return opened


def build_room_layout(
    request: AnalyzePlotRequest,
    decisions: list[DesignDecision] | None = None,
) -> list[Room]:
    """Place rooms from the brief specialists agreed during the graph run."""
    brief = _brief_from_decisions(decisions)
    living = _primary_cardinal(str(brief.get("living_exposure") or "south"))
    kitchen_zone = str(brief.get("kitchen_zone") or "south-east")
    master_zone = str(brief.get("master_zone") or "south-west")

    plot_w = request.plot.dimensions.width
    plot_d = request.plot.dimensions.length
    source = _swapped_request(request) if living in {"east", "west"} else request
    rooms = _orient_rooms(_legacy_layout(source), plot_w, plot_d, living)
    rooms = _move_room_toward_zone(rooms, "kitchen", kitchen_zone, plot_w, plot_d)
    rooms = _rename_master(rooms, master_zone, plot_w, plot_d)
    return _with_openings(rooms, plot_w, plot_d, brief)
