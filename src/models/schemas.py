"""Pydantic models for request/response contracts."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import Enum
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class JobStatus(str, Enum):
    pending = "pending"
    running = "running"
    completed = "completed"
    failed = "failed"


class Coordinates(BaseModel):
    lat: float
    lon: float


class LocationInput(BaseModel):
    address: str
    coordinates: Coordinates


class PlotDimensions(BaseModel):
    length: float = Field(gt=0)
    width: float = Field(gt=0)
    unit: str = "feet"


class PlotInput(BaseModel):
    dimensions: PlotDimensions
    orientation: str
    road_facing: str


class RequirementInput(BaseModel):
    bedrooms: int = Field(ge=1)
    bathrooms: int = Field(ge=1)
    kitchen: int = Field(ge=1)
    living_room: int = Field(ge=1)
    dining_room: int = Field(ge=1)
    budget: str
    style: str
    apply_vastu: bool = True


class AnalyzePlotRequest(BaseModel):
    location: LocationInput
    plot: PlotInput
    requirements: RequirementInput


class DesignDecision(BaseModel):
    agent: str
    decision: str
    reasoning: str
    score: float
    details: dict[str, Any] = Field(default_factory=dict)


class ValidationReport(BaseModel):
    sunlight_score: float
    ventilation_score: float
    structural_score: float
    energy_efficiency: str
    compliant: bool
    issues: list[str] = Field(default_factory=list)


class DesignResult(BaseModel):
    design_id: UUID = Field(default_factory=uuid4)
    files: dict[str, str]
    summary: dict[str, Any]
    design_decisions: list[DesignDecision]
    validation: ValidationReport


class JobRecord(BaseModel):
    job_id: UUID = Field(default_factory=uuid4)
    status: JobStatus = JobStatus.pending
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    request: AnalyzePlotRequest
    result: DesignResult | None = None
    error: str | None = None


class RegenerateRequest(BaseModel):
    requirements: RequirementInput
