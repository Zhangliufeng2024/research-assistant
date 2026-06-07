#!/usr/bin/env python3
"""
Grant Budget Calculator

Calculates budgets with inflation, fringe benefits, and F&A rates for
grant proposals across multiple agencies.

Usage:
    python budget_calculator.py --agency NSF --years 3 --pi-effort "2months"
    python budget_calculator.py --agency NIH --years 5 --personnel "PI:12months,Postdoc:12months,PhD:12months"
"""

import argparse
import json
import sys
# Fix Windows console encoding for emoji/non-ASCII characters
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from typing import Dict, List, Optional


# Default rates (these should be customized per institution)
DEFAULT_RATES = {
    "fringe_benefits": {
        "faculty": 0.28,
        "postdoc": 0.30,
        "graduate_student": 0.15,
        "undergraduate": 0.10,
        "staff": 0.35
    },
    "fa_rate": 0.55,  # F&A (indirect cost) rate
    "annual_inflation": 0.03,  # 3% annual salary increase
    "tuition": {
        "graduate": 20000,  # Annual tuition
        "postdoc_training": 0
    }
}

# Agency-specific rules
AGENCY_RULES = {
    "NSF": {
        "max_pi_summer_months": 2,
        "max_duration_years": 5,
        "requires_data_management": True,
        "requires_postdoc_mentoring": True,
        "cost_sharing_required": False,
        "modular_budget": False
    },
    "NIH": {
        "salary_cap": 221900,
        "modular_threshold": 250000,
        "modular_increment": 25000,
        "max_duration_years": 5,
        "requires_rigor": True,
        "cost_sharing_required": False
    },
    "DOE": {
        "max_duration_years": 5,
        "cost_sharing_may_apply": True,
        "requires_quad_chart": True,
        "quarterly_budgets": True
    },
    "DARPA": {
        "phased": True,
        "phase1_months": 18,
        "phase2_months": 24,
        "phase3_months": 12,
        "cost_sharing_required": False
    },
    "NSFC": {
        "currency": "RMB",
        "typical_general_program": 800000,
        "typical_young_scientists": 300000,
        "duration_years": 3
    },
    "DOT": {
        "max_duration_years": 3,
        "cost_sharing_may_apply": True,
        "requires_implementation_plan": True
    }
}


def calculate_personnel_cost(
    role: str,
    annual_salary: float,
    effort_months: float,
    years: int,
    fringe_rate: Optional[float] = None,
    salary_cap: Optional[float] = None,
    inflation_rate: float = 0.03
) -> Dict:
    """Calculate personnel cost over multiple years with inflation."""

    if fringe_rate is None:
        fringe_rate = DEFAULT_RATES["fringe_benefits"].get(role, 0.25)

    if salary_cap:
        annual_salary = min(annual_salary, salary_cap)

    yearly_costs = []
    total_cost = 0

    for year in range(years):
        inflated_salary = annual_salary * ((1 + inflation_rate) ** year)
        effort_fraction = effort_months / 12.0
        salary_cost = inflated_salary * effort_fraction
        fringe_cost = salary_cost * fringe_rate
        total_year_cost = salary_cost + fringe_cost

        yearly_costs.append({
            "year": year + 1,
            "salary": round(salary_cost, 2),
            "fringe": round(fringe_cost, 2),
            "total": round(total_year_cost, 2)
        })
        total_cost += total_year_cost

    return {
        "role": role,
        "effort_months": effort_months,
        "years": years,
        "yearly_costs": yearly_costs,
        "total_cost": round(total_cost, 2)
    }


def calculate_fa(direct_costs: float, fa_rate: float = 0.55, exclusions: float = 0) -> float:
    """Calculate F&A (indirect) costs."""
    mtdc = direct_costs - exclusions  # Modified Total Direct Costs
    return round(mtdc * fa_rate, 2)


def calculate_budget(
    agency: str,
    years: int,
    personnel: List[Dict],
    equipment: float = 0,
    travel: float = 0,
    supplies: float = 0,
    other: float = 0,
    tuition: float = 0
) -> Dict:
    """Calculate complete budget for a grant proposal."""

    rules = AGENCY_RULES.get(agency.upper(), {})
    rates = DEFAULT_RATES

    # Personnel costs
    personnel_details = []
    total_personnel = 0

    for p in personnel:
        role = p.get("role", "staff")
        salary = p.get("salary", 70000)
        effort = p.get("effort_months", 12)

        salary_cap = rules.get("salary_cap")
        fringe_rate = rates["fringe_benefits"].get(role, 0.25)

        cost = calculate_personnel_cost(
            role=role,
            annual_salary=salary,
            effort_months=effort,
            years=years,
            fringe_rate=fringe_rate,
            salary_cap=salary_cap,
            inflation_rate=rates["annual_inflation"]
        )
        personnel_details.append(cost)
        total_personnel += cost["total_cost"]

    # Annual costs
    annual_costs = []
    total_direct = 0
    total_equipment = equipment
    total_travel = travel * years
    total_supplies = supplies * years
    total_other = other * years
    total_tuition = tuition * years

    for year in range(years):
        year_personnel = sum(p["yearly_costs"][year]["total"] for p in personnel_details)
        year_direct = year_personnel + travel + supplies + other + tuition

        # Add equipment only in year 1 (typical)
        if year == 0:
            year_direct += equipment

        annual_costs.append({
            "year": year + 1,
            "personnel": round(year_personnel, 2),
            "equipment": equipment if year == 0 else 0,
            "travel": travel,
            "supplies": supplies,
            "other": other,
            "tuition": tuition,
            "total_direct": round(year_direct, 2)
        })
        total_direct += year_direct

    # F&A costs
    fa_exclusions = total_equipment + tuition  # Equipment and tuition typically excluded from MTDC
    total_fa = calculate_fa(total_direct, rates["fa_rate"], fa_exclusions)

    total_cost = total_direct + total_fa

    # Check modular budget limit for NIH
    modular_budget = False
    if agency.upper() == "NIH" and total_direct <= rules.get("modular_threshold", 250000):
        modular_budget = True
        # Round to nearest $25K
        modular_direct = round(total_direct / 25000) * 25000

    return {
        "agency": agency.upper(),
        "years": years,
        "personnel": personnel_details,
        "annual_costs": annual_costs,
        "summary": {
            "total_personnel": round(total_personnel, 2),
            "total_equipment": total_equipment,
            "total_travel": total_travel,
            "total_supplies": total_supplies,
            "total_other": total_other,
            "total_tuition": total_tuition,
            "total_direct": round(total_direct, 2),
            "total_fa": total_fa,
            "fa_rate": rates["fa_rate"],
            "total_cost": round(total_cost, 2)
        },
        "modular_budget": modular_budget,
        "rules_applied": rules
    }


def print_budget(budget: Dict):
    """Print budget summary in a readable format."""
    print(f"\n{'='*60}")
    print(f"Budget Summary: {budget['agency']}")
    print(f"Duration: {budget['years']} years")
    print(f"{'='*60}\n")

    # Personnel
    print("PERSONNEL:")
    for p in budget["personnel"]:
        print(f"  {p['role']}: {p['effort_months']} months/year x {p['years']} years = ${p['total_cost']:,.2f}")
    print(f"  {'-'*40}")
    print(f"  Total Personnel: ${budget['summary']['total_personnel']:,.2f}\n")

    # Annual costs
    print("ANNUAL COSTS:")
    for ac in budget["annual_costs"]:
        print(f"  Year {ac['year']}: Personnel ${ac['personnel']:,.2f} + "
              f"Equipment ${ac['equipment']:,.2f} + "
              f"Travel ${ac['travel']:,.2f} + "
              f"Supplies ${ac['supplies']:,.2f} + "
              f"Other ${ac['other']:,.2f} = ${ac['total_direct']:,.2f}")
    print()

    # Summary
    print("TOTALS:")
    print(f"  Total Direct Costs:  ${budget['summary']['total_direct']:,.2f}")
    print(f"  F&A ({budget['summary']['fa_rate']*100:.0f}%):            ${budget['summary']['total_fa']:,.2f}")
    print(f"  {'-'*40}")
    print(f"  TOTAL COST:          ${budget['summary']['total_cost']:,.2f}")

    if budget.get("modular_budget"):
        print(f"\n  NOTE: NIH modular budget applies")
        print(f"  Modular direct costs: ${budget.get('modular_direct', budget['summary']['total_direct']):,.2f}")

    print(f"\n{'='*60}\n")


def main():
    parser = argparse.ArgumentParser(description='Calculate grant budget')
    parser.add_argument('--agency', required=True, choices=list(AGENCY_RULES.keys()),
                       help='Funding agency')
    parser.add_argument('--years', type=int, required=True, help='Project duration in years')
    parser.add_argument('--personnel', type=str, help='Personnel specification (e.g., "PI:2months,Postdoc:12months")')
    parser.add_argument('--json', action='store_true', help='Output as JSON')

    args = parser.parse_args()

    # Parse personnel if provided
    personnel = []
    if args.personnel:
        for spec in args.personnel.split(","):
            parts = spec.strip().split(":")
            if len(parts) == 2:
                role = parts[0].strip()
                effort = int(parts[1].replace("months", "").strip())
                salary = 80000  # Default salary
                if "pi" in role.lower():
                    salary = 120000
                elif "postdoc" in role.lower():
                    salary = 65000
                elif "phd" in role.lower() or "grad" in role.lower():
                    salary = 35000
                personnel.append({"role": role, "salary": salary, "effort_months": effort})

    if not personnel:
        personnel = [{"role": "PI", "salary": 120000, "effort_months": 2}]

    budget = calculate_budget(
        agency=args.agency,
        years=args.years,
        personnel=personnel
    )

    if args.json:
        print(json.dumps(budget, indent=2))
    else:
        print_budget(budget)


if __name__ == "__main__":
    main()
