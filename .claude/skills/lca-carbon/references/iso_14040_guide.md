# ISO 14040/14044 LCA Standard Guide

## Overview

ISO 14040 and ISO 14044 define the international standards for conducting Life Cycle Assessments. This guide provides detailed interpretation for engineering and environmental researchers.

## ISO 14040:2006 — Principles and Framework

### Four Phases of LCA

```
┌─────────────────────┐
│  Goal and Scope      │ ← Define purpose, functional unit, boundaries
│  Definition          │
└─────────┬───────────┘
          ▼
┌─────────────────────┐
│  Life Cycle          │ ← Data collection for all inputs/outputs
│  Inventory (LCI)     │
└─────────┬───────────┘
          ▼
┌─────────────────────┐
│  Life Cycle Impact   │ ← Convert inventory to environmental impacts
│  Assessment (LCIA)   │
└─────────┬───────────┘
          ▼
┌─────────────────────┐
│  Interpretation      │ ← Analyze results, sensitivity, conclusions
└─────────────────────┘
```

### Key Principles

1. **Life cycle perspective**: Consider all stages from cradle to grave
2. **Focus on significant issues**: Prioritize data collection on major contributors
3. **Transparency**: Document all assumptions, data sources, and methods
4. **Accuracy**: Results should be sufficiently accurate for decision-making
5. **Consistency**: Use consistent methods throughout the study
6. **Reproducibility**: Another practitioner should reach similar conclusions

## ISO 14044:2006 — Requirements and Guidelines

### Goal Definition Requirements

- Intended application and reasons for the study
- Intended audience
- Whether results will be used in comparative assertions (public disclosure)
- Commissioner and practitioner identity

### Scope Definition Requirements

#### Functional Unit
The functional unit quantifies the function of the product system. It must be:
- Clearly defined and measurable
- Appropriate for the decision context
- Consistent across compared systems

**Examples:**
| Product | Functional Unit |
|---------|----------------|
| Concrete | 1 m³ of C30/37 concrete with 50-year service life |
| Steel beam | 1 m of HEA 200 beam supporting 500 kN |
| Water treatment | 1 m³ of treated drinking water meeting WHO standards |
| Solar panel | 1 kWh of electricity generated over 25-year lifetime |
| Pavement | 1 km·lane of road with 20-year design life |

#### System Boundary
Must include all processes that are:
- Owned/controlled by the manufacturer
- Significant to the analysis (>1% of mass, energy, or environmental impact)
- Required for fair comparison

**Common boundaries:**
- **Cradle-to-gate**: Raw materials → factory gate (for B2B products)
- **Cradle-to-grave**: Raw materials → end of life (for consumer products)
- **Cradle-to-cradle**: Raw materials → recycling back to raw materials
- **Gate-to-gate**: Single process or factory operations only

#### Cut-off Criteria
- Mass: exclude flows <1% of total mass
- Energy: exclude flows <1% of total energy
- Environmental significance: include regardless of mass/energy if environmentally significant

#### Allocation
For multi-output processes, ISO 14044 prioritizes:
1. **Avoid allocation**: Subdivision or system expansion
2. **Physical relationships**: Mass, volume, energy content
3. **Economic allocation**: Based on economic value of co-products

### LCI Data Requirements

**Data quality indicators:**
- Time-related coverage (year of data)
- Geographic coverage (country/region)
- Technology coverage (specific technology)
- Precision (variance/uncertainty)
- Completeness (coverage of flows)
- Consistency (uniform methods)
- Reproducibility (independent verification)

**Data source hierarchy:**
1. Site-specific measured data (highest quality)
2. Same technology, different site
3. Same sector, same region
4. Same sector, different region
5. Literature data
6. LCI database (ecoinvent, GaBi)
7. Engineering estimates (lowest quality)

### LCIA Methods

**Problem-oriented (midpoint):**
- CML 2001 (Leiden University)
- ReCiPe 2016 (RIVM)
- TRACI 2.1 (US EPA)
- IMPACT 2002+ (EPFL)

**Damage-oriented (endpoint):**
- ReCiPe Endpoint (human health, ecosystems, resources)
- Eco-indicator 99
- IMPACT 2002+

**Midpoint vs. Endpoint:**
- Midpoint: More certain, more specific, less subjective
- Endpoint: More uncertain, more aggregated, easier to understand
- Recommendation: Report midpoint results; use endpoint only for communication

### Critical Review

**Required for:**
- Comparative assertions disclosed to the public
- Studies used for public policy decisions
- Studies following ISO 14044

**Review panel requirements:**
- Minimum 3 qualified reviewers
- At least 1 external expert
- At least 1 stakeholder representative
- Review report must be included in documentation

## Common Impact Assessment Methods

### ReCiPe 2016 (Recommended for Engineering)

**18 Midpoint indicators:**
1. Climate change (kg CO₂ eq)
2. Ozone depletion (kg CFC-11 eq)
3. Terrestrial acidification (kg SO₂ eq)
4. Freshwater eutrophication (kg P eq)
5. Marine eutrophication (kg N eq)
6. Human carcinogenic toxicity (kg 1,4-DCB eq)
7. Human non-carcinogenic toxicity (kg 1,4-DCB eq)
8. Terrestrial ecotoxicity (kg 1,4-DCB eq)
9. Freshwater ecotoxicity (kg 1,4-DCB eq)
10. Marine ecotoxicity (kg 1,4-DCB eq)
11. Land use (m²·year crop eq)
12. Mineral resource scarcity (kg Cu eq)
13. Fossil resource scarcity (kg oil eq)
14. Water consumption (m³)

### Global Warming Potential Time Horizons

| Time Horizon | CO₂ | CH₄ | N₂O | SF₆ |
|-------------|-----|-----|-----|-----|
| GWP-20 | 1 | 80.8 | 264 | 17,500 |
| GWP-100 | 1 | 29.8 | 273 | 25,200 |
| GWP-500 | 1 | 7.89 | 153 | 32,400 |

Source: IPCC AR6 (2021)

## Reporting Checklist

Per ISO 14044, the report must include:

- [ ] Goal and scope clearly defined
- [ ] Functional unit specified
- [ ] System boundary described and justified
- [ ] Cut-off criteria stated
- [ ] Allocation procedures documented
- [ ] LCIA method and categories listed
- [ ] Data sources identified and quality assessed
- [ ] Assumptions and limitations documented
- [ ] Sensitivity analysis performed
- [ ] Results interpreted with limitations
- [ ] Critical review (if required)
