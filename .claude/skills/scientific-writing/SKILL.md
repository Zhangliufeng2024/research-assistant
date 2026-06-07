---
name: scientific-writing
description: "Core skill for the deep research and writing tool. Write scientific manuscripts in full paragraphs (never bullet points). Use two-stage process: (1) create section outlines with key points using research-lookup, (2) convert to flowing prose. IMRAD structure, citations (APA/AMA/Vancouver), figures/tables, reporting guidelines (CONSORT/STROBE/PRISMA). Supports engineering domains: structural analysis, FEM, LCA, energy systems, AI-for-engineering - applies ASCE, Eurocode, ISO 14040, ASHRAE 90.1 standards as appropriate. For research papers and journal submissions across all disciplines."
allowed-tools: [Read, Write, Edit, Bash]
---

# Scientific Writing

## Overview

**This is the core skill for the deep research and writing tool**—combining AI-driven deep research with well-formatted written outputs. Every document produced is backed by comprehensive literature search and verified citations through the research-lookup skill.

Scientific writing is a process for communicating research with precision and clarity. Write manuscripts using IMRAD structure, citations (APA/AMA/Vancouver), figures/tables, and reporting guidelines (CONSORT/STROBE/PRISMA). Apply this skill for research papers and journal submissions.

**Critical Principle: Always write in full paragraphs with flowing prose. Never submit bullet points in the final manuscript.** Use a two-stage process: first create section outlines with key points using research-lookup, then convert those outlines into complete paragraphs.

## When to Use This Skill

This skill should be used when:
- Writing or revising any section of a scientific manuscript (abstract, introduction, methods, results, discussion)
- Structuring a research paper using IMRAD or other standard formats
- Formatting citations and references in specific styles (APA, AMA, Vancouver, Chicago, IEEE)
- Creating, formatting, or improving figures, tables, and data visualizations
- Applying study-specific reporting guidelines (CONSORT for trials, STROBE for observational studies, PRISMA for reviews)
- Drafting abstracts that meet journal requirements (structured or unstructured)
- Preparing manuscripts for submission to specific journals
- Improving writing clarity, conciseness, and precision
- Ensuring proper use of field-specific terminology and nomenclature
- Addressing reviewer comments and revising manuscripts

## Visual Enhancement with Scientific Schematics

**⚠️ MANDATORY: Every scientific paper MUST include a graphical abstract plus 1-2 additional AI-generated figures using the scientific-schematics skill.**

This is not optional. Scientific papers without visual elements are incomplete. Before finalizing any document:
1. **ALWAYS generate a graphical abstract** as the first visual element
2. Generate at minimum ONE additional schematic or diagram using scientific-schematics
3. Prefer 3-4 total figures for comprehensive papers (graphical abstract + methods flowchart + results visualization + conceptual diagram)

### Graphical Abstract (REQUIRED)

**Every scientific writeup MUST include a graphical abstract.** This is a visual summary of your paper that:
- Appears before or immediately after the text abstract
- Captures the entire paper's key message in one image
- Is suitable for journal table of contents display
- Uses landscape orientation (typically 1200x600px)

**Generate the graphical abstract FIRST:**
```bash
python research_assistant/.claude/skills/scientific-schematics/scripts/generate_schematic.py "Graphical abstract for [paper title]: [brief description showing workflow from input → methods → key findings → conclusions]" -o figures/graphical_abstract.png
```

**Graphical Abstract Requirements:**
- **Content**: Visual summary showing workflow, key methods, main findings, and conclusions
- **Style**: Clean, professional, suitable for journal TOC
- **Elements**: Include 3-5 key steps/concepts with connecting arrows or flow
- **Text**: Minimal labels, large readable fonts
- Log: `[HH:MM:SS] GENERATED: Graphical abstract for paper summary`

### Additional Figures (GENERATE EXTENSIVELY)

**⚠️ CRITICAL: Use BOTH scientific-schematics AND generate-image EXTENSIVELY throughout all documents.**

Every document should be richly illustrated. Generate figures liberally - when in doubt, add a visual.

**MINIMUM Figure Requirements:**

| Document Type | Minimum | Recommended |
|--------------|---------|-------------|
| Research Papers | 5 | 6-8 |
| Literature Reviews | 4 | 5-7 |
| Market Research | 20 | 25-30 |
| Presentations | 1/slide | 1-2/slide |
| Posters | 6 | 8-10 |
| Grants | 4 | 5-7 |
| Clinical Reports | 3 | 4-6 |

**Use scientific-schematics EXTENSIVELY for technical diagrams:**
```bash
python research_assistant/.claude/skills/scientific-schematics/scripts/generate_schematic.py "your diagram description" -o figures/output.png
```

- Study design and methodology flowcharts (CONSORT, PRISMA, STROBE)
- Conceptual framework diagrams
- Experimental workflow illustrations
- Data analysis pipeline diagrams
- Biological pathway or mechanism diagrams
- System architecture visualizations
- Neural network architectures
- Decision trees, algorithm flowcharts
- Comparison matrices, timeline diagrams
- Any technical concept that benefits from schematic visualization

**Use generate-image EXTENSIVELY for visual content:**
```bash
python research_assistant/.claude/skills/generate-image/scripts/generate_image.py "your image description" -o figures/output.png
```

- Photorealistic illustrations of concepts
- Medical/anatomical illustrations
- Environmental/ecological scenes
- Equipment and lab setup visualizations
- Artistic visualizations, infographics
- Cover images, header graphics
- Product mockups, prototype visualizations
- Any visual that enhances understanding or engagement

The AI will automatically:
- Create publication-quality images with proper formatting
- Review and refine through multiple iterations
- Ensure accessibility (colorblind-friendly, high contrast)
- Save outputs in the figures/ directory

**When in Doubt, Generate a Figure:**
- Complex concept → generate a schematic
- Data discussion → generate a visualization
- Process description → generate a flowchart
- Comparison → generate a comparison diagram
- Reader benefit → generate a visual

For detailed guidance, refer to the scientific-schematics and generate-image skill documentation.

---

## Core Capabilities

### 1. Manuscript Structure and Organization

**IMRAD Format**: Guide papers through the standard Introduction, Methods, Results, And Discussion structure used across most scientific disciplines. This includes:
- **Introduction**: Establish research context, identify gaps, state objectives
- **Methods**: Detail study design, populations, procedures, and analysis approaches
- **Results**: Present findings objectively without interpretation
- **Discussion**: Interpret results, acknowledge limitations, propose future directions

For detailed guidance on IMRAD structure, refer to `references/imrad_structure.md`.

**Alternative Structures**: Support discipline-specific formats including:
- Review articles (narrative, systematic, scoping)
- Case reports and case series
- Meta-analyses and pooled analyses
- Theoretical/modeling papers
- Methods papers and protocols

### 2. Section-Specific Writing Guidance

**Abstract Composition**: Craft concise, standalone summaries (150-300 words) written as **flowing paragraphs**—never with labeled sections like "Background:", "Methods:", "Results:", "Conclusions:". The abstract should read as cohesive prose covering: (1) context and problem, (2) what was done, (3) key findings with specific numbers, and (4) significance and implications. Only use structured abstracts with labels if the journal explicitly requires them in their author guidelines.

**Introduction Development**: Build compelling introductions that:
- Establish the research problem's importance
- Review relevant literature systematically
- Identify knowledge gaps or controversies
- State clear research questions or hypotheses
- Explain the study's novelty and significance

**Methods Documentation**: Ensure reproducibility through:
- Detailed participant/sample descriptions
- Clear procedural documentation
- Statistical methods with justification
- Equipment and materials specifications
- Ethical approval and consent statements

**Results Presentation**: Present findings with:
- Logical flow from primary to secondary outcomes
- Integration with figures and tables
- Statistical significance with effect sizes
- Objective reporting without interpretation

**Discussion Construction**: Synthesize findings by:
- Relating results to research questions
- Comparing with existing literature
- Acknowledging limitations honestly
- Proposing mechanistic explanations
- Suggesting practical implications and future research

### 3. Citation and Reference Management

Apply citation styles correctly across disciplines. For comprehensive style guides, refer to `references/citation_styles.md`.

**Major Citation Styles:**
- **AMA (American Medical Association)**: Numbered superscript citations, common in medicine
- **Vancouver**: Numbered citations in square brackets, biomedical standard
- **APA (American Psychological Association)**: Author-date in-text citations, common in social sciences
- **Chicago**: Notes-bibliography or author-date, humanities and sciences
- **IEEE**: Numbered square brackets, engineering and computer science

**Best Practices:**
- Cite primary sources when possible
- Include recent literature (last 5-10 years for active fields)
- Balance citation distribution across introduction and discussion
- Verify all citations against original sources
- Use reference management software (Zotero, Mendeley, EndNote)

**MANDATORY: Post-Writing Citation Metadata Check**

After completing each section, scan `references.bib` for any entries missing `volume`, `pages`, or `doi` fields. For every incomplete entry, perform a web search to find the missing metadata:

1. Search using `parallel_web.py search "AUTHOR TITLE JOURNAL volume pages DOI"`
2. If DOI exists, extract metadata from `https://doi.org/DOI` using `parallel_web.py extract`
3. Update the BibTeX entry with found metadata
4. Log: `[HH:MM:SS] METADATA ENRICHED: [CitationKey] - added [fields] ✅`

This check must happen BEFORE final PDF compilation. See the citation-management skill (Phase 2.5) for detailed instructions.

### 4. Figures and Tables

Create effective data visualizations that enhance comprehension. For detailed best practices, refer to `references/figures_tables.md`.

**When to Use Tables vs. Figures:**
- **Tables**: Precise numerical data, complex datasets, multiple variables requiring exact values
- **Figures**: Trends, patterns, relationships, comparisons best understood visually

**Design Principles:**
- Make each table/figure self-explanatory with complete captions
- Use consistent formatting and terminology across all display items
- Label all axes, columns, and rows with units
- Include sample sizes (n) and statistical annotations
- Follow the "one table/figure per 1000 words" guideline
- Avoid duplicating information between text, tables, and figures

**Common Figure Types:**
- Bar graphs: Comparing discrete categories
- Line graphs: Showing trends over time
- Scatterplots: Displaying correlations
- Box plots: Showing distributions and outliers
- Heatmaps: Visualizing matrices and patterns

### 5. Reporting Guidelines by Study Type

Ensure completeness and transparency by following established reporting standards. For comprehensive guideline details, refer to `references/reporting_guidelines.md`.

**Key Guidelines:**
- **CONSORT**: Randomized controlled trials
- **STROBE**: Observational studies (cohort, case-control, cross-sectional)
- **PRISMA**: Systematic reviews and meta-analyses
- **STARD**: Diagnostic accuracy studies
- **TRIPOD**: Prediction model studies
- **ARRIVE**: Animal research
- **CARE**: Case reports
- **SQUIRE**: Quality improvement studies
- **SPIRIT**: Study protocols for clinical trials
- **CHEERS**: Economic evaluations
- **STORBE-AHE**: Built environment and health observational studies

**Engineering & Environmental Standards:**
- **ISO 14040/14044**: Life Cycle Assessment (LCA) methodology and reporting
- **ISO 14064-1**: GHG quantification and reporting for organizations
- **GHG Protocol**: Corporate and project-level carbon accounting (Scope 1/2/3)
- **ASHRAE 90.1 / ISO 52000**: Building energy performance reporting
- **ASCE reporting guidelines**: Structural engineering studies (see J. Structural Eng. author guidelines)
- **IEEE Std 1366**: Power system reliability reporting
- **Checklist for Artificial Intelligence in Medical Imaging (CLAIM)** — adapted variant used for AI-in-engineering reproducibility

**Computational/Simulation Studies:**
- Report software name, version, and licensing (open-source vs. commercial)
- Include mesh convergence or grid independence study
- Validate model against analytical solutions or benchmark experimental data
- Report material model, constitutive law, and calibration procedure
- Specify solver settings: tolerance, time step, convergence criteria

Each guideline provides checklists ensuring all critical methodological elements are reported.

### 6. Writing Principles and Style

Apply fundamental scientific writing principles. For detailed guidance, refer to `references/writing_principles.md`.

**Clarity**:
- Use precise, unambiguous language
- Define technical terms and abbreviations at first use
- Maintain logical flow within and between paragraphs
- Use active voice when appropriate for clarity

**Conciseness**:
- Eliminate redundant words and phrases
- Favor shorter sentences (15-20 words average)
- Remove unnecessary qualifiers
- Respect word limits strictly

**Accuracy**:
- Report exact values with appropriate precision
- Use consistent terminology throughout
- Distinguish between observations and interpretations
- Acknowledge uncertainty appropriately

**Objectivity**:
- Present results without bias
- Avoid overstating findings or implications
- Acknowledge conflicting evidence
- Maintain professional, neutral tone

### 7. Writing Process: From Outline to Full Paragraphs

**CRITICAL: Always write in full paragraphs, never submit bullet points in scientific papers.**

Scientific papers must be written in complete, flowing prose. Use this two-stage approach for effective writing:

**Stage 1: Create Section Outlines with Key Points**

When starting a new section:
1. Use the research-lookup skill to gather relevant literature and data
2. Create a structured outline with bullet points marking:
   - Main arguments or findings to present
   - Key studies to cite
   - Data points and statistics to include
   - Logical flow and organization
3. These bullet points serve as scaffolding—they are NOT the final manuscript

**Example outline (Introduction section):**
```
- Background: AI in drug discovery gaining traction
  * Cite recent reviews (Smith 2023, Jones 2024)
  * Traditional methods are slow and expensive
- Gap: Limited application to rare diseases
  * Only 2 prior studies (Lee 2022, Chen 2023)
  * Small datasets remain a challenge
- Our approach: Transfer learning from common diseases
  * Novel architecture combining X and Y
- Study objectives: Validate on 3 rare disease datasets
```

**Stage 2: Convert Key Points to Full Paragraphs**

Once the outline is complete, expand each bullet point into proper prose:

1. **Transform bullet points into complete sentences** with subjects, verbs, and objects
2. **Add transitions** between sentences and ideas (however, moreover, in contrast, subsequently)
3. **Integrate citations naturally** within sentences, not as lists
4. **Expand with context and explanation** that bullet points omit
5. **Ensure logical flow** from one sentence to the next within each paragraph
6. **Vary sentence structure** to maintain reader engagement

**Example conversion to prose:**

```
Artificial intelligence approaches have gained significant traction in drug discovery 
pipelines over the past decade (Smith, 2023; Jones, 2024). While these computational 
methods show promise for accelerating the identification of therapeutic candidates, 
traditional experimental approaches remain slow and resource-intensive, often requiring 
years of laboratory work and substantial financial investment. However, the application 
of AI to rare diseases has been limited, with only two prior studies demonstrating 
proof-of-concept results (Lee, 2022; Chen, 2023). The primary obstacle has been the 
scarcity of training data for conditions affecting small patient populations. 

To address this challenge, we developed a transfer learning approach that leverages 
knowledge from well-characterized common diseases to predict therapeutic targets for 
rare conditions. Our novel neural architecture combines convolutional layers for 
molecular feature extraction with attention mechanisms for protein-ligand interaction 
modeling. The objective of this study was to validate our approach across three 
independent rare disease datasets, assessing both predictive accuracy and biological 
interpretability of the results.
```

**Key Differences Between Outlines and Final Text:**

| Outline (Planning Stage) | Final Manuscript |
|--------------------------|------------------|
| Bullet points and fragments | Complete sentences and paragraphs |
| Telegraphic notes | Full explanations with context |
| List of citations | Citations integrated into prose |
| Abbreviated ideas | Developed arguments with transitions |
| For your eyes only | For publication and peer review |

**Common Mistakes to Avoid:**

- ❌ **Never** leave bullet points in the final manuscript
- ❌ **Never** submit lists where paragraphs should be
- ❌ **Don't** use numbered or bulleted lists in Results or Discussion sections (except for specific cases like study hypotheses or inclusion criteria)
- ❌ **Don't** write sentence fragments or incomplete thoughts
- ✅ **Do** use occasional lists only in Methods (e.g., inclusion/exclusion criteria, materials lists)
- ✅ **Do** ensure every section flows as connected prose
- ✅ **Do** read paragraphs aloud to check for natural flow

**When Lists ARE Acceptable (Limited Cases):**

Lists may appear in scientific papers only in specific contexts:
- **Methods**: Inclusion/exclusion criteria, materials and reagents, participant characteristics
- **Supplementary Materials**: Extended protocols, equipment lists, detailed parameters
- **Never in**: Abstract, Introduction, Results, Discussion, Conclusions

**Abstract Format Rule:**
- ❌ **NEVER** use labeled sections (Background:, Methods:, Results:, Conclusions:)
- ✅ **ALWAYS** write as flowing paragraph(s) with natural transitions
- Exception: Only use structured format if journal explicitly requires it in author guidelines

**Integration with Research Lookup:**

The research-lookup skill is essential for Stage 1 (creating outlines):
1. Search for relevant papers using research-lookup
2. Extract key findings, methods, and data
3. Organize findings as bullet points in your outline
4. Then convert the outline to full paragraphs in Stage 2

This two-stage process ensures you:
- Gather and organize information systematically
- Create logical structure before writing
- Produce polished, publication-ready prose
- Maintain focus on the narrative flow

### 8. Journal-Specific Formatting

Adapt manuscripts to journal requirements:
- Follow author guidelines for structure, length, and format
- Apply journal-specific citation styles
- Meet figure/table specifications (resolution, file formats, dimensions)
- Include required statements (funding, conflicts of interest, data availability, ethical approval)
- Adhere to word limits for each section
- Format according to template requirements when provided

### 9. Field-Specific Language and Terminology

Adapt language, terminology, and conventions to match the specific scientific discipline. Each field has established vocabulary, preferred phrasings, and domain-specific conventions that signal expertise and ensure clarity for the target audience.

**Identify Field-Specific Linguistic Conventions:**
- Review terminology used in recent high-impact papers in the target journal
- Note field-specific abbreviations, units, and notation systems
- Identify preferred terms (e.g., "participants" vs. "subjects," "compound" vs. "drug," "specimens" vs. "samples")
- Observe how methods, organisms, or techniques are typically described

**Biomedical and Clinical Sciences:**
- Use precise anatomical and clinical terminology (e.g., "myocardial infarction" not "heart attack" in formal writing)
- Follow standardized disease nomenclature (ICD, DSM, SNOMED-CT)
- Specify drug names using generic names first, brand names in parentheses if needed
- Use "patients" for clinical studies, "participants" for community-based research
- Follow Human Genome Variation Society (HGVS) nomenclature for genetic variants
- Report lab values with standard units (SI units in most international journals)

**Molecular Biology and Genetics:**
- Use italics for gene symbols (e.g., *TP53*), regular font for proteins (e.g., p53)
- Follow species-specific gene nomenclature (uppercase for human: *BRCA1*; sentence case for mouse: *Brca1*)
- Specify organism names in full at first mention, then use accepted abbreviations (e.g., *Escherichia coli*, then *E. coli*)
- Use standard genetic notation (e.g., +/+, +/-, -/- for genotypes)
- Employ established terminology for molecular techniques (e.g., "quantitative PCR" or "qPCR," not "real-time PCR")

**Chemistry and Pharmaceutical Sciences:**
- Follow IUPAC nomenclature for chemical compounds
- Use systematic names for novel compounds, common names for well-known substances
- Specify chemical structures using standard notation (e.g., SMILES, InChI for databases)
- Report concentrations with appropriate units (mM, μM, nM, or % w/v, v/v)
- Describe synthesis routes using accepted reaction nomenclature
- Use terms like "bioavailability," "pharmacokinetics," "IC50" consistently with field definitions

**Ecology and Environmental Sciences:**
- Use binomial nomenclature for species (italicized: *Homo sapiens*)
- Specify taxonomic authorities at first species mention when relevant
- Employ standardized habitat and ecosystem classifications
- Use consistent terminology for ecological metrics (e.g., "species richness," "Shannon diversity index")
- Describe sampling methods with field-standard terms (e.g., "transect," "quadrat," "mark-recapture")

**Physics and Engineering:**
- Follow SI units consistently unless field conventions dictate otherwise
- Use standard notation for physical quantities (scalars vs. vectors, tensors)
- Employ established terminology for phenomena (e.g., "quantum entanglement," "laminar flow")
- Specify equipment with model numbers and manufacturers when relevant
- Use mathematical notation consistent with field standards (e.g., ℏ for reduced Planck constant)

**Civil and Structural Engineering:**
- Reference design standards explicitly and by version: "per ASCE 7-22 Section 12.8," "in accordance with EN 1992-1-1:2023," or "following ACI 318-19"
- Use standard structural notation: M (bending moment, kN·m), V (shear force, kN), N (axial force, kN), D/C (demand-to-capacity ratio), drift ratio (%)
- Specify material properties precisely: concrete compressive strength f'c or fck; steel yield strength fy or fyk; elastic modulus E; reinforcement ratio ρ
- Report loading combinations per applicable standards: dead load D, live load L, earthquake E, wind W, snow S; distinguish strength-level vs. service-level demands
- Employ precise failure mode terminology: flexural yielding, shear failure, lateral-torsional buckling, fatigue fracture, progressive collapse, punching shear
- Describe finite element models completely: element type (shell S4R, beam B31, solid C3D8), mesh size and refinement, material constitutive model (elastic-perfectly plastic, von Mises, Drucker-Prager), boundary conditions and contact definitions, solver type
- Report experimental results with statistical descriptors: mean, standard deviation, coefficient of variation (CoV, %), characteristic value (5th percentile), number of specimens
- Distinguish clearly between ultimate limit state (ULS) and serviceability limit state (SLS) performance criteria
- Use SI units as primary; include imperial equivalents [MPa (psi), kN (kip), mm (in.)] for journals targeting US/ASCE audience
- Apply seismic performance nomenclature consistently: immediate occupancy (IO), life safety (LS), collapse prevention (CP) per ASCE 41; fragility curves; interstory drift ratio (IDR)
- For structural health monitoring (SHM): specify sensor type (accelerometer, strain gauge, LVDT), sampling rate (Hz), signal processing method (FFT, wavelet), damage index definition

**Environmental Engineering (Energy & Carbon Emissions):**
- Follow ISO 14040/14044 terminology for Life Cycle Assessment: functional unit (clearly quantified), system boundary, life cycle inventory (LCI), life cycle impact assessment (LCIA), characterization factors
- Standardize carbon metrics with units: embodied carbon (EC, kgCO₂e/m²), operational carbon (OC, kgCO₂e/m²·yr), whole-life carbon (WLC, kgCO₂e/m²); specify assessment period
- Report emissions in CO₂-equivalent (CO₂e) and cite characterization factor source explicitly (e.g., IPCC AR6 GWP100, IPCC AR5 GWP20)
- Use energy performance indicators consistently: Energy Use Intensity (EUI, kWh/m²·yr), Primary Energy Factor (PEF), Site vs. Source energy distinction, net zero energy balance
- Apply carbon accounting framework terminology explicitly: GHG Protocol Scope 1 (direct), Scope 2 (purchased energy), Scope 3 (value chain); Science-Based Targets initiative (SBTi); carbon neutrality vs. net-zero distinction
- Employ renewable energy metrics precisely: installed capacity (MWp for solar, MW for wind), annual generation (MWh/yr), capacity factor (%), Levelized Cost of Energy (LCOE, $/MWh or ¢/kWh), Levelized Cost of Storage (LCOS)
- Reference building performance standards by version: ASHRAE 90.1-2022, PassivHaus PHI/PHIUS criteria, LEED v4.1 (with credit category), BREEAM 2018, WELL Building Standard
- Distinguish clearly between baseline, reference, and improved scenarios; quantify relative improvement as percentage reduction from a defined baseline
- Use IAQ and thermal comfort metrics consistently: PMV (Predicted Mean Vote), PPD (Predicted Percentage Dissatisfied) per ISO 7730/ASHRAE 55; CO₂ concentration (ppm) as IAQ proxy; TVOC levels (μg/m³)
- For urban/regional carbon studies: specify emission factor source (national grid, regional average, marginal), reporting boundary (geographic, organizational, project), vintage year

**Artificial Intelligence for Engineering:**
- Report neural network architecture completely: model type (CNN, GNN, Transformer, LSTM, GRU), input feature dimensionality, hidden layer configuration, activation functions, total trainable parameters
- Specify full training protocol: dataset size and split (e.g., 70/15/15 train/val/test), optimizer (Adam β₁=0.9 β₂=0.999, SGD with momentum), learning rate and schedule (cosine annealing, step decay), batch size, training epochs, early stopping criteria
- Select task-appropriate evaluation metrics and report them consistently: RMSE and R² for regression/prediction; accuracy, precision, recall, F1-score, AUC-ROC for classification; mean IoU for segmentation; never report training metrics as final performance
- Distinguish in-distribution generalization (test set from same distribution) from out-of-distribution (OOD) robustness and cross-domain transfer
- Quantify uncertainty where relevant: prediction intervals, Monte Carlo dropout uncertainty, deep ensemble variance, Bayesian posterior credible intervals
- Describe physics-informed methods precisely: PINN governing equations (specific PDE names and form), physics loss term formulation, boundary condition enforcement strategy (soft constraints vs. hard constraints), residual point sampling strategy
- Use transfer learning terminology consistently: source domain and task, target domain and task, pre-trained backbone (specify version), fine-tuning strategy (full fine-tune vs. head-only vs. adapter), frozen layer count
- Reference engineering benchmark datasets explicitly: PEER Ground Motion Database (seismic ML); Z24 bridge, LANL benchmark (SHM); DOE Commercial Building Stock (energy); NSRDB (solar resource); ERA5 (climate/weather)
- For AI-aided structural/material design: report training data source (simulation vs. experimental), feature engineering choices, and inverse design strategy

**ML Experiment Tooling & Tracking:**
- Report experiment tracking platform used: Weights & Biases (W&B), MLflow, Neptune.ai, or TensorBoard; include run IDs or dashboard links in supplementary materials for reproducibility
- Log hyperparameters comprehensively: learning rate (initial and schedule), batch size, weight decay, dropout rate, optimizer choice and its parameters (e.g., Adam β₁=0.9, β₂=0.999, ε=1e-8), number of epochs, early stopping patience and delta
- Log metrics at every evaluation interval: training/validation loss curves, task-specific metrics (accuracy, F1, BLEU, perplexity, RMSE, mAP), learning rate schedule visualization, gradient norms if diagnosing instability
- Record environment metadata: GPU model and count, CUDA/cuDNN versions, Python version, key library versions (PyTorch, TensorFlow, JAX with commit hash if building from source), container image hash or conda environment YAML
- Report model checkpoints: best checkpoint selection criterion (e.g., lowest validation loss, highest validation F1), checkpoint storage format (safetensors, PyTorch .pt, ONNX), total trainable parameter count
- Present results using a standard hyperparameter table listing each hyperparameter, its search range (if tuned), and the final selected value; include a learning curve figure showing training and validation metrics over epochs with convergence epoch annotated
- Ensure reproducibility by reporting: random seed for each stochastic component (data loading, weight initialization, augmentation, dropout), deterministic mode flag (e.g., `torch.use_deterministic_algorithms(True)`), data versioning tool (DVC, LakeFS, or Weights & Biases Artifacts) with dataset hash or version tag

**Ablation Study Writing Conventions:**
- Follow a systematic structure: (1) establish a strong baseline with all components enabled, (2) remove or modify exactly one component at a time, (3) report the impact on all primary metrics, (4) optionally test combinations of removals to detect interaction effects
- Present ablation results in a table where each row is a model variant (component removed or modified) and each column is an evaluation metric; include a "Delta from Baseline" column showing the absolute or percentage change; bold the best result and underline the worst to guide the reader's eye
- Example ablation table format:

  | Model Variant | Accuracy (%) | F1 (%) | AUC-ROC | Delta Acc. |
  |--------------|-------------|--------|---------|------------|
  | Full model (baseline) | 94.2 | 93.8 | 0.971 | -- |
  | w/o attention module | 91.5 | 90.9 | 0.953 | -2.7 |
  | w/o data augmentation | 92.1 | 91.6 | 0.960 | -2.1 |
  | w/o pretrained backbone | 88.7 | 87.3 | 0.931 | -5.5 |

- Report statistical significance for ablation comparisons: run each configuration with at least 3-5 different random seeds, report mean ± standard deviation, and conduct paired t-tests or bootstrap confidence intervals between the baseline and each ablated variant; report p-values in the table or a supplementary significance table
- Avoid common ablation pitfalls: (a) order dependency—do not sequentially remove components and report cumulative degradation, as the effect of removing component B depends on whether A was already removed; (b) confounded ablations—ensure each ablation changes exactly one factor; if two components are tightly coupled (e.g., a loss term and its weighting schedule), ablate them jointly and note the coupling; (c) oracle ablation—do not tune hyperparameters for each ablated variant separately, as this inflates the apparent contribution of the tuned component; use the same hyperparameters as the full model unless explicitly studying hyperparameter sensitivity
- For ablations involving architectural changes, report computational cost (FLOPs, parameters, inference latency) alongside accuracy to quantify efficiency-accuracy tradeoffs
- In the discussion, interpret ablation results mechanistically: explain why a component matters (or does not) based on the problem structure, not just that the number changed

**CS Conference Paper Structure:**
- Top-tier ML conferences (NeurIPS, ICML, ICLR) typically allow 8-9 pages of main content (excluding references and a limited set of allowed additional pages for acknowledgments and ethics/broader impacts); unlimited appendix and supplementary material are common but reviewers are not obligated to read them
- Main paper structure: (1) Introduction with clear contribution bullets, (2) Related Work positioning against prior art, (3) Method with formal problem setup, (4) Experiments with baselines and ablations, (5) Discussion/Limitations; omit a separate Results section—experiments and results are typically combined
- Appendix contents (reviewers may but are not required to read): full proofs and derivations, additional experimental results and sensitivity analyses, hyperparameter search details and ranges, failure case analysis and qualitative examples, dataset details and preprocessing steps, computational cost breakdown
- NeurIPS requires a Broader Impacts statement discussing potential societal consequences of the work; address both positive applications and potential misuse; be specific rather than generic—avoid "this could be used for good or bad" without elaboration
- NeurIPS and ICML require a Reproducibility Checklist (available as a LaTeX template) covering: code availability, compute requirements, experimental details (seeds, hyperparameters, data splits), and a link to a reproducibility package; fill this out honestly—reviewers check it
- ACM full papers (CHI, KDD, SIGMOD, WWW): 10 pages plus unlimited references; short papers (CHI LBW, SIGMOD demos): 4 pages; follow ACM `acmart` document class with `sigconf` or `sigplan` format; CCS concepts and keywords are mandatory
- For double-blind review (NeurIPS, ICML, ICLR, CHI, ACM venues): anonymize all self-references that reveal identity, remove author names from supplementary code, anonymize URLs to project pages; do not post to arXiv until after the review period if the venue policy prohibits it
- Contribution bullets in the introduction should be specific and verifiable: "We propose X, a method that achieves Y" not "We make several contributions"; each bullet should map to a concrete section or experiment in the paper

**Adversarial Robustness & Fairness Reporting:**
- When claiming model robustness, evaluate against standard adversarial attacks: PGD (Projected Gradient Descent) with ε, step size α, and number of steps T specified (e.g., PGD-20 with ε=8/255, α=2/255 under L∞ norm); AutoAttack (Croce & Hein, 2020) as a parameter-free robustness benchmark; specify the threat model explicitly: norm (L∞, L2, L1), perturbation budget ε, and whether attacks are white-box or black-box
- Report robustness as adversarial accuracy (accuracy on adversarially perturbed test inputs), not just clean accuracy; present a robustness-accuracy tradeoff curve by varying ε; compare against adversarial training baselines (Madry et al., 2018) and certified defense bounds where applicable
- For fairness evaluation, compute and report disaggregated metrics across protected groups (defined by sensitive attributes such as race, gender, age): demographic parity (equal positive prediction rate across groups), equalized odds (equal TPR and FPR across groups), calibration (equal PPV across groups), and predictive parity
- Present fairness results using per-group performance breakdown tables: each row is a demographic group, columns are accuracy, TPR, FPR, PPV, and sample size; include a summary row showing the maximum disparity across groups
- Visualize fairness-accuracy tradeoff curves: plot model accuracy on the x-axis and fairness metric (e.g., demographic parity difference) on the y-axis, showing the Pareto frontier of achievable operating points; compare against fairness-aware baselines (e.g., equalized odds post-processing, reweighting)
- Report intersectional fairness where sample size permits: evaluate combinations of protected attributes (e.g., Black women vs. white men) rather than single attributes in isolation, as single-attribute analysis can mask disparities in intersectional subgroups
- Discuss fairness interventions applied: pre-processing (resampling, reweighting), in-processing (fairness constraints in loss function, adversarial debiasing), post-processing (threshold adjustment, calibration); report the fairness-accuracy cost of each intervention
- When fairness or robustness is not the paper's primary contribution, include at minimum a brief evaluation paragraph and reference to supplementary materials with full results; omitting robustness/fairness evaluation entirely in applied ML papers is increasingly viewed as a weakness by reviewers

**LLM-Specific Reporting:**
- Document prompt templates exhaustively: include the full system prompt, all user/assistant few-shot examples (with exact wording), and any instruction formatting (XML tags, markdown headers, special tokens); report prompt template version and any prompt engineering iterations conducted; store prompts as code artifacts in the supplementary repository
- Report token-level details: maximum context length used, typical input/output token counts, temperature and top-p settings for generation, stop sequences, and whether sampling or greedy decoding was used
- Conduct and report data contamination checks: (a) perplexity-based detection—compute model perplexity on test set passages and compare to a reference distribution; unexpectedly low perplexity suggests memorization; (b) n-gram overlap—check for 13-gram or longer overlaps between training corpus (if disclosed) and evaluation benchmarks using methods from Brown et al. (2020) and the HELM contamination framework; (c) membership inference—apply Min-K% Prob (Shi et al., 2024) or similar methods to flag potential test set leakage
- For human evaluation protocols: define the evaluation task precisely (pairwise preference, Likert scale, best-worst scaling), specify annotator qualifications and training, report number of annotators per item (minimum 3 for reliability), compute inter-annotator agreement using Cohen's κ (2 annotators) or Fleiss' κ / Krippendorff's α (3+ annotators); report κ values and interpret: <0.20 = poor, 0.21-0.40 = fair, 0.41-0.60 = moderate, 0.61-0.80 = substantial, >0.80 = almost perfect agreement
- Select benchmarks appropriate to the task domain: general capability—HELM (Holistic Evaluation of Language Models), BigBench-Hard, MMLU, ARC, HellaSwag; reasoning—GSM8K, MATH, BBH, LogiQA; code—HumanEval, MBPP, SWE-bench; domain-specific—MedQA/PubMedQA (biomedical), LegalBench (legal), SciQ (science); report results on at least one established public benchmark to enable comparison with prior work
- Report LLM-specific failure modes: hallucination rate (if measurable), refusal rate, sensitivity to prompt phrasing (test at least 2-3 paraphrases of key prompts), and performance degradation on out-of-distribution inputs; include qualitative examples of failure cases in the appendix
- For instruction-tuned or RLHF-trained models, report the training data composition (if disclosed), the reward model details, and any safety evaluations conducted; for API-only models (GPT-4, Claude), report the model version identifier, API snapshot date, and any known limitations documented by the provider

**Reporting Standards for Engineering Studies:**
- **Computational studies**: Report solver, version, mesh convergence study, validation against analytical solutions or experimental data
- **Experimental studies**: Report instrumentation accuracy, calibration procedures, environmental conditions, number of specimens/tests
- **LCA studies**: Follow ISO 14044 §5 for reporting; declare software tool (SimaPro, OpenLCA, One Click LCA) and background database (ecoinvent 3.x, GaBi)
- **Energy simulation**: Declare software and version (EnergyPlus v23.2, DesignBuilder, OpenStudio), weather file (TMY3, EPW source), simulation timestep, convergence criteria
- **Carbon footprint studies**: Declare assessment standard (GHG Protocol, ISO 14064-1), emission factor database, reporting year, organizational/operational boundary

**Neuroscience:**
- Use standardized brain region nomenclature (e.g., refer to atlases like Allen Brain Atlas)
- Specify coordinates for brain regions using established stereotaxic systems
- Follow conventions for neural terminology (e.g., "action potential" not "spike" in formal writing)
- Use "neural activity," "neuronal firing," "brain activation" appropriately based on measurement method
- Describe recording techniques with proper specificity (e.g., "whole-cell patch clamp," "extracellular recording")

**Social and Behavioral Sciences:**
- Use person-first language when appropriate (e.g., "people with schizophrenia" not "schizophrenics")
- Employ standardized psychological constructs and validated assessment names
- Follow APA guidelines for reducing bias in language
- Specify theoretical frameworks using established terminology
- Use "participants" rather than "subjects" for human research

**General Principles:**

**Match Audience Expertise:**
- For specialized journals: Use field-specific terminology freely, define only highly specialized or novel terms
- For broad-impact journals (e.g., *Nature*, *Science*): Define more technical terms, provide context for specialized concepts
- For interdisciplinary audiences: Balance precision with accessibility, define terms at first use

**Define Technical Terms Strategically:**
- Define abbreviations at first use: "messenger RNA (mRNA)"
- Provide brief explanations for specialized techniques when writing for broader audiences
- Avoid over-defining terms well-known to the target audience (signals unfamiliarity with field)
- Create a glossary if numerous specialized terms are unavoidable

**Maintain Consistency:**
- Use the same term for the same concept throughout (don't alternate between "medication," "drug," and "pharmaceutical")
- Follow a consistent system for abbreviations (decide on "PCR" or "polymerase chain reaction" after first definition)
- Apply the same nomenclature system throughout (especially for genes, species, chemicals)

**Avoid Field Mixing Errors:**
- Don't use clinical terminology for basic science (e.g., don't call mice "patients")
- Avoid colloquialisms or overly general terms in place of precise field terminology
- Don't import terminology from adjacent fields without ensuring proper usage

**Verify Terminology Usage:**
- Consult field-specific style guides and nomenclature resources
- Check how terms are used in recent papers from the target journal
- Use domain-specific databases and ontologies (e.g., Gene Ontology, MeSH terms)
- When uncertain, cite a key reference that establishes terminology

### 10. Common Pitfalls to Avoid

**Top Rejection Reasons:**
1. Inappropriate, incomplete, or insufficiently described statistics
2. Over-interpretation of results or unsupported conclusions
3. Poorly described methods affecting reproducibility
4. Small, biased, or inappropriate samples
5. Poor writing quality or difficult-to-follow text
6. Inadequate literature review or context
7. Figures and tables that are unclear or poorly designed
8. Failure to follow reporting guidelines

**Writing Quality Issues:**
- Mixing tenses inappropriately (use past tense for methods/results, present for established facts)
- Excessive jargon or undefined acronyms
- Paragraph breaks that disrupt logical flow
- Missing transitions between sections
- Inconsistent notation or terminology

## Workflow for Manuscript Development

**Stage 1: Planning**
1. Identify target journal and review author guidelines
2. Determine applicable reporting guideline (CONSORT, STROBE, etc.)
3. Outline manuscript structure (usually IMRAD)
4. Plan figures and tables as the backbone of the paper

**Stage 2: Drafting** (Use two-stage writing process for each section)
1. Start with figures and tables (the core data story)
2. For each section below, follow the two-stage process:
   - **First**: Create outline with bullet points using research-lookup
   - **Second**: Convert bullet points to full paragraphs with flowing prose
3. Write Methods (often easiest to draft first)
4. Draft Results (describing figures/tables objectively)
5. Compose Discussion (interpreting findings)
6. Write Introduction (setting up the research question)
7. Craft Abstract (synthesizing the complete story as **flowing paragraph(s)**, not labeled sections)
8. Create Title (concise and descriptive)

**Remember**: Bullet points are for planning only—the final manuscript must be in complete paragraphs.

**Stage 3: Revision**
1. Check logical flow and "red thread" throughout
2. Verify consistency in terminology and notation
3. Ensure figures/tables are self-explanatory
4. Confirm adherence to reporting guidelines
5. Verify all citations are accurate and properly formatted
6. Check word counts for each section
7. Proofread for grammar, spelling, and clarity

**Stage 4: Final Preparation**
1. Format according to journal requirements
2. Prepare supplementary materials
3. Write cover letter highlighting significance
4. Complete submission checklists
5. Gather all required statements and forms

## Integration with Other Scientific Skills

This skill works effectively with:
- **Data analysis skills**: For generating results to report
- **Statistical analysis**: For determining appropriate statistical presentations
- **Literature review skills**: For contextualizing research
- **Figure creation tools**: For developing publication-quality visualizations
- **Venue-templates skill**: For venue-specific writing styles and formatting

### Venue-Specific Writing Styles

**Before writing for a specific venue, consult the venue-templates skill for writing style guides:**

Different venues have dramatically different writing expectations:
- **Nature/Science**: Accessible, story-driven, broad significance
- **Cell Press**: Mechanistic depth, graphical abstracts, Highlights
- **Medical journals (NEJM, Lancet)**: Structured abstracts, evidence language
- **ML conferences (NeurIPS, ICML)**: Contribution bullets, ablation studies
- **CS conferences (CHI, ACL)**: Field-specific conventions

The venue-templates skill provides:
- `venue_writing_styles.md`: Master style comparison
- Venue-specific guides: `nature_science_style.md`, `cell_press_style.md`, `medical_journal_styles.md`, `ml_conference_style.md`, `cs_conference_style.md`
- `reviewer_expectations.md`: What reviewers look for at each venue
- Writing examples in `assets/examples/`

**Workflow**: First use this skill for general scientific writing principles (IMRAD, clarity, citations), then consult venue-templates for venue-specific style adaptation.

## References

This skill includes comprehensive reference files covering specific aspects of scientific writing:

- `references/imrad_structure.md`: Detailed guide to IMRAD format and section-specific content
- `references/citation_styles.md`: Complete citation style guides (APA, AMA, Vancouver, Chicago, IEEE)
- `references/figures_tables.md`: Best practices for creating effective data visualizations
- `references/reporting_guidelines.md`: Study-specific reporting standards and checklists
- `references/writing_principles.md`: Core principles of effective scientific communication

**For venue-specific writing styles** (tone, voice, abstract format, reviewer expectations), see the **venue-templates** skill which provides comprehensive style guides for Nature/Science, Cell Press, medical journals, ML conferences, and CS conferences.

Load these references as needed when working on specific aspects of scientific writing.

---

## Engineering Research Study Types

### Citing Chinese Engineering Standards in English-Language Papers

When Chinese standards (GB, GB/T, JGJ, CECS, DBJT, DB) are the governing design codes:

**In-text reference format:**
- "...per the Chinese Code for Seismic Design of Buildings (GB 50011-2010, 2016 revision)..."
- "...following the Technical Specification for Concrete Structures of Tall Buildings (JGJ 3-2010)..."

**Common standards by subdomain:**
| Domain | Standard | Full Title |
|--------|----------|-----------|
| Seismic design | GB 50011-2010 | Code for Seismic Design of Buildings |
| Concrete structures | GB 50010-2010 | Code for Design of Concrete Structures |
| Steel structures | GB 50017-2017 | Standard for Design of Steel Structures |
| Foundation | GB 50007-2011 | Code for Design of Building Foundations |
| Tall buildings | JGJ 3-2010 | Technical Specification for Concrete Structures of Tall Buildings |
| Composite structures | JGJ 138-2016 | Code for Design of Composite Structures |
| LCA / buildings | GB/T 51366-2019 | Standard for Building Carbon Emission Calculation |
| Green buildings | GB/T 50378-2019 | Assessment Standard for Green Building |
| Energy efficiency | GB 50189-2015 | Design Standard for Energy Efficiency of Public Buildings |
| Structural testing | GB/T 50152-2012 | Standard for Test Methods of Concrete Structures |
| Environmental impact | GB/T 24040-2008 | Life Cycle Assessment — Principles and Framework |

**Writing conventions:**
- Always provide English translation of standard title in parentheses on first use
- Include year of standard; note revision year if applicable (e.g., "2010, 2016 revision")
- For international journals: add a footnote or parenthetical noting the issuing body (Ministry of Housing and Urban-Rural Development, MOHURD; Standardization Administration of China, SAC)
- When comparing with Eurocode or ASCE: explicitly state equivalence or difference in safety factors, load combinations, or limit states

---

### Numerical Simulation–Only Papers (No Physical Experiments)

**Paper structure:**
1. Introduction — state why simulation is appropriate (cost, scale, hazard, parametric coverage)
2. Model Description — geometry, material models, element types, boundary/loading conditions
3. Validation — comparison with: (a) analytical solutions, (b) published experimental benchmarks, (c) code-prescribed limits
4. Parametric Study — design of experiment (DOE), parameter ranges, response variables
5. Results & Discussion — response surfaces, sensitivity rankings, governing mechanisms
6. Conclusions — design recommendations, limitations of the simulation approach

**Mandatory reporting items:**
- **Solver & version**: OpenSees 3.5.0, ANSYS Mechanical 2023 R1, ABAQUS 6.14, SAP2000 v24, EnergyPlus 23.1, etc.
- **Element type & mesh**: element formulation (beam-column, shell, solid), mesh size, integration scheme
- **Mesh convergence study**: ≥3 mesh densities; report key response metric vs. mesh size; state convergence criterion (e.g., <2% change)
- **Material models**: name the constitutive model (e.g., Concrete02, Steel02 in OpenSees; Mander confined concrete); cite the source paper
- **Time step / load increment**: for dynamic analyses, state Δt and justify (Δt ≤ T_min/10); for nonlinear static, state load increment and convergence tolerance
- **Validation benchmark**: cite the experimental study used; report RMSE, MAE, or percent error for key response quantities

**Common validation strategies (no own experiments):**
- Compare to closed-form solutions (Euler buckling, Timoshenko beam, heat equation)
- Reproduce published experimental results (clearly cite; state which parameter set used)
- Cross-validate with a different software (e.g., OpenSees vs. SAP2000 eigenvalue)
- Compare to code-prescribed simplified methods as upper/lower bounds

**Language for simulation limitations:**
- "The model assumes linear elastic material behavior beyond the validated strain range of..."
- "Three-dimensional effects and out-of-plane buckling modes are not captured in the 2D frame model..."
- "Soil-structure interaction is not included; fixed-base assumption may overestimate natural frequency by..."

---

### Experimental–Only Papers (Physical Testing Without Companion Simulation)

**Paper structure:**
1. Introduction — gap in experimental data; hypothesis to be tested
2. Experimental Programme — specimen design, material characterization, test matrix
3. Test Setup & Instrumentation — loading apparatus, support conditions, measurement system
4. Test Procedure — loading protocol (monotonic / cyclic / dynamic), rate, environmental conditions
5. Results — raw data reduction, representative curves, failure modes
6. Discussion — mechanism interpretation, comparison with existing data/code predictions
7. Conclusions — design implications, data availability statement

**Mandatory reporting items:**
- **Specimen details**: dimensions, reinforcement ratio, concrete/steel grade with actual (measured) properties
- **Material testing**: report coupon test results (mean ± CoV) for steel; cylinder/cube tests for concrete; cite test standard (ASTM C39, ISO 6892-1, GB/T 228.1)
- **Instrumentation**: sensor type, range, accuracy, sampling rate; calibration date; data acquisition system
- **Loading protocol**: cite standard if applicable (e.g., ATC-24 for cyclic loading; FEMA 461; ISO 24153)
- **Measurement uncertainty**: state expanded uncertainty (k=2, 95% confidence) for primary response quantities
- **Environmental conditions**: temperature (°C ± range), humidity (%), if relevant to material behavior

**Error analysis and uncertainty propagation:**
- Identify primary uncertainty sources: material variability, geometric tolerances, load application, sensor accuracy
- Report combined uncertainty using RSS (root sum of squares) method: u_c = √(u₁² + u₂² + u₃²...)
- For repeated specimens (N≥3): report mean ± standard deviation; coefficient of variation (CoV)
- Flag outliers: justify inclusion/exclusion using Grubbs test or Dixon Q-test

**Common replication statements:**
- "Three nominally identical specimens were tested; results are reported as mean ± one standard deviation"
- "The test was repeated twice; the coefficient of variation of peak load was X%, confirming repeatability"

---

### Combined Numerical + Experimental Papers (Most Common High-Impact Format)

**Recommended paper structure (two-track narrative):**
1. Introduction — dual motivation: experimental insight + predictive modeling capability
2. Experimental Programme — (same as Experimental-Only §2–4 above)
3. Experimental Results — primary data; failure modes; key response quantities
4. Numerical Model Development — geometry, materials, element types, boundary conditions
5. Model Calibration & Validation — fit model to experimental data; report goodness of fit
6. Parametric / Extended Study — use validated model to explore parameter space beyond tested range
7. Discussion — unified interpretation of experimental + simulation findings
8. Conclusions — design recommendations based on combined evidence

**Model calibration section (critical — often missing in weak papers):**
- State which parameters were calibrated and which were fixed from material tests
- Report calibration objective: "The concrete tensile strength f_t and fracture energy G_f were calibrated by minimizing the RMSE between simulated and measured load-displacement curves"
- Show calibration convergence: plot simulated vs. experimental for at least 2 specimens
- Report goodness-of-fit metrics: RMSE, MAE, R², percent error at peak load and at failure displacement
- State validation: "The calibrated model was validated against the remaining N specimens without further parameter adjustment"

**Presenting simulation–experiment correlation:**
- Plot simulated and experimental curves on the same axes (use consistent color/line style conventions)
- Report: Peak load error (%), Initial stiffness error (%), Post-peak slope error (%)
- For dynamic/seismic: compare natural frequencies, mode shapes (MAC value), hysteresis loops
- Language: "The model predicts peak capacity within X% of the experimental mean across all specimens"

**Uncertainty handling for combined studies:**
- Distinguish: (a) experimental measurement uncertainty, (b) model parameter uncertainty, (c) model-form uncertainty
- If using Monte Carlo or sensitivity analysis: state which uncertain parameters were varied and their distributions
- Report: "The 95% prediction interval of the model envelopes X% of the experimental data points"

**Parametric study — clearly separate from validation:**
- Explicitly state: "The following parametric study uses the validated model; results are not directly measured experimentally"
- Justify parameter ranges: based on code limits, practical construction ranges, or literature
- Use design of experiment (DOE) if >3 parameters: full factorial, Latin hypercube, or Taguchi L-array; cite method

---

### CS+Biomedical Paper Structure

Papers at the intersection of computer science and biomedical research require structures that serve both technical rigor and clinical relevance. Adapt the following templates to the specific subdomain.

#### ML for Medical Imaging Papers

**Paper structure:**
1. **Introduction** — Clinical problem significance, current diagnostic workflow and limitations, prior AI approaches and their gaps
2. **Related Work** — Review of deep learning architectures for the imaging task, comparison of prior methods, identification of remaining challenges (generalizability, interpretability, annotation cost)
3. **Data and Preprocessing** — Dataset description (source institution(s), inclusion/exclusion criteria, annotation protocol with inter-annotator agreement), image preprocessing (normalization, augmentation, resolution), train/validation/test split strategy (patient-level, not image-level to prevent data leakage)
4. **Model Architecture** — Network architecture diagram and detailed description (backbone, head, loss function), training protocol (optimizer, learning rate schedule, batch size, epochs, hardware), hyperparameter selection strategy
5. **Training Protocol** — Loss functions, optimization strategy, regularization, augmentation policies, class imbalance handling
6. **Results** — Primary metrics (AUC, sensitivity, specificity, PPV, NPV with 95% confidence intervals), ROC curves, confusion matrices, calibration plots, subgroup analysis (age, sex, scanner type, institution), comparison with radiologist baseline or existing clinical tools
7. **Clinical Interpretation** — Attention maps / Grad-CAM / SHAP visualizations showing model focus regions, failure case analysis, decision curve analysis demonstrating clinical utility
8. **Discussion** — Comparison with state of the art, clinical workflow integration considerations, limitations (dataset size, generalizability, annotation quality), regulatory and deployment considerations, future directions

**Mandatory reporting items:**
- Reporting guideline: **CLAIM** (Checklist for Artificial Intelligence in Medical Imaging)
- Dataset: source, size, annotation protocol, inter-annotator agreement (Cohen's kappa or Fleiss' kappa)
- Validation: internal validation + external validation on independent dataset (different institution/scanner/population)
- Metrics: AUC with DeLong 95% CI, sensitivity, specificity, PPV, NPV, F1; calibration (Hosmer-Lemeshow or Brier score)
- Interpretability: attention map / Grad-CAM visualization for representative cases (true positives, false positives, false negatives)
- Fairness: subgroup performance analysis by demographic variables (age, sex, race/ethnicity) and clinical variables (disease severity, comorbidities)
- Comparison: statistical comparison with radiologist(s) using McNemar's test or paired DeLong test for AUC comparison

#### Computational Drug Discovery Papers

**Paper structure:**
1. **Introduction** — Biological target significance, current therapeutic landscape, limitations of traditional drug discovery (cost, time, attrition), prior computational approaches
2. **Target Selection** — Target rationale (druggability, disease association, structural availability), binding site characterization, known ligand landscape
3. **Molecular Representation** — Input features (SMILES, molecular graphs, 3D pharmacophore fingerprints, protein structure), featurization details, preprocessing steps
4. **Model** — Architecture (GNN, transformer, 3D-CNN), training data (ChEMBL, PDBbind, BindingDB), loss function, training protocol, hyperparameter optimization
5. **Virtual Screening** — Screening library description, filtering pipeline, ranking criteria, hit selection strategy
6. **Experimental Validation** — Biochemical assay protocol, dose-response curves (IC50/EC50), selectivity profiling, ADMET assays (metabolic stability, permeability, cytotoxicity), structural confirmation (NMR, X-ray crystallography if available)
7. **Discussion** — Structure-activity relationship analysis, comparison with docking baselines and prior ML methods, limitations (dataset bias, domain of applicability, synthetic feasibility), next steps for lead optimization

**Mandatory reporting items:**
- Training data: source database, size, date, activity type (IC50, Ki, Kd), train/test split strategy (scaffold-based split recommended)
- Metrics: enrichment factors at 1%/5%/10% hit rates, AUROC for virtual screening, Pearson/Spearman correlation for binding affinity prediction
- Validation: experimental hit rate (synthesized compounds / predicted actives), dose-response confirmation
- ADMET: report at minimum metabolic stability, aqueous solubility, and membrane permeability for confirmed hits
- Baselines: comparison with molecular docking (AutoDock, Glide, GOLD) and/or 2D-QSAR models

#### Genomics/Bioinformatics ML Papers

**Paper structure:**
1. **Introduction** — Disease/genomic question significance, prior biomarker/gene signature studies, limitations of existing approaches
2. **Data and Cohorts** — Cohort descriptions (TCGA, GEO, institutional biobank), sample size, clinical variables, omics data type (WES, RNA-seq, methylation, proteomics), quality control steps
3. **Feature Engineering** — Feature selection method (LASSO, elastic net, random forest, mutual information, differential expression), dimensionality reduction strategy, biological filtering
4. **Model** — Algorithm selection and justification, cross-validation strategy (k-fold, nested CV, leave-one-cohort-out), hyperparameter tuning, regularization
5. **Results** — Primary outcome prediction (survival: HR, concordance index; classification: AUC, accuracy), Kaplan-Meier survival curves with log-rank test, feature importance rankings, pathway enrichment analysis (GO, KEGG, Reactome)
6. **Validation** — Independent cohort validation (geographically, temporally, or technologically independent), comparison with existing signatures/prognostic scores
7. **Biological Interpretation** — Gene set enrichment, pathway analysis, interaction network visualization, literature validation of top features

**Mandatory reporting items:**
- Reporting guideline: **TRIPOD+AI** (for prediction models)
- Cross-validation: nested k-fold or train/validation/test with independent holdout; report mean and standard deviation across folds
- Survival analysis: Cox proportional hazards with HR and 95% CI, Kaplan-Meier with log-rank p-value, concordance index
- Pathway enrichment: adjusted p-value (FDR/Bonferroni), enrichment score, leading-edge analysis
- Feature stability: report feature selection consistency across bootstrap resamples or cross-validation folds

#### Clinical NLP/Text Mining Papers

**Paper structure:**
1. **Introduction** — Clinical text processing challenge, scale of unstructured EHR data, prior NLP approaches and their limitations
2. **Data** — Corpus description (source, size, document types), annotation schema, annotation process (annotators, training, adjudication), inter-annotator agreement (Cohen's kappa, Fleiss' kappa)
3. **Methods** — NLP task definition (NER, relation extraction, classification, de-identification), model architecture (BERT/BioBERT/ClinicalBERT, rule-based hybrid), training protocol, preprocessing (tokenization, sentence splitting, section detection)
4. **Results** — Precision, recall, F1-score (micro and macro), confusion matrix, error analysis by entity/relation type, comparison with baseline systems
5. **Validation** — Temporal validation (train on older notes, test on newer), cross-institutional validation, generalizability assessment
6. **Discussion** — Error taxonomy and failure modes, bias assessment (demographic subgroups, document types), downstream task utility, deployment considerations

**Mandatory reporting items:**
- Inter-annotator agreement: Cohen's kappa (2 annotators) or Fleiss' kappa (>2 annotators) for each entity/relation type
- NER metrics: entity-level precision, recall, F1 (exact match and partial match)
- Bias assessment: performance stratified by patient demographics (age, sex, race/ethnicity) and document characteristics (department, note type)
- Temporal validation: performance on notes from different time periods than training data
- De-identification: if applicable, report HIPAA safe harbor compliance and re-identification risk assessment

#### Reporting Standards for CS+Biomedical Studies

All CS+Biomedical papers should reference the applicable reporting guideline:

| Guideline | Scope | Key Items |
|-----------|-------|-----------|
| **TRIPOD+AI** | Prediction/prognosis models | Model development, validation, calibration, discrimination, clinical utility |
| **CLAIM** | Medical imaging AI | Data annotation, model architecture, training, evaluation, interpretability |
| **SPIRIT-AI** | Clinical trial protocols for AI interventions | Intervention description, outcomes, participant selection, data acquisition |
| **CONSORT-AI** | Clinical trial reports for AI interventions | Randomization, blinding, outcomes, adverse events, AI intervention details |
| **DECIDE-AI** | Early-stage clinical AI | Technical performance, human factors, clinical safety |
