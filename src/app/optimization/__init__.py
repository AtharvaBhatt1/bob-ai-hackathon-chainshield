"""
src/app/optimization
====================
ChainShield Route Feasibility / Optimization Engine package.

Public surface:
    find_feasible_routes    — main entry point
    CarrierSpec             — lightweight carrier/asset spec
    FeasibilityReport       — top-level result container
    RouteAlternativeResult  — per-alternative result
    carrier_spec_from_asset — factory helper
    OptimizationEngineUnavailable — raised when ortools is absent
"""
from src.app.optimization.engine import (
    CarrierSpec,
    FeasibilityReport,
    OptimizationEngineUnavailable,
    RouteAlternativeResult,
    carrier_spec_from_asset,
    find_feasible_routes,
)

__all__ = [
    "CarrierSpec",
    "FeasibilityReport",
    "OptimizationEngineUnavailable",
    "RouteAlternativeResult",
    "carrier_spec_from_asset",
    "find_feasible_routes",
]
