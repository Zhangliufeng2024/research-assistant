# GHG Protocol Guide

## Overview

The GHG Protocol provides the world's most widely used greenhouse gas accounting standards. This guide covers the key frameworks relevant to engineering and environmental research.

## Corporate Standard

### Scope Framework

```
Scope 1 (Direct)          Scope 2 (Indirect-Energy)     Scope 3 (Other Indirect)
┌──────────────────┐      ┌──────────────────┐         ┌──────────────────┐
│ • Stationary      │      │ • Purchased       │         │ • Supply chain    │
│   combustion      │      │   electricity     │         │ • Transportation  │
│ • Mobile          │      │ • Purchased       │         │ • Use of products │
│   combustion      │      │   steam           │         │ • End-of-life     │
│ • Process         │      │ • Purchased       │         │ • Business travel │
│   emissions       │      │   cooling         │         │ • Investments     │
│ • Fugitive        │      │                   │         │ • Waste           │
│   emissions       │      │                   │         │ • Employee commute│
└──────────────────┘      └──────────────────┘         └──────────────────┘
```

### Calculation Formula

```
Emissions = Activity Data × Emission Factor × Global Warming Potential

Where:
  Activity Data = Quantified measure of activity (kWh, L, kg, km, etc.)
  Emission Factor = CO₂ eq per unit of activity
  GWP = Global Warming Potential relative to CO₂
```

## Product Standard (ISO 14067 / PAS 2050)

### Product Life Cycle Stages

```
Upstream                Core                    Downstream
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│ Raw materials    │    │ Manufacturing    │    │ Distribution     │
│ Extraction       │───▶│ Processing       │───▶│ Retail           │
│ Processing       │    │ Assembly         │    │ Use phase        │
│ Transport        │    │ Packaging        │    │ Maintenance      │
│                  │    │                  │    │ End-of-life      │
└─────────────────┘    └─────────────────┘    └─────────────────┘
```

### Cradle-to-Gate vs. Cradle-to-Grave

| Approach | Includes | Use Case |
|----------|----------|----------|
| Cradle-to-gate | Raw materials → factory gate | B2B products, EPDs |
| Cradle-to-grave | Raw materials → disposal/recycling | Consumer products |
| Cradle-to-cradle | Raw materials → recycled materials | Circular economy |
| Gate-to-gate | Single facility operations | Internal benchmarking |

### Biogenic Carbon

**Rules:**
- CO₂ absorbed during growth: credit (negative emission)
- CO₂ released at end-of-life: debit (positive emission)
- If biomass is sustainably managed: net zero over rotation period
- If land use change occurs: include land use change emissions

**ISO 14067 approach:**
- Report biogenic carbon separately from fossil carbon
- Include in GWP if carbon is not sequestered long-term
- Use 100-year GWP time horizon as default

### Carbon Offset

**Quality criteria for offsets:**
1. **Real**: Emissions reduction actually occurred
2. **Additional**: Would not have happened without the offset project
3. **Permanent**: Reductions are not reversed
4. **Verified**: Third-party verification
5. **Quantified**: Measured and documented
6. **Unique**: Not double-counted

## Scope 3 Categories (15 categories)

| Category | Description | Often Significant For |
|----------|-------------|----------------------|
| 1 | Purchased goods and services | Manufacturing, construction |
| 2 | Capital goods | Infrastructure, equipment |
| 3 | Fuel- and energy-related activities | All sectors |
| 4 | Upstream transportation | Manufacturing, retail |
| 5 | Waste generated in operations | All sectors |
| 6 | Business travel | Services, consulting |
| 7 | Employee commuting | All sectors |
| 8 | Upstream leased assets | Real estate |
| 9 | Downstream transportation | Retail, distribution |
| 10 | Processing of sold products | Chemicals, materials |
| 11 | Use of sold products | Energy, automotive |
| 12 | End-of-life treatment of sold products | Consumer goods |
| 13 | Downstream leased assets | Real estate |
| 14 | Franchises | Retail, food service |
| 15 | Investments | Financial services |

## Emission Factors by Region

### Electricity Grid Emission Factors

| Region | Factor (kg CO₂/kWh) | Year | Source |
|--------|---------------------|------|--------|
| China (national) | 0.5810 | 2022 | China MEE |
| China (regional varies) | 0.3-0.9 | 2022 | China MEE |
| United States | 0.4171 | 2022 | EPA eGRID |
| European Union | 0.2760 | 2022 | EEA |
| India | 0.7080 | 2022 | CEA |
| Japan | 0.4681 | 2022 | IEA |
| Global average | 0.4750 | 2022 | IEA |

### Material Emission Factors

| Material | Factor (kg CO₂/kg) | Source |
|----------|---------------------|--------|
| Portland cement | 0.6176 | ecoinvent |
| Concrete (C30) | 0.1321 | ecoinvent |
| Steel (BOF, global) | 1.8540 | worldsteel |
| Steel (EAF) | 0.7210 | worldsteel |
| Aluminum (primary) | 10.580 | IAI |
| Aluminum (recycled) | 0.5120 | ecoinvent |
| Copper (primary) | 3.2100 | ecoinvent |
| PVC | 1.9200 | ecoinvent |
| HDPE | 1.7800 | ecoinvent |
| Glass | 0.8500 | ecoinvent |
| Timber (softwood) | -1.6400 | ecoinvent (biogenic) |
| Timber (hardwood) | -1.8300 | ecoinvent (biogenic) |

### Transport Emission Factors

| Mode | Factor (kg CO₂/t·km) | Source |
|------|----------------------|--------|
| Heavy truck (>32t) | 0.1008 | IPCC |
| Light truck (3.5-7.5t) | 0.2765 | IPCC |
| Rail (freight) | 0.0247 | IPCC |
| Ship (bulk carrier) | 0.0156 | IPCC |
| Ship (container) | 0.0283 | IPCC |
| Air (freight) | 1.1020 | IPCC |
| Pipeline | 0.0155 | IPCC |

## Reporting Requirements

### Minimum Disclosure

Per GHG Protocol, organizations must disclose:
- Scope 1 emissions by source category
- Scope 2 emissions (location-based and market-based)
- Scope 3 categories evaluated and their significance
- Base year and recalculation approach
- Emission factors and data sources
- Uncertainty assessment

### Product Carbon Footprint Disclosure

Per ISO 14067:
- Functional unit or declared unit
- System boundary
- Data sources and quality
- GWP results by life cycle stage
- Sensitivity analysis
- Exclusions and their justification
