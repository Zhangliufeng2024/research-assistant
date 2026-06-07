# Research Methods and Approach Writing Guide

## Overview

The Research Approach and Methods section is the technical core of any grant proposal. It must convince reviewers that the proposed work is feasible, rigorous, and will produce meaningful results. This guide covers methods writing strategies across disciplines.

## General Principles

### Structure Your Methods Section

1. **Restate each Specific Aim** as a heading
2. **Describe the approach** for each aim in detail
3. **Include alternative strategies** for high-risk aims
4. **Address potential pitfalls** and mitigation plans
5. **Provide a timeline** connecting aims to milestones

### Writing Strategies

- **Be specific**: "We will test 30 specimens (15 control, 15 treatment)" not "We will test several specimens"
- **Justify choices**: Explain why this method is superior to alternatives
- **Show feasibility**: Reference preliminary data or published protocols
- **Address rigor**: Describe blinding, randomization, replication, and statistical power
- **Include alternatives**: For each aim, describe what you will do if the primary approach fails

## Methods by Research Type

### Experimental Research

#### Engineering Experimental Studies

**Structural Testing**:
- Specimen design and fabrication procedures
- Material characterization (concrete cylinder tests, steel coupon tests)
- Loading protocol (monotonic, cyclic, quasi-static, dynamic)
- Instrumentation plan (strain gauges, LVDTs, accelerometers, DIC)
- Data acquisition system specifications
- Failure mode identification criteria

**Geotechnical Testing**:
- Soil sampling and preparation methods
- Consolidation, shear strength, and permeability tests
- Field testing (SPT, CPT, pressuremeter)
- Model scale and boundary effects discussion

**Environmental Engineering Experiments**:
- Reactor design and operating conditions
- Sampling frequency and analytical methods
- QA/QC procedures (blanks, duplicates, spikes)
- Detection limits and quantification methods

**Materials Testing**:
- Mix design or material composition
- Curing conditions and age of testing
- Test standards followed (ASTM, EN, IS)
- Number of replicates per condition

#### Biomedical/Clinical Studies

- Study population: inclusion/exclusion criteria, sample size justification
- Randomization and blinding procedures
- Intervention protocol with dosing/timing
- Primary and secondary outcome measures
- Data collection schedule
- Safety monitoring plan

### Computational Research

#### Finite Element Analysis (FEA)

- Software and version (e.g., ABAQUS 2024, ANSYS 2024 R1)
- Element type and mesh refinement strategy
- Mesh convergence study results
- Material constitutive models (elastic, plastic, damage)
- Boundary conditions and loading protocol
- Contact definitions and interaction properties
- Solution procedure (static, dynamic, explicit, implicit)
- Validation against experimental data or analytical solutions

#### Computational Fluid Dynamics (CFD)

- Solver and turbulence model selection
- Mesh independence study
- Boundary condition specifications
- Time step sensitivity analysis
- Validation against benchmark cases

#### Machine Learning / AI

- Dataset description (size, source, preprocessing)
- Model architecture with justification
- Hyperparameter ranges and selection method
- Training procedure (optimizer, learning rate, batch size, epochs)
- Evaluation metrics and cross-validation strategy
- Baseline comparisons with equal tuning budget
- Compute resources (GPU type, training time)
- Random seeds and reproducibility measures

#### Algorithm Design

- Problem formalization with mathematical notation
- Algorithm pseudocode
- Time and space complexity analysis
- Correctness proof or argument
- Implementation details (language, libraries)
- Benchmark datasets and baselines

### Field Studies

- Study site description and selection criteria
- Sampling design (spatial, temporal)
- Equipment calibration and maintenance
- Environmental conditions during data collection
- Permit and regulatory compliance
- Data quality assurance procedures

## Agency-Specific Methods Writing

### NSF Methods Requirements

- **Intellectual Merit**: Methods must demonstrate rigor and innovation
- **Broader Impacts**: Include training plan for students in methods
- **Data Management Plan**: Describe data collection, storage, and sharing
- **Required Sections**: Describe methods under each Specific Aim

### NIH Methods Requirements

- **Rigor and Reproducibility**: Address biological variables (sex, age, ethnicity)
- **Authentication of Key Resources**: Cell lines, antibodies, animal models
- **Statistical Analysis Plan**: Power analysis, effect size, analysis pipeline
- **Timeline**: Year-by-year approach for each Aim

### DOE Methods Requirements

- **TRL Advancement**: Show how methods move technology from current to target TRL
- **National Lab Integration**: Describe collaboration and facility use
- **Cost Sharing**: If applicable, describe in-kind contributions
- **Technology Transfer**: Path from research to deployment

### DARPA Methods Requirements

- **Metrics-Driven**: Define quantitative go/no-go metrics for each task
- **Phase Structure**: Methods for Phase 1 (feasibility), Phase 2 (development), Phase 3 (demonstration)
- **Risk Mitigation**: Technical risk matrix with mitigation strategies
- **Transition Plan**: How methods/technology will transition to DoD or commercial use

## Describing Methods for Non-Specialist Reviewers

### Strategies for Cross-Disciplinary Review

1. **Define technical terms** on first use
2. **Use analogies** to explain complex concepts
3. **Include figures** showing experimental setup or computational workflow
4. **Provide context** for methodological choices ("This method is the gold standard because...")
5. **Reference widely-known protocols** when possible
6. **Avoid jargon** without explanation

### Common Methods Writing Mistakes

1. **Too vague**: "We will use standard methods" -- specify which standards
2. **No justification**: Not explaining why this method over alternatives
3. **Missing controls**: Not describing control groups or baseline comparisons
4. **No power analysis**: Not justifying sample sizes
5. **Ignoring limitations**: Not acknowledging method limitations
6. **No alternative plan**: Not describing what happens if primary method fails
7. **Insufficient detail**: Not enough information for replication
8. **Overly detailed**: Including routine procedures that don't need explanation

## Rigor and Reproducibility Checklist

- [ ] Sample size justified with power analysis
- [ ] Randomization procedure described
- [ ] Blinding procedure described (or justified why not possible)
- [ ] Controls (positive, negative, vehicle) specified
- [ ] Biological/technical replicates distinguished
- [ ] Statistical tests specified a priori
- [ ] Multiple comparison correction described
- [ ] Data exclusion criteria stated
- [ ] Key resources authenticated (cell lines, antibodies, reagents)
- [ ] Sex/gender as biological variable addressed
- [ ] Data and code availability plan described
