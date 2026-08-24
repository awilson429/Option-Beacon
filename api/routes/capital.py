from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query

from api.dependencies import get_service
from api.schemas.capital import (
    CapitalComparison, CapitalDecisionResponse, CapitalLaneState,
    CapitalOverview, RiskStatusResponse,
)

router = APIRouter(tags=["capital readiness"])


@router.get("/capital", response_model=CapitalOverview, summary="OB/BROAD simulated capital")
def capital(service=Depends(get_service)):
    return service.capital_overview()


@router.get("/capital/compare", response_model=CapitalComparison, summary="Normalized OB/BROAD comparison")
def compare(service=Depends(get_service)):
    return service.capital_compare()


@router.get("/capital/decisions/recent", response_model=list[CapitalDecisionResponse], summary="Recent capital decisions")
def decisions(limit: Annotated[int, Query(ge=1, le=200)] = 50, service=Depends(get_service)):
    return service.capital_decisions(limit)


@router.get("/risk/status", response_model=RiskStatusResponse, summary="Lane risk-control status")
def risk_status(service=Depends(get_service)):
    return service.risk_status()


@router.get("/capital/{lane}", response_model=CapitalLaneState, summary="One simulated lane account")
def lane(lane: str, service=Depends(get_service)):
    normalized = lane.upper()
    if normalized not in {"OB", "BROAD"}:
        raise HTTPException(status_code=404, detail="Unsupported capital lane")
    return service.capital_lane(normalized)
