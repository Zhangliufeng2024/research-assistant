# Engineering Journal Writing Styles

Writing style guidance for major civil, structural, environmental, energy, and AI/computational engineering journals.

---

## ASCE Journals

**Covers:** Journal of Structural Engineering, Journal of Bridge Engineering, Journal of Engineering Mechanics, Journal of Geotechnical and Geoenvironmental Engineering, Journal of Computing in Civil Engineering, Journal of Environmental Engineering, Structural Health Monitoring (SAGE/ASCE), Natural Hazards Review

### Abstract Style
- ≤250 words, unstructured
- Must include: problem statement, objectives, methods, key quantitative results, conclusions
- State specific numbers (e.g., "23% increase in lateral stiffness", "RMSE = 0.045")
- Avoid abbreviations, references, and math in abstract

### Writing Style
- Third person, passive or active voice both acceptable
- Precise and technical; avoid qualitative superlatives ("very", "significantly") without numbers
- Define all abbreviations at first use
- SI units mandatory; US customary units may be added in parentheses
- All equations numbered sequentially: $(1), (2), \ldots$

### Structure
1. **Introduction**: Context → literature review → gap → objectives → organization
2. **Theory / Background** *(optional)*: Analytical or theoretical foundation
3. **Methodology / Experimental Program / Numerical Model**: Detailed enough for replication
4. **Results**: Quantitative, organized by finding not by method
5. **Discussion**: Interpretation, comparison with literature, practical implications, limitations
6. **Conclusions**: Numbered list, ≤6 items, each concise and quantitative
7. **Data Availability Statement** *(required since 2022)*
8. **Acknowledgments**
9. **References**

### Citation Style
- Author-year: `(Smith and Jones 2020)` or `Smith and Jones (2020) showed that...`
- Three or more authors: `(Smith et al. 2020)`
- Multiple citations: `(Smith 2020; Jones 2021; Lee 2022)`
- Reference list: alphabetical by first author surname

### Reference Format
```
Smith, J. A., and Jones, M. B. (2021). "Seismic performance of RC walls."
  J. Struct. Eng. 147(3), 04021010. https://doi.org/10.1061/(ASCE)ST.1943-541X.0002934

Author, F. M. (Year). Book Title, Publisher, City.

Author, F. M., and Author, S. G. (Year). "Chapter title." Book Title,
  Editor, F. M., ed., Publisher, City, Pages.
```

### Key Requirements
- Figures: TIFF or EPS, ≥300 dpi (600 dpi for line art)
- Tables: editable format, not images
- Equations: all variables defined immediately after introduction
- Design code references: ASCE 7-22, ASCE 41-17, ACI 318-19, AISC 360-22, AISC 341-22, Eurocode 2/3/8

### Template
`assets/journals/asce_journal.tex`

---

## Elsevier Engineering Journals

**Covers:** Engineering Structures, Applied Energy, Energy and Buildings, Building and Environment, Construction and Building Materials, Automation in Construction, Computer Methods in Applied Mechanics and Engineering (CMAME), Mechanical Systems and Signal Processing (MSSP), Renewable Energy, Journal of Cleaner Production, Structural Safety, Thin-Walled Structures, Resources Conservation and Recycling

### Abstract Style
- 200–250 words, unstructured (some journals accept structured: Background / Methods / Results / Conclusions)
- 4–8 keywords; do not repeat words already in the title
- Highlight the research gap, specific objectives, methodology, and quantitative findings

### Writing Style
- Active voice preferred in Elsevier guidelines; readable and accessible to an interdisciplinary audience
- Concise; avoid padding and repetition between sections
- Use "the present study" or "this work" rather than "this paper" (style varies by journal)
- Quantify claims: "reduced by 23%" not "substantially reduced"

### Structure
1. **Introduction**: Background → prior work → gap → contribution (usually bullet-pointed at end)
2. **Materials and Methods / Methodology**: Sub-sectioned by analysis step
3. **Results**: Figures and tables; factual presentation without interpretation
4. **Discussion**: Interpretation, limitations, comparison, practical significance
5. **Conclusions**: Numbered list preferred; concise and quantitative
6. **CRediT Author Contribution Statement** *(required since 2020)*
7. **Declaration of Competing Interest** *(required)*
8. **Data Availability** *(required)*
9. **Acknowledgements**
10. **References**

### Citation Style
- Numbered sequential: `[1]`, `[2]`, `[1,3,5]`
- In-text: `Smith et al. [1] reported that...` or `as shown in previous studies [1–3]`
- Reference list: sorted by order of appearance

### Reference Format
```
[1] A. Smith, B. Jones, C. Lee, Life-cycle carbon assessment of high-performance envelopes,
    J. Clean. Prod. 280 (2021) 124320. https://doi.org/10.1016/j.jclepro.2020.124320

[2] A. Author, Book Title, Publisher, City, Year.
```

### Key Requirements
- `elsarticle` LaTeX class (CTAN) or Word template from journal homepage
- Highlights: 3–5 bullet points, ≤85 characters each (appears on journal website)
- Graphical abstract: 1 image (400–1333 pixels wide, ≤16 MB, no text overlay)
- CRediT taxonomy: Conceptualization, Methodology, Software, Validation, Formal analysis, Investigation, Resources, Data Curation, Writing – Original Draft, Writing – Review & Editing, Visualization, Supervision, Project administration, Funding acquisition
- Open access: CCBY license option available; check journal's APC policy

### Template
`assets/journals/elsevier_engineering.tex`

---

## IEEE Engineering Journals and Transactions

**Covers:** IEEE Transactions on Power Systems, IEEE Transactions on Smart Grid, IEEE Transactions on Industrial Electronics, IEEE Transactions on Sustainable Energy, IEEE Access, IEEE Journal of Selected Topics in Signal Processing

### Abstract Style
- ≤200 words, unstructured
- Index terms (keywords): 3–5 from IEEE Taxonomy

### Writing Style
- Formal, third-person passive or active voice
- Two-column final format; single-column for submission using `IEEEtran` class
- Math-heavy; use `\begin{equation}` with all variables defined

### Structure
1. **Introduction** *(Roman numeral sections)*
2. **Problem Formulation**
3. **Proposed Method**
4. **Simulation / Experimental Results**
5. **Conclusion**
6. **Appendix** *(if needed)*
7. **References**

### Citation Style
- Numbered in brackets: `[1]`, `[2]`
- IEEE reference format (abbreviated journal names, no "et al." for ≤6 authors)

### Reference Format
```
[1] J. A. Smith and M. B. Jones, "Title of article," IEEE Trans. Power Syst.,
    vol. 36, no. 2, pp. 1234–1245, Mar. 2021, doi: 10.1109/TPWRS.2020.3012345.
```

### Template
Use official `IEEEtran` class: `\documentclass[journal]{IEEEtran}`

---

## Applied Energy / Energy Journal (Elsevier) — Specific Notes

**Energy-specific requirements:**
- Clearly state energy scope: heating, cooling, lighting, plug loads, or whole-building
- Report EUI in both SI (\si{\kilo\watt\hour\per\meter\squared\per\year}) and imperial (\si{\kilo\btu\per\foot\squared\per\year}) for international readability
- Declare primary energy factor (PEF) and grid emission factor (GEF) source and vintage
- LCA studies: follow ISO 14040/14044; declare functional unit and system boundary in Methods
- Energy simulation: state software version, weather file (EPW/TMY3), ASHRAE climate zone, and HVAC system type

---

## Journal of Cleaner Production / Resources Conservation and Recycling — Specific Notes

**Sustainability-specific requirements:**
- GHG reporting: follow GHG Protocol; declare Scope 1/2/3 boundary
- Emission factors: cite IPCC AR6 GWP100 values; state vintage year of emission factors
- LCA: ecoinvent/GaBi database version required; allocation method justified
- Carbon neutrality/net-zero claims: define baseline, accounting period, and additionality
- Policy implications: explicitly discuss alignment with SDGs, Paris Agreement, or national carbon neutrality targets

---

## Journal of Structural Engineering (ASCE) — Specific Notes

**Structural-specific requirements:**
- Design code edition must be stated: ASCE 7-22, ACI 318-19, AISC 360-22, Eurocode 2/3/8 with year
- Seismic performance: classify using FEMA performance levels (IO, LS, CP) or ASCE 41 criteria
- FEM validation: mandatory comparison with at least one experimental dataset or analytical solution
- Statistical reporting: report mean ± standard deviation for repeated tests; confidence intervals for prediction

---

## Structural Health Monitoring (SAGE) — Specific Notes

**SHM-specific requirements:**
- Sensor description: type, manufacturer, sampling rate, dynamic range, calibration reference
- Signal processing: clearly describe filtering, windowing, and feature extraction pipeline
- Damage indices: define metric mathematically; state sensitivity and threshold selection rationale
- Field deployment: describe monitoring duration, environmental variability, and data quality control
- Benchmark dataset: cite if using Z24 Bridge, ASCE SHM Benchmark, or Los Alamos datasets

---

## Writing Style Comparison Table

| Aspect | ASCE | Elsevier Engineering | IEEE |
|--------|------|---------------------|------|
| Citation style | Author-year | Numbered [n] | Numbered [n] |
| Abstract length | ≤250 words | 200–250 words | ≤200 words |
| Units | SI (mandatory) | SI (mandatory) | SI preferred |
| Conclusion style | Numbered list | Numbered list | Prose paragraph |
| Figure format | TIFF/EPS ≥300 dpi | TIFF/EPS ≥300 dpi | TIFF/EPS ≥300 dpi |
| Highlights | Not required | 3–5 bullets | Not required |
| Graphical abstract | Not standard | Required (some journals) | Not required |
| CRediT statement | Not required | Required | Not required |
| Data availability | Required | Required | Encouraged |
| LaTeX class | `article` + `natbib` | `elsarticle` | `IEEEtran` |
