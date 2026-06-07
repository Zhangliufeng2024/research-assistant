#!/usr/bin/env python3
"""
Carbon Footprint Calculator
Calculate carbon emissions for materials, energy, and transport.

Usage:
    python carbon_calculator.py --material concrete --quantity 100 --unit m3
    python carbon_calculator.py --energy electricity --quantity 5000 --region china
    python carbon_calculator.py --transport truck --quantity 100 --distance 500
    python carbon_calculator.py --input project_data.json --output results.json
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


# Emission factors database
EMISSION_FACTORS = {
    "materials": {
        "concrete_c30": {"factor": 0.1321, "unit": "kg CO2/kg", "density": 2400, "source": "ecoinvent"},
        "concrete_c40": {"factor": 0.1562, "unit": "kg CO2/kg", "density": 2450, "source": "ecoinvent"},
        "concrete_c50": {"factor": 0.1803, "unit": "kg CO2/kg", "density": 2500, "source": "ecoinvent"},
        "cement_portland": {"factor": 0.6176, "unit": "kg CO2/kg", "density": 1500, "source": "ecoinvent"},
        "steel_bof": {"factor": 1.8540, "unit": "kg CO2/kg", "density": 7850, "source": "worldsteel"},
        "steel_eaf": {"factor": 0.7210, "unit": "kg CO2/kg", "density": 7850, "source": "worldsteel"},
        "steel_rebar": {"factor": 1.4200, "unit": "kg CO2/kg", "density": 7850, "source": "ecoinvent"},
        "aluminum_primary": {"factor": 10.580, "unit": "kg CO2/kg", "density": 2700, "source": "IAI"},
        "aluminum_recycled": {"factor": 0.5120, "unit": "kg CO2/kg", "density": 2700, "source": "ecoinvent"},
        "copper": {"factor": 3.2100, "unit": "kg CO2/kg", "density": 8960, "source": "ecoinvent"},
        "glass": {"factor": 0.8500, "unit": "kg CO2/kg", "density": 2500, "source": "ecoinvent"},
        "pvc": {"factor": 1.9200, "unit": "kg CO2/kg", "density": 1400, "source": "ecoinvent"},
        "hdpe": {"factor": 1.7800, "unit": "kg CO2/kg", "density": 950, "source": "ecoinvent"},
        "timber_softwood": {"factor": -1.6400, "unit": "kg CO2/kg", "density": 500, "source": "ecoinvent"},
        "timber_hardwood": {"factor": -1.8300, "unit": "kg CO2/kg", "density": 700, "source": "ecoinvent"},
        "brick": {"factor": 0.2400, "unit": "kg CO2/kg", "density": 1900, "source": "ecoinvent"},
        "aggregate": {"factor": 0.0078, "unit": "kg CO2/kg", "density": 1600, "source": "ecoinvent"},
        "insulation_mineral_wool": {"factor": 1.3500, "unit": "kg CO2/kg", "density": 100, "source": "ecoinvent"},
        "insulation_eps": {"factor": 2.8900, "unit": "kg CO2/kg", "density": 25, "source": "ecoinvent"},
        "frp_carbon": {"factor": 22.100, "unit": "kg CO2/kg", "density": 1600, "source": "ecoinvent"},
        "frp_glass": {"factor": 5.2000, "unit": "kg CO2/kg", "density": 2000, "source": "ecoinvent"},
    },
    "energy": {
        "electricity_china": {"factor": 0.5810, "unit": "kg CO2/kWh", "source": "China MEE 2022"},
        "electricity_us": {"factor": 0.4171, "unit": "kg CO2/kWh", "source": "EPA eGRID 2022"},
        "electricity_eu": {"factor": 0.2760, "unit": "kg CO2/kWh", "source": "EEA 2022"},
        "electricity_india": {"factor": 0.7080, "unit": "kg CO2/kWh", "source": "CEA 2022"},
        "electricity_global": {"factor": 0.4750, "unit": "kg CO2/kWh", "source": "IEA 2022"},
        "natural_gas": {"factor": 2.0181, "unit": "kg CO2/m3", "source": "IPCC"},
        "diesel": {"factor": 2.6775, "unit": "kg CO2/L", "source": "IPCC"},
        "gasoline": {"factor": 2.3035, "unit": "kg CO2/L", "source": "IPCC"},
        "lpg": {"factor": 1.5143, "unit": "kg CO2/L", "source": "IPCC"},
        "coal_bituminous": {"factor": 2.4210, "unit": "kg CO2/kg", "source": "IPCC"},
        "heating_oil": {"factor": 2.5244, "unit": "kg CO2/L", "source": "IPCC"},
    },
    "transport": {
        "truck_heavy": {"factor": 0.1008, "unit": "kg CO2/t*km", "source": "IPCC"},
        "truck_medium": {"factor": 0.1765, "unit": "kg CO2/t*km", "source": "IPCC"},
        "truck_light": {"factor": 0.2765, "unit": "kg CO2/t*km", "source": "IPCC"},
        "rail_freight": {"factor": 0.0247, "unit": "kg CO2/t*km", "source": "IPCC"},
        "ship_bulk": {"factor": 0.0156, "unit": "kg CO2/t*km", "source": "IPCC"},
        "ship_container": {"factor": 0.0283, "unit": "kg CO2/t*km", "source": "IPCC"},
        "air_freight": {"factor": 1.1020, "unit": "kg CO2/t*km", "source": "IPCC"},
        "pipeline": {"factor": 0.0155, "unit": "kg CO2/t*km", "source": "IPCC"},
    }
}

# GWP values (IPCC AR6)
GWP = {
    "CO2": 1.0,
    "CH4": 29.8,      # 100-year GWP
    "CH4_fossil": 29.8,
    "CH4_biogenic": 29.8,
    "N2O": 273.0,
    "SF6": 25200.0,
    "HFC-134a": 1530.0,
    "PFC-14": 7390.0,
}


def calculate_material_emissions(material, quantity_kg):
    """Calculate emissions from material consumption."""
    mat_key = material.lower().replace(" ", "_").replace("-", "_")
    if mat_key not in EMISSION_FACTORS["materials"]:
        available = ", ".join(EMISSION_FACTORS["materials"].keys())
        return {"error": f"Unknown material '{material}'. Available: {available}"}

    factor_data = EMISSION_FACTORS["materials"][mat_key]
    emissions_kg = quantity_kg * factor_data["factor"]

    return {
        "material": material,
        "quantity_kg": quantity_kg,
        "emission_factor": factor_data["factor"],
        "factor_unit": factor_data["unit"],
        "source": factor_data["source"],
        "emissions_kg_CO2eq": round(emissions_kg, 2),
        "emissions_t_CO2eq": round(emissions_kg / 1000, 4),
    }


def calculate_energy_emissions(energy_type, quantity, region="china"):
    """Calculate emissions from energy consumption."""
    # Try direct energy type first
    key = energy_type.lower().replace(" ", "_")
    if key in EMISSION_FACTORS["energy"]:
        factor_data = EMISSION_FACTORS["energy"][key]
    # Try electricity with region
    elif key == "electricity":
        region_key = f"electricity_{region.lower()}"
        if region_key in EMISSION_FACTORS["energy"]:
            factor_data = EMISSION_FACTORS["energy"][region_key]
        else:
            factor_data = EMISSION_FACTORS["energy"]["electricity_global"]
    else:
        available = ", ".join(EMISSION_FACTORS["energy"].keys())
        return {"error": f"Unknown energy type '{energy_type}'. Available: {available}"}

    emissions_kg = quantity * factor_data["factor"]

    return {
        "energy_type": energy_type,
        "quantity": quantity,
        "region": region,
        "emission_factor": factor_data["factor"],
        "factor_unit": factor_data["unit"],
        "source": factor_data["source"],
        "emissions_kg_CO2eq": round(emissions_kg, 2),
        "emissions_t_CO2eq": round(emissions_kg / 1000, 4),
    }


def calculate_transport_emissions(transport_mode, mass_tonnes, distance_km):
    """Calculate emissions from transportation."""
    mode_key = transport_mode.lower().replace(" ", "_").replace("-", "_")
    if mode_key not in EMISSION_FACTORS["transport"]:
        available = ", ".join(EMISSION_FACTORS["transport"].keys())
        return {"error": f"Unknown transport mode '{transport_mode}'. Available: {available}"}

    factor_data = EMISSION_FACTORS["transport"][mode_key]
    tonne_km = mass_tonnes * distance_km
    emissions_kg = tonne_km * factor_data["factor"]

    return {
        "transport_mode": transport_mode,
        "mass_tonnes": mass_tonnes,
        "distance_km": distance_km,
        "tonne_km": round(tonne_km, 2),
        "emission_factor": factor_data["factor"],
        "factor_unit": factor_data["unit"],
        "source": factor_data["source"],
        "emissions_kg_CO2eq": round(emissions_kg, 2),
        "emissions_t_CO2eq": round(emissions_kg / 1000, 4),
    }


def calculate_project_emissions(project_data):
    """Calculate total project emissions from JSON input."""
    results = {
        "project_name": project_data.get("name", "Unnamed Project"),
        "categories": [],
        "total_emissions_kg_CO2eq": 0,
        "total_emissions_t_CO2eq": 0,
    }

    # Process materials
    for mat in project_data.get("materials", []):
        result = calculate_material_emissions(mat["name"], mat["quantity_kg"])
        if "error" not in result:
            result["category"] = "materials"
            results["categories"].append(result)
            results["total_emissions_kg_CO2eq"] += result["emissions_kg_CO2eq"]

    # Process energy
    for en in project_data.get("energy", []):
        result = calculate_energy_emissions(
            en["type"], en["quantity"], en.get("region", "china")
        )
        if "error" not in result:
            result["category"] = "energy"
            results["categories"].append(result)
            results["total_emissions_kg_CO2eq"] += result["emissions_kg_CO2eq"]

    # Process transport
    for tr in project_data.get("transport", []):
        result = calculate_transport_emissions(
            tr["mode"], tr["mass_tonnes"], tr["distance_km"]
        )
        if "error" not in result:
            result["category"] = "transport"
            results["categories"].append(result)
            results["total_emissions_kg_CO2eq"] += result["emissions_kg_CO2eq"]

    results["total_emissions_kg_CO2eq"] = round(results["total_emissions_kg_CO2eq"], 2)
    results["total_emissions_t_CO2eq"] = round(results["total_emissions_kg_CO2eq"] / 1000, 4)

    return results


def calculate_lcoe(capex, opex_annual, fuel_cost_annual, annual_production, lifetime, discount_rate=0.06):
    """
    Calculate Levelized Cost of Energy (LCOE).

    Parameters:
    - capex: Capital expenditure (total, year 0)
    - opex_annual: Annual operating expenditure (list or constant)
    - fuel_cost_annual: Annual fuel cost (list or constant, 0 for renewables)
    - annual_production: Annual energy production in kWh (list or constant)
    - lifetime: Project lifetime in years
    - discount_rate: Discount rate (default 6%)

    Returns:
    - LCOE in currency/kWh
    """
    total_cost = 0
    total_energy = 0

    for t in range(lifetime + 1):
        discount_factor = (1 + discount_rate) ** t

        if t == 0:
            total_cost += capex / discount_factor
        else:
            opex = opex_annual[t-1] if isinstance(opex_annual, list) else opex_annual
            fuel = fuel_cost_annual[t-1] if isinstance(fuel_cost_annual, list) else fuel_cost_annual
            total_cost += (opex + fuel) / discount_factor

            prod = annual_production[t-1] if isinstance(annual_production, list) else annual_production
            total_energy += prod / discount_factor

    return total_cost / total_energy if total_energy > 0 else float('inf')


def calculate_building_carbon_intensity(eui_kwh, grid_intensity_gco2_kwh, floor_area_m2):
    """
    Calculate building operational carbon intensity.

    Parameters:
    - eui_kwh: Energy Use Intensity in kWh/m²/yr
    - grid_intensity_gco2_kwh: Grid carbon intensity in gCO₂/kWh
    - floor_area_m2: Building floor area in m²

    Returns:
    - Carbon intensity in kgCO₂e/m²/yr
    """
    return eui_kwh * grid_intensity_gco2_kwh / 1000


def calculate_energy_balance(solar_gains, internal_gains, heating_input, cooling_input,
                              transmission_losses, infiltration_losses, ventilation_losses, dhw):
    """
    Calculate building energy balance.

    Returns dict with all components and net storage.
    """
    total_input = solar_gains + internal_gains + heating_input + cooling_input
    total_output = transmission_losses + infiltration_losses + ventilation_losses + dhw
    storage = total_input - total_output

    return {
        "inputs": {
            "solar_gains": solar_gains,
            "internal_gains": internal_gains,
            "heating_input": heating_input,
            "cooling_input": cooling_input,
            "total": total_input
        },
        "outputs": {
            "transmission_losses": transmission_losses,
            "infiltration_losses": infiltration_losses,
            "ventilation_losses": ventilation_losses,
            "dhw": dhw,
            "total": total_output
        },
        "net_storage": storage,
        "balance_check": abs(storage) < total_input * 0.01  # 1% tolerance
    }


def list_emission_factors():
    """List all available emission factors."""
    print("\n=== AVAILABLE EMISSION FACTORS ===\n")
    for category, factors in EMISSION_FACTORS.items():
        print(f"\n{category.upper()}:")
        for name, data in factors.items():
            print(f"  {name}: {data['factor']} {data['unit']} ({data['source']})")


def main():
    parser = argparse.ArgumentParser(
        description="Carbon Footprint Calculator",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s --material concrete_c30 --quantity 100 --unit m3
  %(prog)s --energy electricity --quantity 5000 --region china
  %(prog)s --transport truck_heavy --quantity 100 --distance 500
  %(prog)s --input project_data.json --output results.json
  %(prog)s --list
        """
    )

    parser.add_argument("--material", type=str, help="Material type")
    parser.add_argument("--energy", type=str, help="Energy type")
    parser.add_argument("--transport", type=str, help="Transport mode")
    parser.add_argument("--quantity", type=float, help="Quantity (kg for materials, kWh/m3/L for energy)")
    parser.add_argument("--mass", type=float, help="Mass in tonnes (for transport)")
    parser.add_argument("--distance", type=float, help="Distance in km (for transport)")
    parser.add_argument("--unit", type=str, default="kg", help="Unit for material quantity (kg, m3, t)")
    parser.add_argument("--region", type=str, default="china", help="Region for electricity emission factor")
    parser.add_argument("--input", type=str, help="JSON input file with project data")
    parser.add_argument("--output", type=str, help="JSON output file for results")
    parser.add_argument("--list", action="store_true", help="List all emission factors")

    args = parser.parse_args()

    if args.list:
        list_emission_factors()
        return

    if args.input:
        with open(args.input, "r") as f:
            project_data = json.load(f)
        results = calculate_project_emissions(project_data)
        if args.output:
            with open(args.output, "w") as f:
                json.dump(results, f, indent=2)
            print(f"Results saved to {args.output}")
        else:
            print(json.dumps(results, indent=2))
        return

    if args.material:
        quantity = args.quantity
        if args.unit == "m3":
            mat_key = args.material.lower().replace(" ", "_").replace("-", "_")
            if mat_key in EMISSION_FACTORS["materials"]:
                density = EMISSION_FACTORS["materials"][mat_key].get("density", 2400)
                quantity = args.quantity * density
                print(f"Converted {args.quantity} m3 x {density} kg/m3 = {quantity} kg")
        elif args.unit == "t":
            quantity = args.quantity * 1000

        result = calculate_material_emissions(args.material, quantity)
        print(json.dumps(result, indent=2))

    elif args.energy:
        result = calculate_energy_emissions(args.energy, args.quantity, args.region)
        print(json.dumps(result, indent=2))

    elif args.transport:
        if not args.mass or not args.distance:
            print("Error: --mass (tonnes) and --distance (km) required for transport calculation")
            sys.exit(1)
        result = calculate_transport_emissions(args.transport, args.mass, args.distance)
        print(json.dumps(result, indent=2))

    else:
        parser.print_help()


if __name__ == "__main__":
    main()
