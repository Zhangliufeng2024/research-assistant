# Engineering Experiment Methods: Comprehensive Guide

This guide covers experimental methods specific to civil, structural, and environmental engineering research.

**Last Updated**: 2026

---

## Structural Testing Methods

### Quasi-Static Cyclic Testing

**Purpose**: Evaluate seismic performance of structural components and connections under simulated earthquake loading.

**Key Protocol Elements**:
- **Loading history**: ACI 374.1 (acceptance criteria), FEMA 461 (loading protocol), or ATC-24 (guidelines)
- **Displacement-controlled**: Typically preferred for post-yield behavior
- **Loading pattern**: Monotonic, cyclic (constant amplitude), or incremental cyclic
- **Specimen design**: Scale effects (1/2, 1/3, full-scale), boundary conditions, similitude requirements

**Instrumentation Plan**:
- Load cells: Capacity ≥ 1.5x expected peak load
- LVDTs: ±50mm to ±250mm typical range, resolution 0.01mm
- String pots: For large displacements (±500mm+)
- Strain gauges: 350Ω typical, gauge length 5-60mm
- DIC (Digital Image Correlation): Full-field strain, requires speckle pattern (dot size 3-5 pixels)
- Fiber optic sensors (FBG): For distributed strain, embedded in concrete

**Data Acquisition**:
- Sampling rate: 1-10 Hz for quasi-static (100+ Hz for dynamic events)
- Resolution: 16-bit minimum, 24-bit preferred
- Anti-aliasing filter: Required for dynamic testing

**Reporting Requirements**:
- Hysteretic loops (load vs. displacement)
- Backbone/envelope curve
- Stiffness degradation (secant stiffness per cycle)
- Strength degradation (peak load per cycle)
- Energy dissipation per cycle and cumulative
- Ductility ratio (Δu/Δy) with yield displacement definition
- Failure mode classification (flexural, shear, anchorage, etc.)

### Shake Table Testing

**Purpose**: Evaluate dynamic/seismic performance of structures at realistic loading rates.

**Key Parameters**:
- Table capacity: Payload (tonnes), peak acceleration (g), velocity (m/s), displacement (mm)
- Degrees of freedom: 1-DOF to 6-DOF
- Actuator bandwidth: Typically 0.1-100 Hz

**Ground Motion Selection**:
- Site-specific hazard analysis (PSHA) or code-based spectra
- Recorded motions: PEER NGA-West2, COSMOS, ESMD databases
- Spectral matching: Wavelet adjustment to target spectrum
- Number of records: Minimum 3 (7-11 recommended per ASCE 7-22)
- Scaling methods: IM-based (Sa(T1)), MSA (multiple stripe analysis)

**Instrumentation**:
- Accelerometers: ±2g to ±10g range, piezoelectric or MEMS
- Displacement transducers: Table motion verification
- Strain gauges: On critical sections
- Laser vibrometers: Non-contact velocity measurement

**Scaling Laws (Similitude)**:
- Length scale: λL = Lprototype/Lmodel
- Time scale: λT = √λL (for gravity-dominated)
- Mass scale: λM = λρ × λL³
- Stress scale: λσ = λρ × λL

**Reporting Standards**:
- Input vs. measured table motion comparison
- Transfer function verification
- Floor response spectra
- Inter-story drift ratios
- Peak floor accelerations
- Damage states observed vs. predicted

### Pseudodynamic (PsD) Testing

**Purpose**: Combine computational mass matrix with experimental restoring force for large-scale seismic testing.

**Key Features**:
- Real-time or slow-rate integration of equations of motion
- Substructuring: Test critical component, simulate remainder computationally
- Integration algorithms: Newmark-α, HHT-α, CR (Chang)
- Convergence issues: Numerical damping, energy balance

### Hybrid Simulation

**Purpose**: Combine physical test with computational substructure in real-time or pseudo-real-time.

**Components**:
- Physical substructure: Tested in laboratory
- Computational substructure: Analyzed in OpenSees, ABAQUS, or similar
- Coordinator: Manages interface (displacements, forces)
- Communication: Latency < 1ms for real-time

### Large-Scale Structural Testing

**Considerations**:
- Specimen fabrication: Mock-up construction quality control
- Boundary conditions: Realistic fixity, load introduction
- Loading equipment: Hydraulic actuators (100kN to 10,000kN+), servo-controlled
- Safety: Structural redundancy, load limiting, emergency stops
- Data management: High-channel-count DAQ (100+ channels)

---

## Geotechnical Testing Methods

### Laboratory Testing

**Soil Classification**:
- Atterberg limits: ASTM D4318
- Grain size distribution: ASTM D6913 (sieve), D7928 (hydrometer)
- Specific gravity: ASTM D854

**Strength Testing**:
- Unconfined compression: ASTM D2166
- Triaxial (CU/UU/CD): ASTM D2850, D4767
- Direct shear: ASTM D3080
- Consolidation: ASTM D2435

**Permeability**:
- Constant head: ASTM D2434 (coarse-grained)
- Falling head: ASTM D5084 (fine-grained)

### Field Testing

**Standard Penetration Test (SPT)**: ASTM D1586
- N-value correlation to φ', Dr, qu
- Energy correction (ER/60%)

**Cone Penetration Test (CPT/CPTu)**: ASTM D5778
- Tip resistance (qc), sleeve friction (fs), pore pressure (u2)
- Soil behavior type (SBT) classification (Robertson 1990)
- Correlations to strength, stiffness, liquefaction

**Pressuremeter (PMT)**: ASTM D4719
- Limit pressure (pL), creep pressure (pf)
- In-situ stress-strain modulus

**Vane Shear Test**: ASTM D2573
- Undrained shear strength (su) in soft clays
- Correction factors (μ) for plasticity

### Centrifuge Modeling

**Purpose**: Simulate prototype stress conditions in scaled models.

**Scaling Laws**:
- Length scale: N (typically 50-200g)
- Stress: 1:1 (same as prototype)
- Time: 1/N (dynamic), 1/N² (consolidation)
- Frequency: N times prototype

**Applications**:
- Foundation behavior (shallow and deep)
- Slope stability
- Earthquake-induced liquefaction
- Retaining wall performance
- Tunnel construction effects

---

## Material Testing Methods

### Concrete

**Compressive Strength**: ASTM C39/C39M
- Cylinder: 150×300mm (standard) or 100×200mm
- Loading rate: 0.15-0.35 MPa/s
- Reporting: Average of 2-3 specimens, age (7, 14, 28 days)

**Tensile Strength**:
- Splitting: ASTM C496
- Flexural: ASTM C78 (third-point loading)

**Elastic Modulus**: ASTM C469
- Secant modulus at 40% of f'c

**Durability**:
- Chloride penetration: ASTM C1556 (bulk diffusion), C1202 (rapid chloride permeability)
- Carbonation: EN 13295 (depth of carbonation)
- Freeze-thaw: ASTM C666

### Steel

**Tensile Testing**: ASTM E8/E8M
- Yield strength (0.2% offset), ultimate strength, elongation
- Coupon location: Flange, web, per ASTM A370

**Charpy V-Notch**: ASTM E23
- Transition temperature curve
- Lateral expansion, shear fracture percentage

**Fatigue Testing**: ASTM E466
- S-N curves (stress amplitude vs. cycles)
- Endurance limit definition
- Paris law parameters (da/dN vs. ΔK)

**High-Strain Rate Testing**:
- Split Hopkinson pressure bar (SHPB)
- Strain rates: 10² to 10⁴ /s

### FRP Composites

**Tensile**: ASTM D3039
**Compression**: ASTM D6641
**Interlaminar Shear**: ASTM D2344
**Flexural**: ASTM D7264

---

## Environmental Engineering Experiments

### Batch Adsorption Studies

**Isotherm Studies**:
- Langmuir: qe = qmax KL Ce / (1 + KL Ce)
- Freundlich: qe = KF Ce^(1/n)
- BET: Multi-layer adsorption
- D-R (Dubinin-Radushkevich): Mean free energy
- Minimum 5 concentrations, triplicate, equilibrium time determination

**Kinetic Studies**:
- Pseudo-first-order (Lagergren): qt = qe(1 - e^(-k1t))
- Pseudo-second-order (Ho): qt = k2 qe² t / (1 + k2 qe t)
- Intraparticle diffusion (Weber-Morris): qt = ki t^(1/2) + C
- Film diffusion: Boyd model
- Minimum 8 time points, covers equilibrium

**Thermodynamic Studies**:
- Van't Hoff: ln(Kd) = -ΔH°/RT + ΔS°/R
- Parameters: ΔG°, ΔH°, ΔS°
- Temperature range: 3-5 temperatures (e.g., 15, 25, 35, 45°C)

### Column Studies (Fixed-Bed Adsorption)

**Experimental Setup**:
- Column: Glass/acrylic, ID 1-5 cm, L/D > 10
- Packing: Adsorbent particle size, bed height, flow rate
- Influent concentration, pH, temperature

**Breakthrough Analysis**:
- Breakthrough curve: C/C0 vs. time or bed volumes
- Breakthrough time (tb): C/C0 = 0.05 or 0.1
- Exhaustion time (te): C/C0 = 0.95
- Bed depth service time (BDST) model
- Thomas model: ln(C0/C - 1) = kTH q0 m / Q - kTH C0 t
- Yoon-Nelson model
- Adams-Bohart model

### Membrane Separation

**Key Parameters**:
- Flux (J): L/(m²·h) or LMH
- Rejection (R): (1 - Cp/Cf) × 100%
- Molecular weight cut-off (MWCO)
- Transmembrane pressure (TMP)
- Recovery rate
- Fouling: Flux decline ratio, resistance-in-series model

**Standard Tests**:
- ASTM D4516: Standard practice for standardizing reverse osmosis performance
- ASTM D4194: RO characteristics

### Biological Treatment

**Activated Sludge**:
- SRT (solids retention time): 5-20 days typical
- HRT (hydraulic retention time): 4-8 hours typical
- F/M ratio: 0.2-0.6 kg BOD/kg MLSS·d
- MLSS/MLVSS: 2,000-4,000 mg/L typical
- SVI (sludge volume index): < 150 mL/g (good settling)

**Anaerobic Treatment**:
- UASB: Organic loading rate (OLR), upflow velocity
- Anaerobic digestion: Biogas composition (CH4, CO2, H2S), volatile solids reduction

**Respirometry**:
- OUR (oxygen uptake rate)
- SOUR (specific oxygen uptake rate)
- BOD kinetics (BODu, k1)

---

## Instrumentation and Data Acquisition

### Sensor Types

| Sensor | Measurand | Range | Resolution | Application |
|--------|----------|-------|------------|-------------|
| LVDT | Displacement | ±1-250mm | 0.001mm | Structural deformation |
| String pot | Displacement | ±50-1500mm | 0.1mm | Large displacements |
| Load cell | Force | 1-10,000kN | 0.1% FS | Load measurement |
| Strain gauge | Strain | ±50,000 με | 1 με | Local strain |
| Accelerometer | Acceleration | ±2-200g | 0.001g | Dynamic response |
| Fiber optic (FBG) | Strain/Temp | ±5,000 με | 1 με | Distributed sensing |
| DIC | Full-field strain | 0.01-100% | 0.001% | Surface strain mapping |
| Thermocouple | Temperature | -200-1,200°C | 0.1°C | Temperature monitoring |
| Piezometer | Pore pressure | 0-1,000 kPa | 0.1 kPa | Geotechnical |
| Inclinometer | Tilt | ±30° | 0.001° | Deformation monitoring |

### Digital Image Correlation (DIC)

**Setup**:
- Camera: Resolution ≥ 5 MP, frame rate ≥ 1 Hz (quasi-static)
- Speckle pattern: Random dots, 3-5 pixels per dot
- Calibration: Certified calibration target
- Software: VIC-2D/3D, GOM Correlate, Ncorr (open source)
- Subset size: 21-41 pixels, step size 5-7 pixels

**Reporting**:
- Full-field strain maps (εxx, εyy, γxy)
- Displacement fields
- Strain localization identification
- Crack width measurement
- Validation against point sensors (LVDT, strain gauges)

### Data Acquisition Systems

**Commercial Systems**:
- National Instruments (NI cDAQ, PXI)
- HBM (QuantumX, Spider8)
- Campbell Scientific (CR1000X, CR6)
- Vishay (System 7000, P3)

**Key Specifications**:
- Channel count: 8-256+ channels
- Sampling rate: 1 Hz to 200 kS/s per channel
- Resolution: 16-bit or 24-bit
- Input types: Voltage, strain, thermocouple, IEPE, LVDT excitation
- Synchronization: GPS, IRIG-B, PTP (IEEE 1588)

---

## Data Presentation for Engineering Papers

### Load-Displacement Curves

**Types**:
- Monotonic: Load vs. displacement envelope
- Cyclic/Hysteretic: Load vs. displacement loops (pinching, degradation)
- Backbone/Envelope: Peak points from each cycle
- Normalized: By yield/base values

**Figure Requirements**:
- Axes: Load (kN) or moment (kN·m) vs. displacement (mm) or drift (%)
- Grid lines: Recommended for reading values
- Legend: Loading direction (push/pull), cycle number if relevant
- Annotations: Yield point, peak, ultimate, failure mode

### S-N Curves (Fatigue)

**Format**:
- Log-log scale: log(N) vs. log(S) or log(Δσ)
- Multiple stress ratios (R = -1, 0, 0.1, 0.5)
- Scatter band representation
- Design curves: Eurocode 3 detail categories, AISC fatigue categories

### Seismic Data Presentation

**Response Spectra**:
- 5% damped elastic response spectrum
- Design spectrum comparison (ASCE 7-22, Eurocode 8)
- Period markers: T1, T2 (higher modes)

**Incremental Dynamic Analysis (IDA)**:
- IM vs. EDP (Sa(T1) vs. max drift)
- Multiple records: Cloud of points
- 16th/50th/84th percentile curves

**Hysteretic Energy**:
- Cumulative energy dissipation vs. cycles
- Energy ratio (Eh/Ep) for equivalent viscous damping

### Environmental Engineering Data

**Isotherm Plots**:
- qe (mg/g) vs. Ce (mg/L)
- Linearized form comparison (R² values)
- Model parameters table

**Breakthrough Curves**:
- C/C0 vs. time (hours) or bed volumes (BV)
- Multiple flow rates or bed depths on same plot
- Model fit overlay

**Water Quality Profiles**:
- Concentration vs. distance/time
- Regulatory limit lines (WHO, EPA MCLs)
- Detection limit markers

---

## See Also

- `research_methods.md` - General experimental methods
- `diagram_types.md` - Schematic and figure types
- `engineering_journal_styles.md` - Venue-specific requirements
- `civil_design_codes.md` - Design code references
