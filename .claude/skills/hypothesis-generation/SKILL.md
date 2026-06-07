---
name: hypothesis-generation
description: "Generate testable hypotheses. Formulate from observations, design experiments, explore competing explanations, develop predictions, propose mechanisms, for scientific inquiry across domains."
allowed-tools: [Read, Write, Edit, Bash]
---

# Scientific Hypothesis Generation

## Overview

Hypothesis generation is a systematic process for developing testable explanations. Formulate evidence-based hypotheses from observations, design experiments, explore competing explanations, and develop predictions. Apply this skill for scientific inquiry across domains.

## When to Use This Skill

This skill should be used when:
- Developing hypotheses from observations or preliminary data
- Designing experiments to test scientific questions
- Exploring competing explanations for phenomena
- Formulating testable predictions for research
- Conducting literature-based hypothesis generation
- Planning mechanistic studies across scientific domains

## Visual Enhancement with Scientific Schematics

**⚠️ MANDATORY: Every hypothesis generation report MUST include at least 1-2 AI-generated figures using the scientific-schematics skill.**

This is not optional. Hypothesis reports without visual elements are incomplete. Before finalizing any document:
1. Generate at minimum ONE schematic or diagram (e.g., hypothesis framework showing competing explanations)
2. Prefer 2-3 figures for comprehensive reports (mechanistic pathway, experimental design flowchart, prediction decision tree)

**How to generate figures:**
- Use the **scientific-schematics** skill to generate AI-powered publication-quality diagrams
- Simply describe your desired diagram in natural language
- Nano Banana Pro will automatically generate, review, and refine the schematic

**How to generate schematics:**
```bash
python scripts/generate_schematic.py "your diagram description" -o figures/output.png
```

The AI will automatically:
- Create publication-quality images with proper formatting
- Review and refine through multiple iterations
- Ensure accessibility (colorblind-friendly, high contrast)
- Save outputs in the figures/ directory

**When to add schematics:**
- Hypothesis framework diagrams showing competing explanations
- Experimental design flowcharts
- Mechanistic pathway diagrams
- Prediction decision trees
- Causal relationship diagrams
- Theoretical model visualizations
- Any complex concept that benefits from visualization

For detailed guidance on creating schematics, refer to the scientific-schematics skill documentation.

---

## Workflow

Follow this systematic process to generate robust scientific hypotheses:

### 1. Understand the Phenomenon

Start by clarifying the observation, question, or phenomenon that requires explanation:

- Identify the core observation or pattern that needs explanation
- Define the scope and boundaries of the phenomenon
- Note any constraints or specific contexts
- Clarify what is already known vs. what is uncertain
- Identify the relevant scientific domain(s)

### 2. Conduct Comprehensive Literature Search

Search existing scientific literature to ground hypotheses in current evidence. Use academic databases and web search:

**For academic literature:**
- Use research-lookup to access relevant literature from Scopus, Web of Science, and Google Scholar
- Search for recent reviews, meta-analyses, and primary research
- Look for similar phenomena, related mechanisms, or analogous systems

**For all scientific domains:**
- Use WebSearch to find recent papers, preprints, and reviews
- Search for established theories, mechanisms, or frameworks
- Identify gaps in current understanding

**Search strategy:**
- Begin with broad searches to understand the landscape
- Narrow to specific mechanisms, pathways, or theories
- Look for contradictory findings or unresolved debates
- Consult `references/literature_search_strategies.md` for detailed search techniques

### 3. Synthesize Existing Evidence

Analyze and integrate findings from literature search:

- Summarize current understanding of the phenomenon
- Identify established mechanisms or theories that may apply
- Note conflicting evidence or alternative viewpoints
- Recognize gaps, limitations, or unanswered questions
- Identify analogies from related systems or domains

### 4. Generate Competing Hypotheses

Develop 3-5 distinct hypotheses that could explain the phenomenon. Each hypothesis should:

- Provide a mechanistic explanation (not just description)
- Be distinguishable from other hypotheses
- Draw on evidence from the literature synthesis
- Consider different levels of explanation (molecular, cellular, systemic, population, etc.)

**Strategies for generating hypotheses:**
- Apply known mechanisms from analogous systems
- Consider multiple causative pathways
- Explore different scales of explanation
- Question assumptions in existing explanations
- Combine mechanisms in novel ways

### 5. Evaluate Hypothesis Quality

Assess each hypothesis against established quality criteria from `references/hypothesis_quality_criteria.md`:

**Testability:** Can the hypothesis be empirically tested?
**Falsifiability:** What observations would disprove it?
**Parsimony:** Is it the simplest explanation that fits the evidence?
**Explanatory Power:** How much of the phenomenon does it explain?
**Scope:** What range of observations does it cover?
**Consistency:** Does it align with established principles?
**Novelty:** Does it offer new insights beyond existing explanations?

Explicitly note the strengths and weaknesses of each hypothesis.

### 6. Design Experimental Tests

For each viable hypothesis, propose specific experiments or studies to test it. Consult `references/experimental_design_patterns.md` for common approaches:

**Experimental design elements:**
- What would be measured or observed?
- What comparisons or controls are needed?
- What methods or techniques would be used?
- What sample sizes or statistical approaches are appropriate?
- What are potential confounds and how to address them?

**Consider multiple approaches:**
- Laboratory experiments (in vitro, in vivo, computational)
- Observational studies (cross-sectional, longitudinal, case-control)
- Clinical trials (if applicable)
- Natural experiments or quasi-experimental designs

### 7. Formulate Testable Predictions

For each hypothesis, generate specific, quantitative predictions:

- State what should be observed if the hypothesis is correct
- Specify expected direction and magnitude of effects when possible
- Identify conditions under which predictions should hold
- Distinguish predictions between competing hypotheses
- Note predictions that would falsify the hypothesis

### 8. Present Structured Output

Generate a professional LaTeX document using the template in `assets/hypothesis_report_template.tex`. The report should be well-formatted with colored boxes for visual organization and divided into a concise main text with comprehensive appendices.

**Document Structure:**

**Main Text (Maximum 4 pages):**
1. **Executive Summary** - Brief overview in summary box (0.5-1 page)
2. **Competing Hypotheses** - Each hypothesis in its own colored box with brief mechanistic explanation and key evidence (2-2.5 pages for 3-5 hypotheses)
   - **IMPORTANT:** Use `\newpage` before each hypothesis box to prevent content overflow
   - Each box should be ≤0.6 pages maximum
3. **Testable Predictions** - Key predictions in amber boxes (0.5-1 page)
4. **Critical Comparisons** - Priority comparison boxes (0.5-1 page)

Keep main text highly concise - only the most essential information. All details go to appendices.

**Page Break Strategy:**
- Always use `\newpage` before hypothesis boxes to ensure they start on fresh pages
- This prevents content from overflowing off page boundaries
- LaTeX boxes (tcolorbox) do not automatically break across pages

**Appendices (Comprehensive, Detailed):**
- **Appendix A:** Comprehensive literature review with extensive citations
- **Appendix B:** Detailed experimental designs with full protocols
- **Appendix C:** Quality assessment tables and detailed evaluations
- **Appendix D:** Supplementary evidence and analogous systems

**Colored Box Usage:**

Use the custom box environments from `hypothesis_generation.sty`:

- `hypothesisbox1` through `hypothesisbox5` - For each competing hypothesis (blue, green, purple, teal, orange)
- `predictionbox` - For testable predictions (amber)
- `comparisonbox` - For critical comparisons (steel gray)
- `evidencebox` - For supporting evidence highlights (light blue)
- `summarybox` - For executive summary (blue)

**Each hypothesis box should contain (keep concise for 4-page limit):**
- **Mechanistic Explanation:** 1-2 brief paragraphs (6-10 sentences max) explaining HOW and WHY
- **Key Supporting Evidence:** 2-3 bullet points with citations (most important evidence only)
- **Core Assumptions:** 1-2 critical assumptions

All detailed explanations, additional evidence, and comprehensive discussions belong in the appendices.

**Critical Overflow Prevention:**
- Insert `\newpage` before each hypothesis box to start it on a fresh page
- Keep each complete hypothesis box to ≤0.6 pages (approximately 15-20 lines of content)
- If content exceeds this, move additional details to Appendix A
- Never let boxes overflow off page boundaries - this creates unreadable PDFs

**Citation Requirements:**

Aim for extensive citation to support all claims:
- **Main text:** 10-15 key citations for most important evidence only (keep concise for 4-page limit)
- **Appendix A:** 40-70+ comprehensive citations covering all relevant literature
- **Total target:** 50+ references in bibliography

Main text citations should be selective - cite only the most critical papers. All comprehensive citation and detailed literature discussion belongs in the appendices. Use `\citep{author2023}` for parenthetical citations.

**LaTeX Compilation:**

The template requires XeLaTeX or LuaLaTeX for proper rendering:

```bash
xelatex hypothesis_report.tex
bibtex hypothesis_report
xelatex hypothesis_report.tex
xelatex hypothesis_report.tex
```

**Required packages:** The `hypothesis_generation.sty` style package must be in the same directory or LaTeX path. It requires: tcolorbox, xcolor, fontspec, fancyhdr, titlesec, enumitem, booktabs, natbib.

**Page Overflow Prevention:**

To prevent content from overflowing on pages, follow these critical guidelines:

1. **Monitor Box Content Length:** Each hypothesis box should fit comfortably on a single page. If content exceeds ~0.7 pages, it will likely overflow.

2. **Use Strategic Page Breaks:** Insert `\newpage` before boxes that contain substantial content:
   ```latex
   \newpage
   \begin{hypothesisbox1}[Hypothesis 1: Title]
   % Long content here
   \end{hypothesisbox1}
   ```

3. **Keep Main Text Boxes Concise:** For the 4-page main text limit:
   - Each hypothesis box: Maximum 0.5-0.6 pages
   - Mechanistic explanation: 1-2 brief paragraphs only (6-10 sentences max)
   - Key evidence: 2-3 bullet points only
   - Core assumptions: 1-2 items only
   - If content is longer, move details to appendices

4. **Break Long Content:** If a hypothesis requires extensive explanation, split across main text and appendix:
   - Main text box: Brief mechanistic overview + 2-3 key evidence points
   - Appendix A: Detailed mechanism explanation, comprehensive evidence, extended discussion

5. **Test Page Boundaries:** Before each new box, consider if remaining page space is sufficient. If less than 0.6 pages remain, use `\newpage` to start the box on a fresh page.

6. **Appendix Page Management:** In appendices, use `\newpage` between major sections to avoid overflow in detailed content areas.

**Quick Reference:** See `assets/FORMATTING_GUIDE.md` for detailed examples of all box types, color schemes, and common formatting patterns.

---

## Domain-Specific Hypothesis Templates

### Civil/Structural Engineering Hypothesis Types

#### Type 1: Structural Performance Hypothesis
**Pattern**: "Structure/system X under condition Y will exhibit behavior Z with quantitative bounds."
**Examples**:
- "Steel moment frames with buckling-restrained braces (BRBs) will achieve 40-60% higher energy dissipation capacity than conventional frames under near-fault ground motions (pulse-like records with PGV > 40 cm/s)."
- "Reinforced concrete beams with fiber-reinforced polymer (FRP) reinforcement will exhibit 15-25% lower stiffness degradation after 100 load cycles compared to steel-reinforced beams at the same service load level."
- "The interstory drift ratio demand of a 9-story steel structure with tuned mass dampers (TMDs) will remain below 2.0% under Design Basis Earthquake (DBE) level excitations, compared to 3.5% for the uncontrolled structure."
**Key Elements**: Loading protocol, performance metric, quantitative bounds, reference standard (GB 50011, ASCE 7)

#### Type 2: Material Behavior Hypothesis
**Pattern**: "Material X processed/treated with method Y will achieve property Z superior to conventional material."
**Examples**:
- "Ultra-high performance concrete (UHPC) with 2% steel fiber volume fraction will achieve compressive strength >150 MPa and flexural strength >25 MPa, meeting the GB/T 31387-2015 requirements."
- "Recycled aggregate concrete (RAC) with 50% replacement ratio and optimized mix design will achieve durability index within 10% of natural aggregate concrete after 28-day curing."
**Key Elements**: Material composition, processing method, performance metric, standard reference

#### Type 3: Numerical-Experimental Correlation Hypothesis
**Pattern**: "The finite element model X with constitutive model Y will predict experimental behavior Z within error bound W."
**Examples**:
- "A fiber-based beam-column element model with concrete02 and steel02 material models in OpenSees will predict the peak lateral force of RC columns within ±10% of experimental results and the post-peak softening behavior within ±15% drift error."
- "The CFD model using k-epsilon turbulence model will predict flood inundation depth within ±0.3 m of field observations for return periods of 50-100 years."
**Key Elements**: Software, constitutive model, validation metric, error bound

#### Type 4: Geotechnical Hypothesis
**Pattern**: "Soil/foundation system X under loading condition Y will exhibit capacity/settlement Z."
**Examples**:
- "A group pile foundation with 9 piles (3x3, s/d=3) in soft clay will exhibit group efficiency factor >0.85 under sustained loading, as predicted by the interaction factor method."
**Key Elements**: Soil profile, loading condition, prediction method, field/lab validation

#### Type 5: Structural Health Monitoring Hypothesis
**Pattern**: "SHM method/system X detects/identifies damage characteristic Y with accuracy Z under conditions W."
**Examples**:
- "Vibration-based damage detection method using natural frequency shifts and mode shape curvature identifies damage location with ≥85% accuracy and severity level (minor/moderate/severe/critical) using 12 accelerometers on a 3-span continuous steel bridge."
- "Structural health monitoring system using distributed fiber optic sensors (DFOS) detects crack growth of ≥0.1 mm within 24-hour time period with false alarm rate ≤5% in reinforced concrete flexural members."
**Key Elements**: Sensor type and count, damage metric, detection accuracy, false alarm rate, structural type

#### Type 6: Seismic Engineering Hypothesis
**Pattern**: "Seismic design/retrofit strategy X achieves performance metric Y under seismic hazard Z."
**Examples**:
- "Retrofitting strategy using buckling-restrained braces (BRBs) reduces seismic base shear demand by ≥30% while maintaining structural displacement ductility ≥4.0 under the FEMA P-695 far-field ground motion set."
- "Performance-based seismic design method following ASCE 41-17 nonlinear static procedure achieves target performance level (IO/LS/CP) with ≥90% reliability under BSE-2E hazard level (2% probability of exceedance in 50 years) for steel moment-resisting frames."
**Key Elements**: Retrofit/design method, hazard level, performance metric, reliability target, structural system

### Computer Science / AI Hypothesis Types

#### Algorithmic Hypotheses
- **Complexity improvement:** "Algorithm X achieves O(f(n)) time complexity for problem P, improving upon the existing O(g(n)) bound where f(n) = o(g(n))."
- **Approximation quality:** "Algorithm X achieves an approximation ratio of α for problem P, tightening the known bound from β to α."
- **Convergence guarantee:** "Method X converges to ε-optimal solution in O(1/ε^k) iterations under conditions C₁, C₂, ..., Cₙ."

#### Machine Learning Hypotheses
- **Performance improvement:** "Model X achieves higher [metric] than baseline Y on dataset D because [architectural/training innovation Z]."
- **Generalization:** "Model X trained on domain A transfers to domain B with ≤k% performance drop when [transfer mechanism] is applied."
- **Sample efficiency:** "Method X achieves comparable performance to baseline Y using only p% of the training data through [technique]."
- **Robustness:** "Model X maintains ≥t% accuracy under [perturbation type] at severity level s, outperforming baseline Y which drops to u%."
- **Fairness:** "Model X achieves demographic parity gap ≤δ across protected groups G₁, G₂, ..., Gₙ while maintaining overall accuracy ≥a%."

#### Systems Hypotheses
- **Scalability:** "System X maintains throughput T and latency ≤L when scaling from N₁ to N₂ nodes under workload W."
- **Resource efficiency:** "System X reduces memory/compute/storage by p% compared to baseline Y while maintaining equivalent performance."
- **Fault tolerance:** "System X maintains ≥a% availability under failure scenario F with recovery time ≤R."

#### Data/Hypothesis-Driven Hypotheses
- **Data quality:** "Training on dataset D' (cleaned/filtered by method M) improves model performance by p% compared to training on original dataset D."
- **Feature importance:** "Feature set F₁ is more predictive of outcome Y than feature set F₂, with ΔAUC ≥ δ."
- **Causal discovery:** "Variable X has a causal effect on outcome Y with effect size ≥ e, controlling for confounders Z₁, Z₂, ..., Zₙ."

#### LLM-Specific Hypotheses
- **Instruction following:** "Model X with [prompting/alignment technique] achieves ≥s% score on instruction-following benchmark B."
- **Reasoning:** "Chain-of-thought prompting improves model X's accuracy on reasoning tasks by ≥p% compared to direct prompting."
- **Hallucination reduction:** "Method X reduces factual hallucination rate by ≥p% on benchmark B while maintaining fluency scores."
- **Data contamination:** "Model X's performance on benchmark B is inflated by ≤k% when evaluated on decontaminated test instances."

### Environmental Engineering Hypothesis Types

#### Type 8: Treatment Efficiency Hypothesis
**Pattern**: "Treatment technology X achieves removal efficiency Y for pollutant Z under conditions W."
**Examples**:
- "Granular activated carbon (GAC) adsorption with 15 min empty bed contact time (EBCT) will achieve >95% removal of perfluorooctanoic acid (PFOA) from groundwater at initial concentration 100 ng/L, meeting the EPA health advisory level of 70 ng/L."
- "The anammox reactor operated at 35 degrees C with hydraulic retention time (HRT) of 12 hours will achieve >90% nitrogen removal at nitrogen loading rate of 2.0 kg N/(m^3*d)."
**Key Elements**: Pollutant, initial concentration, operating conditions, regulatory standard

#### Type 9: Carbon/Energy Hypothesis
**Pattern**: "Intervention X achieves carbon reduction Y% or energy saving Z% compared to baseline."
**Examples**:
- "Deep retrofit of existing office buildings (envelope + HVAC + lighting) in Climate Zone 4A will achieve 55-65% reduction in operational carbon emissions (tCO2e/m2/yr), with embodied carbon payback period <10 years."
- "The hybrid solar-wind-battery system for a mid-rise residential building in Ningbo will achieve 75% self-sufficiency ratio with LCOE of 0.45-0.55 RMB/kWh over 25-year lifetime."
**Key Elements**: System boundary, baseline comparison, metric (tCO2e, kWh, LCOE), time horizon

#### Type 10: Environmental Fate Hypothesis
**Pattern**: "Contaminant X in medium Y undergoes process Z with rate/bound W."
**Examples**:
- "Microplastics (1-5 um polyethylene) in coastal sediments undergo photodegradation at a rate of 0.8-1.2% per month under UV-B exposure, with half-life of 60-90 months in the top 5 cm sediment layer."
**Key Elements**: Contaminant speciation, environmental medium, process, kinetic parameters

### Interdisciplinary Hypothesis Types

#### Type 11: AI for Civil Engineering (Civil x CS)
**Pattern**: "Physics-informed ML model X achieves prediction accuracy Y for engineering problem Z while satisfying physical constraints C."
**Examples**:
- "A physics-informed neural network (PINN) with strain energy loss function predicts the nonlinear static pushover response of RC shear walls within 5% of FEM results, while exactly satisfying equilibrium equations, at 1000x computational speedup."
- "Graph neural network (GNN) with message passing on structural connectivity graphs predicts damage location in truss structures with >90% F1-score using only 5% of sensor nodes."
**Key Elements**: Physical constraints, ML architecture, engineering problem, validation method, computational advantage

#### Type 12: AI for Environmental Engineering (Environmental x CS)
**Pattern**: "ML model X achieves prediction accuracy Y for environmental variable Z, outperforming traditional method M."
**Examples**:
- "LSTM-based air quality prediction model using meteorological and emission data achieves RMSE <15 ug/m^3 for PM2.5 24-hour forecasting, outperforming CMAQ by 30% at 100x lower computational cost."
- "Random forest model trained on satellite imagery and in-situ measurements predicts chlorophyll-a concentration in reservoirs with R^2 >0.85, enabling early warning of algal blooms 3-5 days in advance."
**Key Elements**: Data sources, model architecture, accuracy metric, comparison with physics-based models

#### Type 13: Sustainable Infrastructure (Civil x Environmental)
**Pattern**: "Sustainable material/design X achieves structural performance Y while reducing environmental impact Z."
**Examples**:
- "Geopolymer concrete using fly ash and slag achieves compressive strength of 40-50 MPa (meeting C40 grade requirements per GB 50010) while reducing embodied carbon by 60-70% compared to OPC concrete."
- "Modular steel-concrete composite construction reduces construction waste by 40% and embodied carbon by 25% while maintaining equivalent seismic performance to cast-in-place RC construction (interstory drift <2% under DBE)."
**Key Elements**: Structural metric, environmental metric, standard compliance, comparison baseline

#### Type 14: Smart City/Energy (Civil x CS x Environmental)
**Pattern**: "Integrated AI+IoT system X achieves urban-scale efficiency Y while reducing environmental impact Z."
**Examples**:
- "Digital twin-based building energy management system using reinforcement learning achieves 25-35% reduction in HVAC energy consumption while maintaining thermal comfort (PMV between -0.5 and +0.5) across 4 climate zones in China."
- "IoT-enabled bridge structural health monitoring with edge computing anomaly detection reduces inspection cost by 50% while detecting damage >95% accuracy (F1-score), with 5-year lifecycle carbon footprint 30% lower than manual inspection."
**Key Elements**: System integration, AI method, IoT architecture, performance metrics (technical + environmental + economic), scale

### Hypothesis Quality Checklist (Domain-Enhanced)
In addition to the 7 general criteria (Testability, Falsifiability, Parsimony, Explanatory Power, Scope, Consistency, Novelty), domain-specific hypotheses should also check:

**Civil Engineering**:
- [ ] Loading/boundary conditions explicitly defined
- [ ] Performance metric has engineering significance (not just statistical)
- [ ] Reference standard cited (GB/JGJ/ACI/Eurocode)
- [ ] Scale effects acknowledged (lab vs. field)
- [ ] Safety implications considered

**Computer Science**:
- [ ] Baseline comparison is fair (same compute budget)
- [ ] Benchmark dataset is standard and well-established
- [ ] Statistical significance with multiple runs
- [ ] Computational cost reported
- [ ] Reproducibility feasible with described information

**Environmental Engineering**:
- [ ] QA/QC procedures described
- [ ] Detection limits (LOD/LOQ) stated
- [ ] Regulatory relevance (EPA/WHO/GB standards)
- [ ] Scale-up feasibility discussed
- [ ] Environmental significance (not just statistical significance)

**Cross-Disciplinary**:
- [ ] Both domain contributions are substantial (not token)
- [ ] Physical/domain constraints are satisfied (not just data-driven)
- [ ] Comparison with domain-specific baselines (not just ML baselines)
- [ ] Interpretability for domain experts
- [ ] Practical deployment pathway described

## Quality Standards

Ensure all generated hypotheses meet these standards:

- **Evidence-based:** Grounded in existing literature with citations
- **Testable:** Include specific, measurable predictions
- **Mechanistic:** Explain how/why, not just what
- **Comprehensive:** Consider alternative explanations
- **Rigorous:** Include experimental designs to test predictions

## Resources

### references/

- `hypothesis_quality_criteria.md` - Framework for evaluating hypothesis quality (testability, falsifiability, parsimony, explanatory power, scope, consistency)
- `experimental_design_patterns.md` - Common experimental approaches across domains (RCTs, observational studies, lab experiments, computational models)
- `literature_search_strategies.md` - Effective search techniques for academic databases

### assets/

- `hypothesis_generation.sty` - LaTeX style package providing colored boxes, professional formatting, and custom environments for hypothesis reports
- `hypothesis_report_template.tex` - Complete LaTeX template with main text structure and comprehensive appendix sections
- `FORMATTING_GUIDE.md` - Quick reference guide with examples of all box types, color schemes, citation practices, and troubleshooting tips

### Related Skills

When preparing hypothesis-driven research for publication, consult the **venue-templates** skill for writing style guidance:
- `venue_writing_styles.md` - Master guide comparing styles across venues
- Venue-specific guides for Nature/Science, engineering journals, and ML/CS conferences
- `reviewer_expectations.md` - What reviewers look for when evaluating research hypotheses
