# Engineering Controlled Vocabulary Tutorials

## Ei Thesaurus (Engineering Index)

### What It Is
The Ei Thesaurus is the controlled vocabulary for Compendex (Engineering Village), the most comprehensive engineering database. Using Ei Thesaurus terms dramatically improves recall and precision in engineering literature searches.

### How to Use
1. **Access**: Available through Engineering Village (requires institutional access)
2. **Browse**: Alphabetical or hierarchical structure
3. **Search strategy**: Start with keyword -> find Ei Thesaurus term -> use controlled term in search

### Key Civil Engineering Terms
| Keyword | Ei Thesaurus Term | Broader Term | Related Terms |
|---------|-------------------|--------------|---------------|
| Earthquake resistant structures | SEISMIC DESIGN | STRUCTURAL DESIGN | Earthquake engineering, Base isolation |
| Reinforced concrete | REINFORCED CONCRETE | CONCRETE | Prestressed concrete, Fiber reinforced concrete |
| Finite element analysis | FINITE ELEMENT METHOD | NUMERICAL METHODS | Boundary element method, Meshfree methods |
| Steel structures | STEEL STRUCTURES | STRUCTURAL STEEL | Steel beams, Steel columns, Connections |
| Bridge design | BRIDGE DESIGN | CIVIL ENGINEERING | Cable stayed bridges, Suspension bridges |
| Soil mechanics | SOIL MECHANICS | GEOTECHNICAL ENGINEERING | Soil properties, Consolidation |

### Key Environmental Engineering Terms
| Keyword | Ei Thesaurus Term | Broader Term | Related Terms |
|---------|-------------------|--------------|---------------|
| Water treatment | WATER TREATMENT | WATER | Wastewater treatment, Drinking water |
| Air pollution | AIR POLLUTION | POLLUTION | Emissions, Particulates, Greenhouse gases |
| Life cycle assessment | LIFE CYCLE COSTING | COST BENEFIT ANALYSIS | Environmental impact, Sustainability |
| Carbon emissions | CARBON DIOXIDE | GREENHOUSE GASES | Carbon footprint, Carbon capture |
| Renewable energy | RENEWABLE ENERGY SOURCES | ENERGY SOURCES | Solar energy, Wind power |

### Key Computer Science / AI Terms
| Keyword | Ei Thesaurus Term | Broader Term | Related Terms |
|---------|-------------------|--------------|---------------|
| Machine learning | MACHINE LEARNING | ARTIFICIAL INTELLIGENCE | Deep learning, Neural networks |
| Neural networks | NEURAL NETWORKS | MACHINE LEARNING | Convolutional neural networks, Recurrent neural networks |
| Image recognition | IMAGE RECOGNITION | PATTERN RECOGNITION | Object detection, Image segmentation |
| Natural language processing | NATURAL LANGUAGE PROCESSING | ARTIFICIAL INTELLIGENCE | Text mining, Sentiment analysis |
| Computer vision | COMPUTER VISION | ARTIFICIAL INTELLIGENCE | Image processing, Object recognition |

### Search Strategy Example
**Topic**: "Machine learning for structural health monitoring"

```
# Step 1: Identify Ei Thesaurus terms
STRUCTURAL HEALTH MONITORING (Ei term)
MACHINE LEARNING (Ei term)
STRUCTURAL ENGINEERING (Ei term)

# Step 2: Build search in Engineering Village
({STRUCTURAL HEALTH MONITORING} WN CV) AND ({MACHINE LEARNING} WN CV)

# Step 3: Add synonyms for broader coverage
({STRUCTURAL HEALTH MONITORING} WN CV OR {SHM} WN CV) AND
({MACHINE LEARNING} WN CV OR {DEEP LEARNING} WN CV OR {NEURAL NETWORKS} WN CV)

# Step 4: Filter by document type and year
Document type: Journal article
Year: 2019-2026
```

## ACM Computing Classification System (CCS)

### What It Is
The ACM CCS is the controlled vocabulary for computer science literature in ACM Digital Library, IEEE Xplore, and DBLP.

### Key CCS Codes for AI/ML in Engineering
| Code | Description | Use For |
|------|-------------|---------|
| I.2.6 | Learning | Machine learning algorithms |
| I.4.8 | Scene Analysis | Object detection, structural damage detection |
| I.5.4 | Applications | Pattern recognition in engineering data |
| I.3.5 | Computational Geometry | CAD, mesh generation |
| J.2 | Physical Sciences and Engineering | Engineering applications of CS |
| I.2.10 | Vision and Scene Understanding | Computer vision for inspection |

### Search Strategy in ACM DL
```
CCS:"Computing methodologies~Machine learning" AND "structural health monitoring"
CCS:"Applied computing~Engineering" AND "deep learning"
```

## IEEE Taxonomy

### Key IEEE Terms for Engineering AI
- **Smart Infrastructure**: IoT sensors, structural monitoring, digital twins
- **Cyber-Physical Systems**: real-time control, embedded systems, SCADA
- **Computational Intelligence**: neural networks, fuzzy logic, evolutionary computation
- **Pattern Recognition**: damage detection, defect classification, anomaly detection

### Search in IEEE Xplore
```
("structural health monitoring" OR "SHM") AND ("deep learning" OR "neural network")
Controlled term: "Structural engineering" AND "Machine learning"
```

## Cross-Database Strategy

| Database | Controlled Vocabulary | Best For |
|----------|---------------------|----------|
| Compendex (Engineering Village) | Ei Thesaurus | All engineering disciplines |
| ACM Digital Library | ACM CCS | Computer science, software |
| IEEE Xplore | IEEE Taxonomy | Electrical, electronics, AI/ML |
| Web of Science | Keywords Plus + Author Keywords | Multidisciplinary |
| Scopus | Emtree (medical) + Author Keywords | Broad coverage |
| CNKI | CLC code | Chinese literature |
