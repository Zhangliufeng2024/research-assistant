# CS/AI Research Methodology Guide

## Research Workflow for CS/AI Papers

### Phase 1: Problem Definition and Baseline
1. **Define the research problem** with formal notation
2. **Establish baseline(s)** using published implementations (prefer reuse over reimplementation)
3. **Define evaluation contract**: metrics, datasets, splits, aggregation
4. **Set up reproducibility**: random seeds, software versions, hardware specs

### Phase 2: Literature-Grounded Ideation
1. **Broad literature survey** (5-10 papers minimum): foundational, SOTA, competing, cross-domain
2. **Extract limitations** of existing approaches: saturated, decorative, and differentiated opportunities
3. **Generate ideas** using multiple lenses:
   - Mechanism route: new architecture, algorithm, or training method
   - Objective route: new loss function, metric, or optimization target
   - Measurement route: new evaluation, benchmark, or analysis method
   - Infrastructure route: new system, tool, or deployment approach
4. **Stress-test top candidates** with hidden assumptions and rejection cases
5. **Select route** with explicit novelty type, risk assessment, and falsification path

### Phase 3: Experimentation
1. **Start with minimum viable evidence**: one clean implementation pass, one real run
2. **Evidence ladder**:
   - Minimum: executable and comparable to baseline
   - Solid: strong enough to carry the main claim
   - Maximum: broader supporting polish after main claim is credible
3. **Ablation study**: systematically remove/replace each component
4. **Robustness checks**: OOD data, adversarial perturbation, domain shift
5. **Failure analysis**: classify failures (implementation, evaluation, environment, direction)

### Phase 4: Analysis and Writing
1. **Claim-evidence mapping**: every claim points to artifact, citation, or explicit gap
2. **Figure/table planning**: design displays before prose
3. **Section-by-section drafting**: write abstract last
4. **Validation**: check claim-evidence consistency, reference completeness, figure quality

### Phase 5: Review and Rebuttal
1. **Self-review**: 13-dimension audit (novelty, rigor, clarity, evidence, etc.)
2. **Experiment inventory**: classify all results (completed, written but not evidenced, failed)
3. **Revision plan**: prioritize issues by severity
4. **Rebuttal preparation**: normalize reviewer comments into atomic items with explicit routes

## Experiment Design Patterns

### Pattern 1: Ablation Study
**Goal:** Isolate contribution of each proposed component
**Protocol:**
- Start with full model (all components enabled)
- Remove/replace ONE component at a time
- Measure delta vs. full model
- Rank components by contribution magnitude
**Report:** Full model result + each ablated variant + delta values + significance

### Pattern 2: Hyperparameter Sweep
**Goal:** Understand sensitivity and find optimal configuration
**Protocol:**
- Sweep each hyperparameter across ≥3 orders of magnitude
- Fix all other hyperparameters at reasonable defaults
- Report best values, search ranges, and sensitivity curves
**Report:** Sensitivity plots + recommended defaults + total compute for search

### Pattern 3: Robustness Evaluation
**Goal:** Verify performance under distribution shift
**Protocol:**
- Natural shift: test on data from different time/location/source
- Synthetic shift: noise, corruption, adversarial examples
- Domain transfer: related but different domain
**Report:** Performance degradation curves + comparison with baselines

### Pattern 4: Scaling Analysis
**Goal:** Understand how method scales with resources
**Protocol:**
- Vary model size (parameters), data size, compute budget
- Plot performance vs. resource usage
- Compare scaling curves with baselines
**Report:** Scaling plots + efficiency comparison + extrapolation discussion

### Pattern 5: Fairness Audit
**Goal:** Ensure model does not discriminate across protected groups
**Protocol:**
- Identify protected attributes
- Compute fairness metrics (demographic parity, equalized odds, predictive parity)
- Evaluate mitigation strategies if bias detected
**Report:** Per-group metrics + fairness-accuracy tradeoffs + mitigation results

### Pattern 6: Reproducibility Package
**Goal:** Enable others to reproduce results exactly
**Protocol:**
- Release code with clear README and dependencies
- Document all random seeds and configurations
- Provide data preprocessing scripts
- Include hardware and timing requirements
**Report:** Reproducibility checklist (NeurIPS/ICML standard)

## Common Failure Modes in CS/AI Research

1. **Surrogate optimization**: Improving a proxy metric without validating on the real objective
2. **Benchmark overfitting**: Tuning specifically for benchmark performance rather than general capability
3. **Ablation confounding**: Changing multiple components simultaneously, making it impossible to attribute improvement
4. **Selection bias**: Reporting only best runs while hiding failures
5. **Leakage**: Using test data during training or hyperparameter selection
6. **Unfair comparison**: Different preprocessing, data splits, or evaluation protocols for proposed vs. baseline methods
7. **Compute asymmetry**: Comparing methods with vastly different computational budgets without accounting for it
8. **Cherry-picking examples**: Showing only qualitative results where the method works well
9. **Missing error bars**: Reporting single-run results without variance
10. **Overclaiming**: Drawing conclusions not supported by the experimental evidence

## Review Framework for CS/AI Papers

### Pre-Submission Checklist
- [ ] Research question clearly stated and well-motivated
- [ ] Novelty clearly articulated relative to prior work
- [ ] Baselines are fair and include SOTA methods
- [ ] Ablation study isolates contribution of each component
- [ ] Multiple random seeds (≥3) with mean ± std reported
- [ ] Statistical significance tested for key claims
- [ ] Hyperparameter sensitivity analysis included
- [ ] Training curves reported
- [ ] Compute budget reported
- [ ] OOD/robustness evaluation included
- [ ] Code available or will be available
- [ ] Reproducibility checklist completed
- [ ] Limitations honestly discussed
- [ ] Broader impact discussed (if applicable)

### Evaluation Dimensions
1. **Novelty**: Is the contribution genuinely new? How does it differ from prior work?
2. **Significance**: Does it solve an important problem? Would it change practice?
3. **Rigor**: Are the experiments thorough and fair? Are claims supported by evidence?
4. **Clarity**: Is the paper well-written? Can a reader reproduce the work?
5. **Reproducibility**: Could another researcher replicate the results from the paper alone?
6. **Validity**: Are threats to validity honestly discussed?
7. **Adequacy**: Are the baselines, datasets, and metrics appropriate?
8. **Efficiency**: Is the computational cost reasonable for the benefit gained?
9. **Generality**: Does the method apply beyond the specific setting tested?
10. **Ethics**: Are there concerns about bias, fairness, safety, or misuse?
