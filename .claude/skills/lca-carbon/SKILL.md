---
name: lca-carbon
description: Life Cycle Assessment (LCA) and carbon accounting following ISO 14040/14044, GHG Protocol, and environmental impact assessment standards. Supports LCA reports, carbon footprint calculations, environmental product declarations (EPD), and sustainability assessments for engineering and environmental research.
allowed-tools: [Read, Write, Edit, Bash]
---

# Life Cycle Assessment & Carbon Accounting

## Overview

This skill provides comprehensive guidance for conducting Life Cycle Assessments (LCA) and carbon footprint analyses following international standards. It covers the full LCA workflow from goal definition to interpretation, with specific guidance for engineering and environmental applications.

**Key Standards:**
- ISO 14040:2006 — LCA: Principles and Framework
- ISO 14044:2006 — LCA: Requirements and Guidelines
- ISO 14064 — GHG Accounting and Verification
- ISO 14025 — Environmental Labels and Declarations (Type III, EPD)
- GHG Protocol — Corporate and Product Life Cycle Standards
- PAS 2050 — Product Carbon Footprint

## When to Use This Skill

Use this skill when:
- Conducting a full Life Cycle Assessment for a product, process, or system
- Calculating carbon footprints (organizational, product, project)
- Writing environmental impact assessment sections for papers or reports
- Preparing Environmental Product Declarations (EPDs)
- Comparing environmental performance of alternative materials/processes
- Supporting claims about sustainability or environmental benefit
- Writing grant proposals related to environmental sustainability, carbon neutrality, or circular economy
- Reviewing manuscripts that include LCA or carbon footprint analyses

## Core Workflow

### Phase 1: Goal and Scope Definition

1. **Define the Goal**:
   - Purpose of the study (comparison, improvement, marketing, policy)
   - Intended audience
   - Decision context
   - Commissioner of the study

2. **Define the Scope**:
   - **Functional unit**: Quantified performance of the product system (e.g., "1 m² of wall assembly with 50-year service life")
   - **System boundary**: Cradle-to-grave, cradle-to-gate, cradle-to-cradle, gate-to-gate
   - **Cut-off criteria**: Mass, energy, or environmental significance thresholds (typically 1%)
   - **Allocation procedures**: For multi-output processes (mass, economic, physical)
   - **Impact categories**: GWP, AP, EP, ODP, POCP, ADPE, ADPF

3. **Reference Flow**: The amount of product needed to fulfill the functional unit

### Phase 2: Life Cycle Inventory (LCI)

1. **Data Collection**:
   - **Foreground data**: Direct measurements from the studied system
   - **Background data**: LCI databases (ecoinvent, GaBi, openLCA Nexus)
   - **Literature data**: Peer-reviewed LCA studies

2. **Process Mapping**:
   - Raw material extraction
   - Transportation
   - Manufacturing/processing
   - Use phase (energy, maintenance, repair)
   - End-of-life (recycling, disposal, recovery)

3. **Data Quality Assessment**:
   - Temporal representativeness
   - Geographic representativeness
   - Technological representativeness
   - Completeness and precision

### Phase 3: Life Cycle Impact Assessment (LCIA)

1. **Classification**: Assign inventory flows to impact categories
2. **Characterization**: Convert flows to common units using characterization factors
3. **Normalization** (optional): Express results relative to reference values
4. **Weighting** (optional): Assign relative importance to impact categories

**Common Impact Categories (CML, ReCiPe, TRACI):**

| Category | Unit | Description |
|----------|------|-------------|
| GWP | kg CO₂ eq | Global Warming Potential (100-year) |
| AP | kg SO₂ eq | Acidification Potential |
| EP | kg PO₄³⁻ eq | Eutrophication Potential |
| ODP | kg CFC-11 eq | Ozone Depletion Potential |
| POCP | kg C₂H₄ eq | Photochemical Ozone Creation Potential |
| ADPE | kg Sb eq | Abiotic Depletion Potential (elements) |
| ADPF | MJ | Abiotic Depletion Potential (fossil fuels) |
| HTP | kg 1,4-DB eq | Human Toxicity Potential |
| FAETP | kg 1,4-DB eq | Freshwater Aquatic Ecotoxicity |
| MAETP | kg 1,4-DB eq | Marine Aquatic Ecotoxicity |
| TETP | kg 1,4-DB eq | Terrestrial Ecotoxicity |

### Phase 4: Interpretation

1. **Identify Significant Issues**: Major contributors to each impact category
2. **Sensitivity Analysis**: Test key assumptions and parameters
3. **Uncertainty Analysis**: Monte Carlo simulation or scenario analysis
4. **Conclusions and Recommendations**: Based on findings, with limitations

## Carbon Footprint Calculation

### Organizational Carbon Footprint (ISO 14064)

**Scope 1 — Direct Emissions:**
- Stationary combustion (boilers, furnaces)
- Mobile combustion (vehicles)
- Process emissions (chemical reactions)
- Fugitive emissions (leaks, methane)

**Scope 2 — Indirect (Energy):**
- Purchased electricity
- Purchased steam/heating
- Purchased cooling

**Scope 3 — Other Indirect:**
- Supply chain (upstream)
- Transportation and distribution
- Use of sold products
- End-of-life treatment of sold products
- Business travel, employee commuting
- Investments

### Product Carbon Footprint (PAS 2050 / ISO 14067)

```
CF = Σ(Mi × EFi) + Σ(Ej × EFj) + Σ(Dk × EFk)

Where:
  CF = Carbon Footprint (kg CO₂ eq)
  Mi = Mass of material i (kg)
  EFi = Emission factor for material i (kg CO₂ eq/kg)
  Ej = Energy consumption j (kWh or MJ)
  EFj = Emission factor for energy source j
  Dk = Distance for transport k (km)
  EFk = Emission factor for transport mode k (kg CO₂ eq/kg·km)
```

### Common Emission Factors

| Source | Factor | Unit | Source |
|--------|--------|------|--------|
| Electricity (China) | 0.5810 | kg CO₂/kWh | China MEE 2022 |
| Electricity (US) | 0.4171 | kg CO₂/kWh | EPA eGRID 2022 |
| Electricity (EU) | 0.2760 | kg CO₂/kWh | EEA 2022 |
| Natural gas | 2.0181 | kg CO₂/m³ | IPCC |
| Diesel | 2.6775 | kg CO₂/L | IPCC |
| Gasoline | 2.3035 | kg CO₂/L | IPCC |
| Cement (Portland) | 0.6176 | kg CO₂/kg | ecoinvent |
| Steel (BOF) | 1.8540 | kg CO₂/kg | worldsteel |
| Steel (EAF) | 0.7210 | kg CO₂/kg | worldsteel |
| Aluminum (primary) | 10.580 | kg CO₂/kg | IAI |
| Concrete (C30) | 0.1321 | kg CO₂/kg | IPCC |
| Transport (truck) | 0.1008 | kg CO₂/t·km | IPCC |
| Transport (rail) | 0.0247 | kg CO₂/t·km | IPCC |
| Transport (ship) | 0.0156 | kg CO₂/t·km | IPCC |

## Energy Systems Analysis (能源系统分析)

### Levelized Cost of Energy (LCOE) Calculation

LCOE = (Total Lifetime Cost) / (Total Lifetime Energy Production)

**Formula:**
```
LCOE = [Sum_t (CAPEX_t + OPEX_t + Fuel_t) / (1+r)^t] / [Sum_t E_t / (1+r)^t]
```

Where:
- CAPEX_t = Capital expenditure in year t (RMB/kW or $/kW)
- OPEX_t = Operating expenditure in year t (fixed + variable, RMB/kW/yr)
- Fuel_t = Fuel cost in year t (for thermal, RMB/kWh)
- r = Discount rate (typically 5-8% for Chinese projects)
- E_t = Energy production in year t (kWh)
- t = Year (0 to N, where N = project lifetime)

**Typical LCOE Values (2024, China):**
| Technology | CAPEX (RMB/kW) | OPEX (% CAPEX/yr) | Lifetime (yr) | LCOE (RMB/kWh) |
|-----------|---------------|-------------------|---------------|----------------|
| Solar PV (utility) | 3,500-4,500 | 1.5-2.0% | 25 | 0.25-0.40 |
| Onshore Wind | 5,000-6,500 | 2.0-3.0% | 20-25 | 0.30-0.45 |
| Offshore Wind | 12,000-18,000 | 2.5-3.5% | 25 | 0.55-0.80 |
| Coal (ultra-supercritical) | 3,500-4,000 | 3.0-4.0% | 30 | 0.35-0.50 |
| Natural Gas CCGT | 2,500-3,500 | 2.5-3.5% | 30 | 0.45-0.65 |
| Nuclear | 15,000-20,000 | 1.5-2.5% | 60 | 0.35-0.50 |
| Biomass | 8,000-12,000 | 3.0-5.0% | 20 | 0.50-0.75 |

**LCOE Reporting Requirements:**
1. State discount rate and justify (WACC or social discount rate)
2. State currency and base year (e.g., 2024 RMB)
3. Report CAPEX breakdown (equipment, installation, grid connection, land)
4. Report annual OPEX breakdown (fixed, variable, insurance)
5. Include capacity factor assumptions
6. Perform sensitivity analysis on key parameters (discount rate, capacity factor, fuel cost)
7. Compare with grid parity threshold

### Building Energy Simulation Reporting Standards

When reporting building energy simulation results (EnergyPlus, DeST, TRNSYS, etc.):

**Required Information:**
1. **Simulation Software**: Name, version, validation status
2. **Weather Data**: Source (CTSWDB for China, TMY3 for US, IWEC for international), location, typical vs. design day
3. **Building Geometry**: Floor area (gross/net), number of stories, orientation, window-to-wall ratio (WWR)
4. **Envelope Properties**: U-values for walls/roof/floor/windows (W/m²·K), thermal mass, air tightness (ACH50)
5. **HVAC System**: System type (VAV, FCU, VRV, split), COP/EER, part-load curves
6. **Internal Loads**: Lighting (W/m²), equipment (W/m²), occupancy (people/m²), schedule
7. **Simulation Settings**: Timestep, convergence criteria, solar distribution algorithm

**Required Outputs:**
| Metric | Unit | Description |
|--------|------|-------------|
| EUI | kWh/m²/yr | Energy Use Intensity (total) |
| Heating EUI | kWh/m²/yr | Heating energy |
| Cooling EUI | kWh/m²/yr | Cooling energy |
| Lighting EUI | kWh/m²/yr | Lighting energy |
| Peak Load (heating) | W/m² | Design day peak |
| Peak Load (cooling) | W/m² | Design day peak |
| PEF/GEF | - | Primary/Gross Energy Factor |
| Carbon Intensity | kgCO₂e/m²/yr | Operational carbon |

**Calibration Requirements (if comparing with measured data):**
- CV-RMSE ≤ 15% (monthly), ≤ 30% (hourly) per ASHRAE Guideline 14
- NMBE ≤ 5% (monthly)
- Report calibration methodology (manual vs. automated)
- Show monthly comparison plot (simulated vs. measured)

### Carbon Intensity Time Series Analysis

For temporal carbon footprint analysis:

**Grid Carbon Intensity (gCO₂/kWh):**
| Region | Average | Peak | Off-Peak | Source |
|--------|---------|------|----------|--------|
| China National | 550-600 | 700-800 | 400-500 | CSG/SGCC |
| China East | 600-700 | 800-900 | 450-550 | Regional grid |
| China North | 700-800 | 900-1000 | 500-600 | Coal-heavy |
| China South | 400-500 | 550-650 | 300-400 | Hydro-rich |
| US National | 380-420 | 450-500 | 300-350 | EPA eGRID |
| EU Average | 250-300 | 350-400 | 180-220 | EEA |

**Time-Series Reporting:**
1. Report temporal resolution (hourly/monthly/annual)
2. Use marginal vs. average emission factors (specify which)
3. For demand-side management studies: report carbon savings from load shifting
4. For renewable integration: report curtailment-adjusted carbon intensity
5. Source: Use real grid data when available (China: CEC; US: EPA; EU: ENTSO-E)

### Energy Balance Analysis Framework

For whole-building or whole-system energy analysis:

**Energy Balance Equation:**
```
Q_input = Q_useful + Q_losses + Q_storage
```

**Reporting Template:**
| Component | Energy (kWh/yr) | % of Total | Notes |
|-----------|-----------------|------------|-------|
| **Inputs** | | | |
| Solar gains | | | Through windows + solar collector |
| Internal gains | | | Lighting + equipment + occupants |
| Heating input | | | From HVAC system |
| Cooling input | | | From HVAC system |
| **Outputs** | | | |
| Transmission losses | | | Through envelope |
| Infiltration losses | | | Air leakage |
| Ventilation losses | | | Fresh air requirement |
| Domestic hot water | | | End use |
| **Storage** | | | |
| Thermal mass | | | Seasonal storage |

### Energy Efficiency Metrics

| Metric | Formula | Application |
|--------|---------|-------------|
| COP | Q_heating / W_input | Heat pump heating performance |
| EER | Q_cooling / W_input | Cooling system performance |
| SCOP | Seasonal COP | Annual heating performance |
| SEER | Seasonal EER | Annual cooling performance |
| SPF | Seasonal Performance Factor | Heat pump system (including auxiliaries) |
| PEF | Primary Energy / Final Energy | Energy source efficiency |
| GEF | Gross Energy / Delivered Energy | Including generation losses |
| EUI | Total Energy / Floor Area | Building energy intensity |
| RE ratio | Renewable / Total | Renewable energy fraction |
| Self-sufficiency | On-site generation / Demand | Energy independence |

### Renewable Energy System Sizing

**Solar PV System:**
- Required: Location (latitude, longitude), tilt angle, azimuth, system losses (10-20%)
- Output: Annual yield (kWh/kWp), capacity factor (%)
- Tools: PVsyst, SAM, Homer
- Reporting: Module type, inverter efficiency, degradation rate (0.3-0.7%/yr)

**Battery Storage:**
- Required: Capacity (kWh), power (kW), round-trip efficiency (85-95%), DoD (80-90%)
- Reporting: Cycle life, degradation rate, warranty terms
- Application: Peak shaving, self-consumption optimization, grid services

**Hybrid Systems:**
- Report sizing optimization methodology (HOMER, custom optimizer)
- Report dispatch strategy (rule-based, MPC, RL)
- Report reliability metrics (LOLP, LPSP)
- Report economics (NPC, LCOE, payback period, IRR)

## HVAC and Building Energy Systems

### Building Energy Modeling

**Required Reporting for Building Simulation Papers:**
- [ ] Building geometry and orientation
- [ ] Envelope specifications (U-values, SHGC, infiltration rates)
- [ ] HVAC system type and specifications
- [ ] Internal loads (lighting, equipment, occupancy schedules)
- [ ] Weather data source and location
- [ ] Simulation software and version
- [ ] Calibration methodology (if comparing to measured data)

**Key Metrics:**
- Energy Use Intensity (EUI): kWh/m2/year or kBtu/ft2/year
- Peak heating/cooling load: W/m2
- HVAC system COP/EER/SEER
- Thermal comfort indices (PMV, PPD per ASHRAE 55)
- Indoor air quality (CO2, PM2.5, TVOC)

**ASHRAE Standards Reference:**
| Standard | Topic | Use When |
|----------|-------|----------|
| ASHRAE 55 | Thermal Comfort | Evaluating occupant comfort |
| ASHRAE 62.1 | Ventilation | Evaluating indoor air quality |
| ASHRAE 90.1 | Energy Efficiency | Evaluating building energy code compliance |
| ASHRAE 189.1 | Green Buildings | Evaluating sustainable design |
| ASHRAE 209 | Energy Simulation | Validating building energy models |

### Carbon Accounting for Buildings

**Scope 1 (Direct):**
- On-site combustion (natural gas, oil)
- Refrigerant leakage
- Backup generators

**Scope 2 (Indirect - Electricity):**
- Grid electricity consumption
- District heating/cooling

**Scope 3 (Value Chain):**
- Embodied carbon of materials
- Construction emissions
- End-of-life emissions
- Transportation of occupants

**Reporting Template:**
```
Carbon Footprint Report - [Building/System Name]
Scope 1: [value] tCO2e/year
Scope 2: [value] tCO2e/year (using [grid emission factor] kgCO2/kWh)
Scope 3: [value] tCO2e/year
Total: [value] tCO2e/year
EUI: [value] kWh/m2/year
Carbon Intensity: [value] kgCO2e/m2/year
```

### HVAC System Optimization

**Common Research Topics:**
- Demand-controlled ventilation
- Thermal energy storage
- Heat pump optimization
- Radiant cooling/heating
- Mixed-mode ventilation
- Smart thermostat algorithms
- District energy systems

**Evaluation Framework:**
- [ ] Energy savings vs. baseline HVAC system
- [ ] Thermal comfort maintenance (ASHRAE 55 compliance)
- [ ] Indoor air quality maintenance (ASHRAE 62.1 compliance)
- [ ] Economic analysis (payback period, LCC, NPV)
- [ ] Carbon reduction potential
- [ ] Scalability and retrofit feasibility

### Energy Systems Analysis

**Grid-Interactive Efficient Buildings:**
- Demand response capability
- Load flexibility and shifting
- Renewable energy integration
- Battery storage optimization
- Vehicle-to-building (V2B) integration

**District Energy Systems:**
- Combined heat and power (CHP)
- District heating/cooling networks
- Waste heat recovery
- Fifth-generation district heating
- Sector coupling analysis

**Renewable Energy Integration:**
- Solar PV system sizing and optimization
- Solar thermal system design
- Ground-source heat pump performance
- Building-integrated renewables
- Microgrid design and control

## Engineering-Specific LCA Guidance

### Construction Materials LCA

**System Boundary**: Cradle-to-gate + construction + use + end-of-life

**Key stages:**
1. Raw material extraction and processing
2. Transportation to factory
3. Manufacturing
4. Transportation to site
5. Construction/installation
6. Use phase (maintenance, energy consumption)
7. Demolition and end-of-life

**Functional units:**
- Structural elements: "1 m of beam supporting X kN for Y years"
- Building envelope: "1 m² of wall assembly achieving U-value of X for Y years"
- Pavement: "1 km of road with Z design life"

### Water Treatment LCA

**Key considerations:**
- Chemical consumption (coagulants, disinfectants)
- Energy for pumping and treatment
- Sludge management and disposal
- Infrastructure embodied carbon
- Distribution network losses

### Energy Systems LCA

**Key considerations:**
- Manufacturing of equipment (solar panels, turbines, batteries)
- Installation and commissioning
- Operational efficiency and degradation
- Maintenance and replacement cycles
- Decommissioning and recycling

## LCA Software and Tools

| Tool | Type | Database | Cost |
|------|------|----------|------|
| openLCA | Free | ecoinvent (license), open databases | Free |
| SimaPro | Commercial | ecoinvent, GaBi | ~$5,000/year |
| GaBi | Commercial | GaBi databases | ~$8,000/year |
| One Click LCA | Cloud | Multiple | Subscription |
| Brightway2 | Python | ecoinvent, custom | Free (Python) |
| EASETECH | Academic | DTU databases | Academic license |

## LCA Report Structure

See `assets/lca_report_template.md` for the full template. Key sections:

1. **Executive Summary**
2. **Goal and Scope Definition**
3. **Life Cycle Inventory**
4. **Life Cycle Impact Assessment**
5. **Interpretation and Sensitivity Analysis**
6. **Conclusions and Recommendations**
7. **Data Quality Assessment**
8. **References**

## Writing Tips

### For Journal Papers
- Clearly state the LCA standard followed (ISO 14040/14044)
- Justify the functional unit and system boundary
- Report sensitivity analysis results
- Discuss data quality and limitations
- Compare with literature values where possible
- Use consistent impact assessment methods

### For Grant Proposals
- Connect LCA to research objectives (e.g., "quantify environmental benefits of proposed method")
- Describe data collection plan and access to LCI databases
- Include preliminary LCA results if available
- Discuss how LCA will inform design decisions

### Common Pitfalls
- Inconsistent functional units in comparisons
- Narrow system boundaries (missing significant stages)
- Using outdated or regionally inappropriate emission factors
- Ignoring uncertainty and sensitivity
- Overclaiming based on single impact category

## References

**Standards:**
- ISO 14040:2006 Environmental management — Life cycle assessment — Principles and framework
- ISO 14044:2006 Environmental management — Life cycle assessment — Requirements and guidelines
- ISO 14064-1:2018 GHG — Part 1: Specification for quantification and reporting
- ISO 14067:2018 Carbon footprint of products

**Guidance:**
- GHG Protocol Corporate Accounting and Reporting Standard
- GHG Protocol Product Life Cycle Accounting and Reporting Standard
- PAS 2050:2011 Specification for the assessment of life cycle GHG emissions

**Databases:**
- ecoinvent: https://ecoinvent.org/
- GaBi: https://gabi.sphera.com/
- US LCI: https://www.nrel.gov/lci/
- European Reference Life Cycle Database: https://eplca.jrc.ec.europa.eu/

## Dependencies

### Required Python Packages
```bash
pip install brightway2  # For programmatic LCA
pip install pandas numpy matplotlib  # For data analysis and visualization
```

### Optional
```bash
pip install premise  # For prospective LCA with future scenarios
pip install bw2io    # For importing LCI databases into Brightway
```
