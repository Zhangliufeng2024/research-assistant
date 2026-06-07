# Scientific Diagram Types Catalog

This document catalogs all supported diagram types with examples for each domain.

## Biomedical / Clinical

### CONSORT Flowchart
```
"CONSORT participant flow diagram: Assessed (n=500) → Excluded (n=150) → Randomized (n=350) → Treatment (n=175) vs Control (n=175) → Analyzed (n=160 vs n=165)"
```

### PRISMA Flow Diagram
```
"PRISMA flow diagram: Identification (n=1200 from databases, n=50 from other) → Screening (n=1250) → Eligibility (n=300) → Included (n=85). Show exclusion reasons at each stage."
```

### Biological Pathway
```
"MAPK signaling cascade: EGFR (membrane) → Grb2 → SOS → RAS-GTP → RAF → MEK → ERK → nucleus (gene transcription). Phosphorylation steps labeled."
```

### Clinical Decision Tree
```
"Decision tree for diabetic patient management: HbA1c test → if <7% continue monitoring, if 7-9% add oral agent, if >9% start insulin. Each branch shows follow-up actions."
```

### Molecular Structure
```
"Protein structure diagram showing alpha-helices (red), beta-sheets (blue), loops (gray), with active site highlighted in yellow. Include binding pocket detail."
```

## Civil / Structural Engineering

### Structural Analysis Diagram
```
"Simply supported beam (span 6m) with distributed load (10 kN/m) and point load (50 kN at midspan). Show bending moment diagram below, shear force diagram below that. Label max moment (M=112.5 kN·m at center) and reactions (R1=R2=55 kN)."
```

### Load Path Diagram
```
"Load path in a steel frame building: Roof loads → purlins → rafters → columns → foundations → soil. Show lateral load path through bracing. Use arrows to indicate force flow direction."
```

### Cross-Section Diagram
```
"Reinforced concrete beam cross-section: 300mm width × 600mm depth, 3 layers of tensile reinforcement (4×25mm bars), 2×16mm compression bars, 10mm stirrups at 150mm spacing. Show cover 40mm."
```

### FEA Mesh Visualization
```
"Finite element mesh of a bridge pier: Show refined mesh near the base (element size 25mm), coarser mesh at top (element size 100mm). Highlight boundary conditions (fixed at base, free at top). Color-code stress distribution from blue (low) to red (high)."
```

### Moment-Curvature Diagram
```
"Moment-curvature relationship for RC section: Show elastic range (linear), cracking point (drop), yielding plateau, and ultimate point. Label key values: cracking moment (Mcr=45 kN·m), yield moment (My=180 kN·m), ultimate moment (Mu=220 kN·m)."
```

### Seismic Response Spectrum
```
"Design response spectrum per ASCE 7-22: Show acceleration vs period curve with short period plateau (SDS=1.0g), transition zone (TS=0.5s), and long period descending branch. Mark building periods T1=0.8s, T2=0.25s."
```

### Foundation Diagram
```
"Spread foundation design: Show column load (P=2000 kN), footing dimensions (2m×2m×0.5m), soil bearing pressure distribution (uniform 500 kPa), reinforcement layout, and embedment depth (1m below grade)."
```

### Retaining Wall
```
"Gravity retaining wall with soil pressure: Show wall dimensions, active earth pressure triangle (Pa), passive pressure at toe, water table level, drainage system, and factor of safety sliding (FS=1.5) and overturning (FS=2.0)."
```

## Environmental Engineering

### Water Treatment Process Flow
```
"Water treatment plant process flow: Raw water intake → Coagulation (alum dosing) → Flocculation → Sedimentation → Sand filtration → Activated carbon → Disinfection (chlorine) → Storage → Distribution. Show flow rates and removal efficiencies at each stage."
```

### Wastewater Treatment Plant
```
"WWTP layout: Inlet → Bar screen → Grit chamber → Primary clarifier → Activated sludge (aeration tank) → Secondary clarifier → Tertiary filtration → UV disinfection → Effluent. Sludge line: Primary + Secondary sludge → Thickener → Anaerobic digester → Dewatering → Disposal."
```

### Carbon Cycle Diagram
```
"Building carbon lifecycle: Embodied carbon (materials + construction) → Operational carbon (energy use over 50 years) → Maintenance carbon → End-of-life carbon. Show carbon payback period and net-zero timeline."
```

### LCA System Boundary
```
"LCA system boundary diagram: Cradle-to-grave showing Raw material extraction → Transportation → Manufacturing → Transportation → Construction → Use phase (50 years) → Demolition → End-of-life (recycling 60%, landfill 40%). System boundary box enclosing all stages."
```

### Contaminant Plume
```
"Groundwater contaminant plume: Show source zone (DNAPL), dissolved phase plume extending downgradient, monitoring wells (MW-1 through MW-5), capture zone of extraction wells, and contaminant concentrations at each well."
```

### Constructed Wetland
```
"Horizontal subsurface flow constructed wetland: Inlet distribution zone → Gravel bed with Phragmites plants → Liner → Collection pipes → Outlet. Show water level, flow path, and treatment zones. Include cross-section showing substrate layers."
```

## Computer Science / Machine Learning

### Neural Network Architecture
```
"Transformer architecture: Encoder stack (6 layers) with multi-head self-attention + feed-forward. Decoder stack (6 layers) with masked self-attention + cross-attention + feed-forward. Show positional encoding, layer norm, residual connections."
```

### CNN Architecture
```
"ResNet-50 architecture: Input (224×224×3) → Conv1 → MaxPool → 4 residual blocks (3,4,6,3 layers) → GlobalAvgPool → FC → Softmax. Show skip connections in each block."
```

### System Architecture
```
"Distributed microservices architecture: API Gateway → Auth Service, User Service, Order Service, Payment Service. Each service connects to its own database. Message queue (Kafka) between services. Show load balancer and monitoring."
```

### Algorithm Flowchart
```
"Dijkstra's algorithm flowchart: Initialize distances → Add source to priority queue → While queue not empty: extract min vertex, relax edges, update distances. Show decision nodes for distance comparison."
```

### Data Pipeline
```
"ML training pipeline: Data collection → Preprocessing (cleaning, normalization) → Feature engineering → Train/val/test split → Model training (hyperparameter tuning) → Evaluation → Deployment → Monitoring."
```

### GAN Architecture
``"
"GAN architecture: Generator network (noise → fake image) and Discriminator network (image → real/fake). Show training loop with alternating optimization. Loss functions labeled."
```

### UML Class Diagram
```
"UML class diagram for design pattern: Show AbstractFactory (abstract class) with ConcreteFactoryA and ConcreteFactoryB implementing it. Products created by each factory. Include associations and dependencies."
```

## Interdisciplinary (AI + Engineering)

### Digital Twin Architecture
```
"Digital twin for bridge monitoring: Physical bridge → Sensors (strain, accelerometers, GPS) → Data acquisition → Cloud platform → Physics-based model + ML model → Predictions → Dashboard. Show feedback loop for model updating."
```

### SHM System Diagram
```
"Structural health monitoring system: Sensors (accelerometers, strain gauges, temperature) → DAQ → Edge computing (feature extraction) → Cloud (ML damage detection) → Alert system → Maintenance scheduling. Show data flow and processing at each stage."
```

### Smart Building System
```
"Smart building IoT architecture: Sensors (occupancy, temperature, light) → BMS → HVAC control, lighting control, energy optimization. Show AI agent for predictive control. Include grid interaction and renewable energy integration."
```

### FEA + ML Hybrid
```
"Hybrid FEA-ML workflow: Experimental data → FEA model calibration → FEA simulations (parametric study) → ML surrogate model training → Real-time prediction. Show validation loop comparing ML predictions with FEA."
```

## Chemistry / Materials

### Reaction Mechanism
```
"Catalytic reaction mechanism: Substrate + Catalyst → Intermediate 1 → Intermediate 2 → Product + Catalyst. Show energy diagram with activation energies and transition states."
```

### Phase Diagram
```
"Binary phase diagram: Temperature vs composition showing liquidus, solidus, solvus lines. Mark eutectic point, solid solution regions, and two-phase regions. Include tie lines."
```

### Crystal Structure
```
"Unit cell of perovskite (ABO3): Show A-site cation (12-coordinate), B-site cation (6-coordinate), oxygen anions. Include lattice parameters a=b=c≈4Å."
```

## Engineering Data Visualization Types

### Hysteretic Curves (Load-Displacement Loops)
**Description**: Cyclic load vs. displacement response showing pinching, stiffness degradation, strength degradation, and energy dissipation.
**When to use**: Seismic performance evaluation of beams, columns, connections, walls, bracing.
**Key annotations**: Yield point (Δy, Py), peak (Δmax, Pmax), ultimate (Δu, Pu), backbone curve, cumulative energy dissipation, secant stiffness degradation.
**Example prompt**: "Hysteretic curves for a BRB specimen: X-axis drift ratio -3% to +3%, Y-axis force -2000 to +2000 kN. Symmetric loops with excellent energy dissipation. Mark yield at ±0.5% drift (±800 kN), peak at ±2% (±1600 kN). Backbone curve overlay in dashed red. Cumulative energy 450 kN·m at 2%."

### Backbone/Envelope Curves
**Description**: Envelope connecting peak load-displacement points from each cycle.
**When to use**: Comparing cyclic vs. monotonic, defining ductility μ = Δu/Δy.
**Key annotations**: Yield, peak, ultimate points, ductility ratio, post-peak softening, monotonic comparison.
**Example prompt**: "Backbone curves comparing two RC columns: Specimen 1 yield at 15mm/400kN peak 45mm/520kN; Specimen 2 (retrofitted) yield 15mm/450kN peak 60mm/680kN. Ductility improvement 5.0→6.7."

### S-N Fatigue Curves
**Description**: Stress amplitude vs. cycles to failure on log-log scale.
**When to use**: Fatigue assessment of steel connections, bridge components, offshore structures.
**Key annotations**: Stress range Δσ (MPa), cycles N, stress ratios (R=-1,0,0.1,0.5), Eurocode 3/AISC design categories, endurance limit, scatter band.
**Example prompt**: "S-N curve for welded connections: log-log X-axis 10^3-10^7 cycles, Y-axis Δσ 50-500 MPa. Data scatter with Eurocode 3 Cat 71 design line. Endurance limit at 5×10^6 cycles. Paris law slope m=3."

### Breakthrough Curves
**Description**: Effluent concentration C/C0 vs. time or bed volumes for fixed-bed adsorption.
**When to use**: Column studies for adsorption, ion exchange, activated carbon, biochar.
**Key annotations**: Breakthrough (C/C0=0.05-0.1), exhaustion (C/C0=0.95), S-shaped sigmoid, Thomas/BDST model overlay, multiple bed depths.
**Example prompt**: "Breakthrough curves for Pb(II) on biochar at 5/10/15 cm bed depths, flow 5 mL/min, C0=50 mg/L. S-shaped curves, earlier breakthrough for shorter bed. Thomas model fit (dashed)."

### Isotherm Plots
**Description**: Equilibrium adsorption capacity qe vs. equilibrium concentration Ce.
**When to use**: Batch adsorption studies for any adsorbent-adsorbate system.
**Key annotations**: Langmuir fit (plateau, monolayer), Freundlich fit (no plateau), qmax, data with error bars, R² values.
**Example prompt**: "Isotherm for Cu(II) on modified biochar: X-axis Ce 0-200 mg/L, Y-axis qe 0-80 mg/g. Triplicate data with error bars. Langmuir qmax=65 mg/g (R²=0.98, solid red), Freundlich KF=8.5 (R²=0.94, dashed blue)."

### Response Spectra
**Description**: Spectral acceleration Sa vs. period T showing seismic demand.
**When to use**: Seismic design, ground motion selection, dynamic analysis.
**Key annotations**: Design spectrum (ASCE 7-22/EC8), MCE spectrum (1.5x), 5% damping, Ts, T0, TL, fundamental period T1.
**Example prompt**: "Design response spectrum Site Class D, SDC D (ASCE 7-22): X-axis T 0-4s, Y-axis Sa 0-1.5g. Sds=1.0g, Sd1=0.6g, Ts=0.6s. MCE in dashed red. T1=0.8s marked."

### IDA Curves
**Description**: IM vs. EDP showing structural response across seismic intensity levels.
**When to use**: Collapse assessment, fragility analysis, performance-based earthquake engineering.
**Key annotations**: Sa(T1) vs. max drift, multiple records (cloud), 16th/50th/84th percentiles, collapse plateau, performance levels (IO, LS, CP).
**Example prompt**: "IDA for 6-story steel frame (20 motions): X-axis drift 0-10%, Y-axis Sa 0-2g. Gray cloud of individual curves. Bold 50th percentile, dashed 16th/84th. IO at 0.7%, LS at 2.5%, CP at 5%."

### Moment-Curvature Diagrams
**Description**: Bending moment vs. curvature for cross-sections.
**When to use**: RC beam/column section analysis, fiber modeling.
**Key annotations**: Cracking (Mcr, φcr), yielding (My, φy), ultimate (Mu, φu), tension stiffening, experimental vs. fiber analysis.
**Example prompt**: "M-φ for 300×500mm RC column (P=500kN): X-axis φ 0-0.08/m, Y-axis M 0-600 kN·m. Trilinear: Mcr=120, My=420, Mu=480. Fiber analysis (solid) vs. experimental (dashed)."

### Load Path Diagrams
**Description**: Force flow through structural system from load to foundation.
**When to use**: Concept design, load transfer explanation, teaching.
**Key annotations**: Force flow arrows (thickness ∝ magnitude), load transfer mechanisms, reactions, connection details.
**Example prompt**: "Load path for steel portal frame: UDL on rafters → knee connections → columns → foundations. Arrow thickness proportional to force. Blue=compression, red=tension, green=bending."

### Cross-Section Details
**Description**: Detailed cross-section with reinforcement, dimensions, materials.
**When to use**: RC beam/column/wall design, steel section design.
**Key annotations**: Dimensions b×h, bar layout (number, diameter, spacing), stirrups, cover, material grades, section properties.
**Example prompt**: "RC beam section: 300×500mm, cover 25mm. Tension: 4-25mm bars in 2 layers. Compression: 2-16mm. Stirrups: 10mm @ 150mm c/c 3-legged. C30/37, Grade 500. Label all dimensions."

## Tips for Effective Diagram Prompts

### Include These Elements
1. **Type**: What kind of diagram (flowchart, architecture, cross-section, etc.)
2. **Components**: Specific elements to include with labels
3. **Relationships**: How elements connect (arrows, lines, hierarchy)
4. **Quantities**: Numbers, dimensions, values where applicable
5. **Direction**: Flow direction (top-to-bottom, left-to-right, clockwise)
6. **Colors**: Specific color coding or style requirements
7. **Labels**: Key text annotations

### Example of a Comprehensive Prompt
```
"Structural analysis diagram of a 3-span continuous beam:
- Spans: 4m, 6m, 4m
- Loads: UDL 15 kN/m on all spans, point load 100kN at midspan of center span
- Show: Bending moment diagram below (label max sagging 180 kN·m, max hogging 120 kN·m)
- Show: Shear force diagram below that
- Use blue for beam, red for tension, green for compression
- Include reaction values at supports"
```
