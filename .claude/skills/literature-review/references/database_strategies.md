# Literature Database Search Strategies

This document provides comprehensive guidance for searching multiple literature databases systematically and effectively.

## Available Databases and Skills

### Biomedical & Life Sciences

#### PubMed / PubMed Central
- **Access**: Use `gget` skill or WebFetch tool
- **Coverage**: 35M+ citations in biomedical literature
- **Best for**: Clinical studies, biomedical research, genetics, molecular biology
- **Search tips**: Use MeSH terms, Boolean operators (AND, OR, NOT), field tags [Title], [Author]
- **Example**: `"CRISPR"[Title] AND "gene editing"[Title/Abstract] AND 2020:2024[Publication Date]`

#### bioRxiv / medRxiv
- **Access**: Use `gget` skill or direct API
- **Coverage**: Preprints in biology and medicine
- **Best for**: Latest unpublished research, cutting-edge findings
- **Note**: Not peer-reviewed; verify findings with caution
- **Search tips**: Search by category (bioinformatics, genomics, etc.)

### General Scientific Literature

#### arXiv
- **Access**: Direct API access
- **Coverage**: Preprints in physics, mathematics, computer science, quantitative biology
- **Best for**: Computational methods, bioinformatics algorithms, theoretical work
- **Categories**: q-bio (Quantitative Biology), cs.LG (Machine Learning), stat.ML (Statistics)
- **Search format**: `cat:q-bio.QM AND title:"single cell"`

#### Semantic Scholar
- **Access**: Direct API (requires API key)
- **Coverage**: 200M+ papers across all fields
- **Best for**: Cross-disciplinary searches, citation graphs, paper recommendations
- **Features**: Influential citations, paper summaries, related papers
- **Rate limits**: 100 requests/5 minutes with API key

#### Google Scholar
- **Access**: Web scraping (use cautiously) or manual search
- **Coverage**: Comprehensive across all fields
- **Best for**: Finding highly cited papers, conference proceedings, theses
- **Limitations**: No official API, rate limiting
- **Export**: Use "Cite" feature for formatted citations

### Engineering & Computer Science

#### Scopus (Elsevier)
- **Access**: Institutional subscription or Scopus API
- **Coverage**: 87M+ records across all STEM fields
- **Best for**: Engineering, computer science, materials science, multidisciplinary research
- **Features**: Citation analysis, author profiles, h-index, SCImago journal rankings
- **Search tips**: Use TITLE-ABS-KEY(), DOCTYPE(), PUBYEAR()
- **Example**: `TITLE-ABS-KEY("structural health monitoring") AND PUBYEAR > 2019 AND DOCTYPE(ar)`

#### Web of Science (Clarivate)
- **Access**: Institutional subscription or Web of Science API
- **Coverage**: 90M+ records across sciences, engineering, humanities
- **Best for**: High-impact research, citation tracking, impact factor analysis
- **Features**: Journal Impact Factor, Essential Science Indicators, Research Areas
- **Search tips**: Use TS=(topic), TI=(title), AU=(author)
- **Example**: `TS=("finite element analysis" AND "seismic") AND PY=(2020-2024)`

#### IEEE Xplore
- **Access**: IEEE Xplore API or direct search
- **Coverage**: 5M+ documents in electrical engineering, CS, electronics
- **Best for**: Signal processing, communications, power systems, computer vision, robotics
- **Search tips**: Use metadata fields ("Abstract":, "Document Title":, "Author Affiliation":)
- **Example**: `"Document Title":"deep learning" AND "Abstract":"image classification"`

#### ASCE Library (American Society of Civil Engineers)
- **Access**: Institutional subscription
- **Coverage**: Journals, conference proceedings, standards in civil engineering
- **Best for**: Structural engineering, geotechnical, transportation, water resources, construction
- **Search tips**: Filter by journal, conference, or standard; use DOI for verification

#### Compendex / Engineering Village
- **Access**: Institutional subscription
- **Coverage**: 26M+ records across all engineering disciplines
- **Best for**: Comprehensive engineering literature, applied research
- **Features**: Controlled vocabulary (Ei Thesaurus), faceted search
- **Search tips**: Use Ei controlled terms for precise searching
- **Example**: `{seismic retrofitting} WN KY AND {reinforced concrete} WN KY`

#### INSPEC (IET)
- **Access**: Via Engineering Village or institutional subscription
- **Coverage**: 20M+ records in physics, electrical engineering, electronics, CS, IT
- **Best for**: Electrical engineering, control systems, communications, theoretical CS

#### ACM Digital Library
- **Access**: Direct API or institutional subscription
- **Coverage**: Full-text of ACM publications, 50+ years of computing literature
- **Best for**: All areas of computer science, software engineering, HCI, AI/ML
- **Features**: The ACM Computing Classification System (CCS) for topic hierarchy

#### DBLP (Computer Science Bibliography)
- **Access**: Free, no authentication required. Direct API available
- **Coverage**: 6M+ publications in computer science
- **Best for**: CS publication metadata, author profiles, venue indexing
- **Note**: Bibliographic metadata only (no abstracts); use as complement to ACM/IEEE

#### GeoRef (American Geosciences Institute)
- **Access**: Via Engineering Village or institutional subscription
- **Coverage**: Geosciences, geology, geophysics, environmental geology
- **Best for**: Geological engineering, environmental site characterization, hydrogeology

#### EPA Publications
- **Access**: EPA's National Service Center for Environmental Publications (NSCEP)
- **Coverage**: EPA technical reports, environmental standards, regulatory documents
- **Best for**: Environmental engineering, pollution control, environmental regulations

## Chinese-Language Academic Databases (中文学术数据库)

### CNKI (中国知网 — China National Knowledge Infrastructure)
- **URL**: https://www.cnki.net
- **Coverage**: 80M+ articles, China's largest academic database. Covers journals, dissertations, conference proceedings, patents, standards (GB), newspapers, yearbooks.
- **Search Syntax**:
  - Basic: `主题="关键词" AND 篇名="另一关键词"`
  - Fields: `主题`(Topic/Subject), `篇名`(Title), `作者`(Author), `关键词`(Keywords), `摘要`(Abstract), `全文`(Full text), `基金`(Funding), `DOI`
  - Boolean: `AND`/`OR`/`NOT` (same as English)
  - Example: `主题="有限元分析" AND 篇名="钢筋混凝土" AND 来源期刊="建筑结构学报"`
  - Date range: `发表时间：2020-01-01 至 2025-12-31`
  - Source filter: 核心期刊/CSSCI/CSCD/EI/SCI
- **Access**: Institutional subscription required. CNKI Open API available for metadata retrieval.
- **Best for**: Chinese-language journal articles, doctoral/master's dissertations, GB standards, Chinese conference proceedings
- **Citation export**: Supports RefWorks, EndNote, BibTeX (via CNKI E-Study)

### Wanfang Data (万方数据)
- **URL**: https://www.wanfangdata.com.cn
- **Coverage**: 80M+ records. Strong in Chinese dissertations, conference proceedings, patents, standards, and Chinese medical/technical literature.
- **Search Syntax**:
  - Fields: `主题`, `题名`, `作者`, `摘要`, `关键词`, `DOI`, `基金`
  - Example: `主题:"碳排放" AND 关键词:"生命周期评价" AND 发表时间:2020-2025`
- **Access**: Institutional subscription. Some open-access content.
- **Best for**: Chinese dissertations (博士/硕士论文), Chinese conference proceedings, technical standards

### CQVIP (维普 — Chongqing VIP Information)
- **URL**: https://www.cqvip.com
- **Coverage**: 120M+ articles. Chinese science and technology journal articles, especially strong in engineering and applied sciences.
- **Search Syntax**:
  - Fields: `关键词`, `题名`, `作者`, `摘要`, `机构`
  - Example: `关键词=桥梁健康监测 AND 机构=同济大学`
- **Access**: Institutional subscription.
- **Best for**: Chinese S&T journal articles, engineering and applied science literature

### Baidu Scholar (百度学术)
- **URL**: https://xueshu.baidu.com
- **Coverage**: Aggregates from CNKI, Wanfang, CQVIP, PubMed, IEEE, Springer, etc. 100M+ documents. Free to search.
- **Search Syntax**:
  - Basic keyword search with auto-suggestion
  - Advanced: Author, title, publication, year, DOI filters
  - Example: `建筑能耗 机器学习 预测 site:cnki.net`
- **Access**: Free. Links to publisher pages for full text.
- **Best for**: Cross-database Chinese literature discovery, finding open-access versions, citation count overview

### Chinese Database Selection Strategy
| Research Need | Primary Database | Secondary |
|--------------|-----------------|-----------|
| Chinese journal articles (工程类) | CNKI | CQVIP |
| Doctoral/Master's dissertations | CNKI | Wanfang |
| Chinese conference proceedings | Wanfang | CNKI |
| GB standards (国标) | CNKI → 标准库 | Wanfang |
| Cross-language discovery | Baidu Scholar | Google Scholar |
| Patents (Chinese) | CNKI → 专利库 | Wanfang |

### Multilingual Search Strategy
When conducting cross-language literature reviews:
1. Search English databases (Scopus, WoS, IEEE, ASCE) with English terms
2. Search Chinese databases (CNKI, Wanfang) with equivalent Chinese terms
3. Use Baidu Scholar to bridge — it indexes both Chinese and English sources
4. For Chinese terms mapping to English: use CNKI's bilingual abstracts and keywords
5. Key engineering term mappings:
   - 有限元分析 = Finite Element Analysis (FEA)
   - 钢筋混凝土 = Reinforced Concrete (RC)
   - 抗震设计 = Seismic Design
   - 碳排放 = Carbon Emission
   - 生命周期评价 = Life Cycle Assessment (LCA)
   - 深度学习 = Deep Learning
   - 神经网络 = Neural Network
   - 结构健康监测 = Structural Health Monitoring (SHM)

## Environmental Engineering Database Search Strategies

### EPA Publications & NSCEP (National Service Center for Environmental Publications)
- **URL**: https://www.epa.gov/nscep
- **Coverage**: EPA technical reports, risk assessments, guidance documents, environmental impact statements
- **Access**: Free, publicly available
- **Search Tips**: Use EPA report numbers (e.g., EPA/600/R-24/001). Browse by topic (air, water, waste, chemicals). Filter by publication year and document type.
- **Best for**: US environmental regulations, EPA methods (e.g., Method 1623 for Cryptosporidium), risk assessments, environmental impact statements

### GeoRef (American Geosciences Institute)
- **URL**: Available through EBSCOhost, ProQuest, Ovid
- **Coverage**: 4.5M+ records in geosciences, geology, geophysics, hydrology, environmental geology, geochemistry, paleontology
- **Search Syntax** (EBSCOhost):
  - `DE "descriptor"` for controlled vocabulary
  - `TI "title words"` for title search
  - `SU "subject"` for subject headings
  - Example: `DE "groundwater pollution" AND TI "remediation" AND PY 2020-2025`
- **Controlled Vocabulary**: GeoRef Thesaurus (10,000+ terms)
- **Access**: Institutional subscription (available at most research universities)
- **Best for**: Geological/hydrological environmental studies, groundwater contamination, soil remediation, geothermal energy

### GreenFILE (EBSCO)
- **URL**: Available through EBSCOhost
- **Coverage**: Human impact on the environment — global warming, green building, pollution, sustainable agriculture, renewable energy, recycling
- **Search**: Standard EBSCOhost interface with subject headings
- **Access**: Free at many public libraries, institutional subscription for full features
- **Best for**: Environmental policy, sustainability research, green technology overview

### USGS Publications Warehouse
- **URL**: https://pubs.usgs.gov
- **Coverage**: USGS reports, maps, data releases — water resources, geological hazards, mineral resources, environmental health
- **Search**: Full-text search, author, year, publication series, topic
- **Access**: Free, publicly available
- **Best for**: US water resources data, geological/environmental surveys, streamflow data, groundwater levels

### IEA (International Energy Agency)
- **URL**: https://www.iea.org (reports), https://www.iea.org/data-and-statistics (data)
- **Coverage**: Energy statistics, technology roadmaps, country energy policies, World Energy Outlook
- **Access**: Summary free, full reports require subscription. Data tables often free.
- **Best for**: Global energy trends, energy policy analysis, technology roadmaps (solar, wind, hydrogen, CCUS), country energy profiles

### IRENA (International Renewable Energy Agency)
- **URL**: https://www.irena.org
- **Coverage**: Renewable energy statistics, cost data, technology briefs, capacity data
- **Access**: Free
- **Best for**: Renewable energy costs (LCOE data), capacity statistics, technology briefs, energy transition pathways

### IPCC Reports
- **URL**: https://www.ipcc.ch/reports/
- **Coverage**: Assessment Reports (AR5, AR6), Special Reports (SR1.5, SRCCL, SROCC), Methodology Reports
- **Access**: Free
- **Citation**: Use IPCC AR6 WG III for emission factors, WG I for climate science, WG II for impacts/adaptation
- **Best for**: Climate change science, emission scenarios, adaptation/mitigation strategies, GWP values

### Environmental Database Selection Strategy
| Research Need | Primary Database | Secondary |
|--------------|-----------------|-----------|
| Water treatment/remediation | Scopus + WoS | EPA NSCEP, GeoRef |
| Air quality/pollution | Scopus + WoS | EPA, GreenFILE |
| Soil contamination/remediation | Scopus + GeoRef | USGS, EPA |
| LCA/Carbon footprint | Scopus + WoS | IPCC, ecoinvent |
| Energy systems/policy | Scopus + WoS | IEA, IRENA |
| Climate change impacts | WoS | IPCC, GreenFILE |
| Waste management | Scopus + WoS | EPA, GreenFILE |
| Environmental regulations | EPA NSCEP | CNKI (for Chinese standards) |

### Specialized Databases

#### ChEMBL / PubChem
- **Access**: Use `gget` skill or `bioservices` skill
- **Coverage**: Chemical compounds, bioactivity data, drug molecules
- **Best for**: Drug discovery, chemical biology, medicinal chemistry
- **ChEMBL**: 2M+ compounds, bioactivity data
- **PubChem**: 110M+ compounds, assay data

#### UniProt
- **Access**: Use `gget` skill or `bioservices` skill
- **Coverage**: Protein sequence and functional information
- **Best for**: Protein research, sequence analysis, functional annotations
- **Search by**: Protein name, gene name, organism, function

#### KEGG (Kyoto Encyclopedia of Genes and Genomes)
- **Access**: Use `bioservices` skill
- **Coverage**: Pathways, diseases, drugs, genes
- **Best for**: Pathway analysis, systems biology, metabolic research

#### COSMIC (Catalogue of Somatic Mutations in Cancer)
- **Access**: Use `gget` skill or direct download
- **Coverage**: Cancer genomics, somatic mutations
- **Best for**: Cancer research, mutation analysis

#### AlphaFold Database
- **Access**: Use `gget` skill with `alphafold` command
- **Coverage**: 200M+ protein structure predictions
- **Best for**: Structural biology, protein modeling

#### PDB (Protein Data Bank)
- **Access**: Use `gget` or direct API
- **Coverage**: Experimental 3D structures of proteins, nucleic acids
- **Best for**: Structural biology, drug design, molecular modeling

### Citation & Reference Management

#### OpenAlex
- **Access**: Direct API (free, no key required)
- **Coverage**: 250M+ works, comprehensive metadata
- **Best for**: Citation analysis, author disambiguation, institutional research
- **Features**: Open access, excellent for bibliometrics

#### Dimensions
- **Access**: Free tier available
- **Coverage**: Publications, grants, patents, clinical trials
- **Best for**: Research impact, funding analysis, translational research

---

## Search Strategy Framework

### 1. Define Research Question (PICO Framework)

For clinical/biomedical reviews:
- **P**opulation: Who is the study about?
- **I**ntervention: What is being tested?
- **C**omparison: What is it compared to?
- **O**utcome: What are the results?

**Example**: "What is the efficacy of CRISPR-Cas9 gene therapy (I) for treating sickle cell disease (P) compared to standard care (C) in improving patient outcomes (O)?"

### 1b. Engineering Research Questions (PEO Framework)

For engineering and applied research reviews:
- **P**opulation/Problem: What system, structure, or material is being studied?
- **E**xposure/Intervention: What treatment, method, or technology is applied?
- **O**utcome: What performance metrics or results are measured?

**Example**: "What is the effectiveness of fiber-reinforced polymer (E) wrapping for strengthening reinforced concrete columns (P) in improving axial load capacity and ductility (O)?"

### 1c. Computer Science Research Questions (PICO Variant)

For CS and computational research reviews:
- **P**roblem: What computational problem or task is addressed?
- **I**ntervention: What algorithm, architecture, or method is proposed?
- **C**omparison: What existing methods or baselines are used?
- **O**utcome: What metrics are reported (accuracy, latency, scalability)?

**Example**: "Can transformer-based architectures (I) improve code vulnerability detection (P) compared to traditional static analysis tools (C) in terms of precision and recall (O)?"

### 1d. Environmental Research Questions (PCC Framework)

For environmental and sustainability reviews:
- **P**opulation: What environment, ecosystem, or system is studied?
- **C**oncept: What environmental process, pollutant, or intervention is examined?
- **C**ontext: What geographic, temporal, or regulatory context applies?

**Example**: "How do constructed wetlands (C) affect heavy metal removal efficiency (C) in urban stormwater treatment (P) under temperate climate conditions (C)?"

### 2. Develop Search Terms

#### Primary Concepts
Identify 2-4 main concepts from your research question.

**Example**:
- Concept 1: CRISPR, Cas9, gene editing
- Concept 2: sickle cell disease, SCD, hemoglobin disorders
- Concept 3: gene therapy, therapeutic editing

#### Synonyms & Related Terms
List alternative terms, abbreviations, and related concepts.

**Tool**: Use MeSH (Medical Subject Headings) browser for standardized terms

#### Boolean Operators
- **AND**: Narrows search (must include both terms)
- **OR**: Broadens search (includes either term)
- **NOT**: Excludes terms

**Example**: `(CRISPR OR Cas9 OR "gene editing") AND ("sickle cell" OR SCD) AND therapy`

#### Wildcards & Truncation
- `*` or `%`: Matches any characters
- `?`: Matches single character

**Example**: `genom*` matches genomic, genomics, genome

### 3. Set Inclusion/Exclusion Criteria

#### Inclusion Criteria
- **Date range**: e.g., 2015-2024 (last 10 years)
- **Language**: English (or specify multilingual)
- **Publication type**: Peer-reviewed articles, reviews, preprints
- **Study design**: RCTs, cohort studies, meta-analyses
- **Population**: Human, animal models, in vitro

#### Exclusion Criteria
- Case reports (n<5)
- Conference abstracts without full text
- Non-original research (editorials, commentaries)
- Duplicate publications
- Retracted articles

### 4. Database Selection Strategy

#### Multi-Database Approach
Search at least 3 complementary databases:

1. **Primary database**: PubMed (biomedical) or arXiv (computational)
2. **Preprint server**: bioRxiv/medRxiv or arXiv
3. **Comprehensive database**: Semantic Scholar or Google Scholar
4. **Specialized database**: ChEMBL, UniProt, or field-specific

#### Civil / Structural / Geotechnical Engineering
1. **Primary**: Scopus or Web of Science (broad engineering coverage)
2. **Domain-specific**: ASCE Library (civil engineering journals & standards)
3. **Engineering-wide**: Compendex / Engineering Village
4. **Comprehensive**: Google Scholar (capture conference proceedings)

#### Environmental Engineering
1. **Primary**: Scopus or Web of Science
2. **Domain-specific**: EPA Publications, GeoRef
3. **Engineering-wide**: Compendex / Engineering Village
4. **Environmental science**: Web of Science (Environmental Sciences category)

#### Computer Science / Machine Learning
1. **Primary**: DBLP (bibliography) + ACM Digital Library (full-text)
2. **Domain-specific**: IEEE Xplore (applications, signal processing, robotics)
3. **Preprints**: arXiv (cs.*, stat.ML categories)
4. **Comprehensive**: Semantic Scholar (citation graphs, influence metrics)

#### Interdisciplinary (AI + Engineering)
1. **Primary**: Scopus (broad STEM coverage)
2. **CS-side**: ACM Digital Library, IEEE Xplore
3. **Engineering-side**: ASCE Library, Compendex
4. **Comprehensive**: Web of Science, Google Scholar

#### Database-Specific Syntax

| Database | Field Tags | Example |
|----------|-----------|---------|
| PubMed | [Title], [Author], [MeSH] | "CRISPR"[Title] AND 2020:2024[DP] |
| arXiv | ti:, au:, cat: | ti:"machine learning" AND cat:q-bio.QM |
| Semantic Scholar | title:, author:, year: | title:"deep learning" year:2020-2024 |
| Scopus | TITLE-ABS-KEY(), PUBYEAR() | TITLE-ABS-KEY("finite element") AND PUBYEAR > 2019 |
| Web of Science | TS=, TI=, PY= | TS=("seismic retrofit") AND PY=(2020-2024) |
| IEEE Xplore | "Document Title":, "Abstract": | "Document Title":"neural network" AND "Abstract":"structural" |
| ACM DL | Abstract:, Title: | Abstract:"distributed systems" AND Title:"consensus" |
| Compendex | {term} WN KY | {bridge load rating} WN KY AND {finite element} WN KY |

---

## Search Execution Workflow

### Phase 1: Pilot Search
1. Run initial search with broad terms
2. Review first 50 results for relevance
3. Note common keywords and MeSH terms
4. Refine search strategy

### Phase 2: Comprehensive Search
1. Execute refined searches across all selected databases
2. Export results in standard format (RIS, BibTeX, JSON)
3. Document search strings and date for each database
4. Record number of results per database

### Phase 3: Deduplication
1. Import all results into a single file
2. Use `search_databases.py --deduplicate` to remove duplicates
3. Identify duplicates by DOI (primary) or title (fallback)
4. Keep the version with most complete metadata

### Phase 4: Screening
1. **Title screening**: Review titles, exclude obviously irrelevant
2. **Abstract screening**: Read abstracts, apply inclusion/exclusion criteria
3. **Full-text screening**: Obtain and review full texts
4. Document reasons for exclusion at each stage

### Phase 5: Quality Assessment
1. Assess study quality using appropriate tools:
   - **RCTs**: Cochrane Risk of Bias tool
   - **Observational**: Newcastle-Ottawa Scale
   - **Systematic reviews**: AMSTAR 2
2. Grade quality of evidence (high, moderate, low, very low)
3. Consider excluding very low-quality studies

---

## Search Documentation Template

### Required Documentation
All searches must be documented for reproducibility:

```markdown
## Search Strategy

### Database: PubMed
- **Date searched**: 2024-10-25
- **Date range**: 2015-01-01 to 2024-10-25
- **Search string**:
  ```
  ("CRISPR"[Title] OR "Cas9"[Title] OR "gene editing"[Title/Abstract])
  AND ("sickle cell disease"[MeSH] OR "SCD"[Title/Abstract])
  AND ("gene therapy"[MeSH] OR "therapeutic editing"[Title/Abstract])
  AND 2015:2024[Publication Date]
  AND English[Language]
  ```
- **Results**: 247 articles
- **After deduplication**: 189 articles

### Database: bioRxiv
- **Date searched**: 2024-10-25
- **Date range**: 2015-01-01 to 2024-10-25
- **Search string**: "CRISPR" AND "sickle cell" (in title/abstract)
- **Results**: 34 preprints
- **After deduplication**: 28 preprints

### Total Unique Articles
- **Combined results**: 217 unique articles
- **After title screening**: 156 articles
- **After abstract screening**: 89 articles
- **After full-text screening**: 52 articles included in review
```

---

## Domain-Specific Search Strategy Examples

### CS/AI Search Strategy Examples

**Machine Learning Methods:**
```
("deep learning" OR "neural network" OR "transformer" OR "attention mechanism")
AND ("structural health monitoring" OR "damage detection" OR "structural engineering")
AND ("performance" OR "accuracy" OR "robustness")
```

**LLM Applications:**
```
("large language model" OR "LLM" OR "GPT" OR "BERT" OR "foundation model")
AND ("scientific" OR "engineering" OR "research" OR "code generation")
AND ("evaluation" OR "benchmark" OR "comparison")
```

**Computer Vision for Engineering:**
```
("computer vision" OR "object detection" OR "image segmentation" OR "crack detection")
AND ("infrastructure" OR "bridge" OR "building" OR "construction")
AND ("automated" OR "real-time" OR "deep learning")
```

### Carbon/Energy/HVAC Search Strategy Examples

**Building Energy Optimization:**
```
("building energy" OR "energy efficiency" OR "HVAC optimization")
AND ("machine learning" OR "deep learning" OR "reinforcement learning" OR "model predictive control")
AND ("energy savings" OR "comfort" OR "cost reduction")
```

**Carbon Accounting:**
```
("carbon footprint" OR "life cycle assessment" OR "LCA" OR "embodied carbon")
AND ("building" OR "construction" OR "infrastructure")
AND ("ISO 14040" OR "ISO 14064" OR "GHG Protocol")
```

**Smart Grid and Buildings:**
```
("smart grid" OR "demand response" OR "building-to-grid" OR "microgrid")
AND ("renewable" OR "solar" OR "battery" OR "energy storage")
AND ("optimization" OR "control" OR "scheduling")
```

---

## Advanced Search Techniques

### Prioritizing High-Impact Papers (CRITICAL)

**Always prioritize papers based on citation count, venue quality, and author reputation.** Quality matters more than quantity.

#### Citation Metrics in Database Searches

Use citation counts to identify influential work:

| Paper Age | Citations | Classification |
|-----------|-----------|----------------|
| 0-3 years | 20+ | Noteworthy |
| 0-3 years | 100+ | Highly Influential |
| 3-7 years | 100+ | Significant |
| 3-7 years | 500+ | Landmark |
| 7+ years | 500+ | Seminal |
| 7+ years | 1000+ | Foundational |

**Database-Specific Citation Features:**
- **Google Scholar:** Sort by citation count, use "Cited by" feature
- **Semantic Scholar:** "Highly Influential Citations" metric, citation velocity
- **OpenAlex:** Citation counts, citation context analysis
- **PubMed:** Use "Cited by" in PMC, check citation counts via Google Scholar

#### Filtering by Journal Quality

Prioritize papers from higher-tier venues:

**Tier 1 (Always Prefer):**
- Nature, Science, Cell, NEJM, Lancet, JAMA, PNAS
- Nature Medicine, Nature Biotechnology, Nature Methods
- Search tip: `source:Nature` or `journal:Nature` in Google Scholar

**Tier 2 (High Priority):**
- High-impact specialized journals (Impact Factor >10)
- Top conferences: NeurIPS, ICML, ICLR, CVPR, ACL

**Tier 3 (Include When Relevant):**
- Respected field-specific journals (IF 5-10)

**PubMed Journal Filtering:**
```
"Nature"[Journal] OR "Science"[Journal] OR "Cell"[Journal]
```

**Google Scholar Journal Filtering:**
```
source:Nature source:Science source:Cell
```

#### Leveraging "Cited by" Features

**Finding Influential Work:**
1. Start with a known key paper
2. Click "Cited by" to find papers that cite it
3. Sort citing papers by their citation count
4. Highly-cited citing papers indicate important follow-up work

**Identifying Seminal Papers:**
1. Search your topic broadly
2. Note which papers appear repeatedly in reference lists
3. Papers cited by many of your results are likely seminal
4. Check citation counts to confirm influence

**Semantic Scholar Features:**
- "Highly Influential Citations" shows citations that significantly built on the paper
- "Citation Velocity" shows recent citation growth
- Paper recommendations based on citation networks

### Citation Chaining

#### Forward Citation Search
Find papers that cite a key paper:
- Use Google Scholar "Cited by" feature
- Use OpenAlex or Semantic Scholar APIs
- Identifies newer research building on seminal work
- **Tip:** Sort by citation count to find the most influential follow-up work

#### Backward Citation Search
Review references in key papers:
- Extract references from included papers
- Search for highly cited references (500+ citations for older papers)
- Identifies foundational research
- **Tip:** Focus on references that appear in multiple papers' bibliographies

### Snowball Sampling
1. Start with 3-5 highly relevant papers **from Tier-1 venues**
2. Extract all their references
3. Check which references are cited by multiple papers
4. Review those high-overlap references - these are likely seminal
5. Repeat for newly identified key papers
6. **Prioritize papers with high citation counts** at each step

### Author Search
Follow prolific and reputable authors in the field:
- Search by author name across databases
- Check author profiles (ORCID, Google Scholar) for h-index and publication venues
- Review recent publications and preprints
- **Prefer authors with multiple Tier-1 publications** and high h-index (>40)
- Look for senior authors who are recognized field leaders

### Related Article Features
Many databases suggest related articles:
- PubMed "Similar articles"
- Semantic Scholar "Recommended papers"
- Use to discover papers missed by keyword search
- **Filter recommendations by citation count and venue quality**

---

## Quality Control Checklist

### Before Searching
- [ ] Research question clearly defined
- [ ] PICO criteria established (if applicable)
- [ ] Search terms and synonyms listed
- [ ] Inclusion/exclusion criteria documented
- [ ] Target databases selected (minimum 3)
- [ ] Date range determined

### During Searching
- [ ] Search string tested and refined
- [ ] Results exported with complete metadata
- [ ] Search parameters documented
- [ ] Number of results recorded per database
- [ ] Search date recorded

### After Searching
- [ ] Duplicates removed
- [ ] Screening protocol followed
- [ ] Reasons for exclusion documented
- [ ] Quality assessment completed
- [ ] All citations verified with verify_citations.py
- [ ] Search methodology documented in review

---

## Common Pitfalls to Avoid

1. **Too narrow search**: Missing relevant papers
   - Solution: Include synonyms, related terms, broader concepts

2. **Too broad search**: Thousands of irrelevant results
   - Solution: Add specific concepts with AND, use field tags

3. **Single database**: Incomplete coverage
   - Solution: Search minimum 3 complementary databases

4. **Ignoring preprints**: Missing latest findings
   - Solution: Include bioRxiv, medRxiv, or arXiv

5. **No documentation**: Irreproducible search
   - Solution: Document every search string, date, and result count

6. **Manual deduplication**: Time-consuming and error-prone
   - Solution: Use search_databases.py script

7. **Unverified citations**: Broken DOIs, incorrect metadata
   - Solution: Run verify_citations.py on final reference list

8. **Publication bias**: Only including published positive results
   - Solution: Search trial registries, contact authors for unpublished data

---

## Example Multi-Database Search Workflow

```python
# Example workflow using available skills

# 1. Search PubMed via gget
search_term = "CRISPR AND sickle cell disease"
# Use gget search pubmed search_term

# 2. Search bioRxiv
# Use gget search biorxiv search_term

# 3. Search arXiv for computational papers
# Search arXiv with: cat:q-bio AND "CRISPR" AND "sickle cell"

# 4. Search Semantic Scholar via API
# Use semantic scholar API with search query

# 5. Aggregate and deduplicate results
# python search_databases.py combined_results.json --deduplicate --format markdown --output review_papers.md

# 6. Verify all citations
# python verify_citations.py review_papers.md

# 7. Generate final PDF
# python generate_pdf.py review_papers.md --citation-style nature
```

---

## Specialized Engineering Databases

### Material Property Databases

#### MatWeb (www.matweb.com)
- **Content**: 130,000+ material data sheets (metals, polymers, ceramics, composites)
- **Access**: Free basic search; premium for bulk data
- **Use for**: Material property lookup for FEM input, material selection
- **Search tip**: Search by material grade (e.g., "Q345B", "ASTM A992", "C30/37 concrete")
- **Data quality**: Manufacturer-reported; verify against code design values

#### NIST Material Data (materialsdata.nist.gov)
- **Content**: SRD (Standard Reference Data) for thermophysical, mechanical, optical properties
- **Access**: Free for most datasets
- **Use for**: High-accuracy material constants, calibration data
- **Key datasets**: NIST WebBook (thermodynamics), SRD 145 (concrete), SRD 82 (steel)

#### CES EduPack / Granta Selector
- **Content**: Material property database with Ashby charts
- **Access**: Licensed (institutional)
- **Use for**: Material selection, comparative analysis, sustainability indices
- **Strength**: Visual material selection using property charts

### Hydrological & Environmental Databases

#### USGS National Water Information System (NWIS)
- **Content**: Streamflow, groundwater, water quality data for 1.5M+ sites
- **Access**: Free (waterdata.usgs.gov)
- **Use for**: Hydrological modeling calibration, flood frequency analysis, water quality trends
- **API**: REST API available for bulk data download
- **Data quality**: Quality-controlled by USGS; flag codes for data qualification

#### EPA Envirofacts
- **Content**: Air emissions, water discharges, waste management, toxic releases
- **Access**: Free (envirofacts.epa.gov)
- **Use for**: Environmental impact assessment, compliance data, emission inventories
- **Databases**: TRI, NEI, SDWIS, RCRA, CERCLA

#### Global Runoff Data Centre (GRDC)
- **Content**: River discharge data from 9,500+ stations in 161 countries
- **Access**: Free registration
- **Use for**: Large-scale hydrological analysis, climate impact studies

### Seismic & Natural Hazard Databases

#### FEMA P-58 HAZUS
- **Content**: Seismic fragility and consequence functions for building typologies
- **Access**: Free
- **Use for**: Seismic loss estimation, probabilistic seismic risk assessment
- **Key**: Building damage functions by construction type, height, code era

#### NHERI DesignSafe-CI (www.designsafe-ci.org)
- **Content**: Experimental data, simulation tools, and curated datasets from NSF NHERI
- **Access**: Free (requires registration)
- **Use for**: Post-earthquake reconnaissance data, shake table test data, centrifuge test data
- **Strength**: Raw experimental data available for reuse

#### PEER NGA Database
- **Content**: Strong ground motion records from global earthquakes
- **Access**: Free (peer.berkeley.edu)
- **Use for**: Ground motion selection for time history analysis, GMPE development
- **Key**: NGA-West2 (shallow crustal), NGA-East (central/eastern US)

### Construction & Building Databases

#### RSMeans / Gordian
- **Content**: Construction cost data by trade, region, and building type
- **Access**: Licensed
- **Use for**: Cost estimation, life cycle cost analysis, feasibility studies

#### ASHRAE Handbook Online
- **Content**: HVAC design data, energy standards, building physics
- **Access**: Licensed (ASHRAE membership or institutional)
- **Use for**: Building energy simulation inputs, HVAC design parameters

### Energy & Carbon Databases

#### IEA World Energy Balances
- **Content**: Energy supply, transformation, and consumption for 150+ countries
- **Access**: Licensed (institutional)
- **Use for**: Energy system modeling, carbon emission benchmarking

#### IPCC Emission Factor Database (EFDB)
- **Content**: Default emission factors by sector and fuel type
- **Access**: Free (www.ipcc-nggip.iges.or.jp/EFDB)
- **Use for**: GHG inventory, carbon footprint calculation, LCA background data

#### IRENA Renewable Energy Statistics
- **Content**: Capacity, generation, and cost data for renewable energy technologies
- **Access**: Free
- **Use for**: Renewable energy feasibility, LCOE benchmarking, technology comparison

### Database Selection by Engineering Sub-Domain

| Sub-Domain | Primary Databases | Specialized Databases |
|-----------|------------------|----------------------|
| Structural Engineering | Scopus, Web of Science, ASCE Library | PEER NGA, NHERI DesignSafe, FEMA P-58 |
| Geotechnical | Scopus, GeoRef | USGS, NGMDB, CPT databases |
| Construction Management | Scopus, ASCE Library | RSMeans, BIM object libraries |
| Water Resources | Scopus, Web of Science | USGS NWIS, GRDC, EPA Water Quality Portal |
| Air Quality | Scopus, Web of Science | EPA AQS, AirNow, Copernicus CAMS |
| LCA / Carbon | Scopus, Web of Science | ecoinvent, GaBi, IPCC EFDB, IEA |
| Energy Systems | IEEE Xplore, Scopus | IEA, IRENA, EIA, OpenEI |
| AI for Engineering | IEEE Xplore, ACM DL, arXiv | Papers with Code, GitHub trending |

---

## Resources

### MeSH Browser
https://meshb.nlm.nih.gov/search

### Boolean Search Tutorial
https://www.ncbi.nlm.nih.gov/books/NBK3827/

### Citation Style Guides
See references/citation_styles.md in this skill

### PRISMA Guidelines
Preferred Reporting Items for Systematic Reviews and Meta-Analyses:
http://www.prisma-statement.org/
