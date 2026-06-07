# Word Document Template Selection Guide

## Available Templates

### Engineering Journal Templates
| Template | File | Use When |
|----------|------|----------|
| ASCE Paper | `asce_paper.js` | ASCE journals (J. Structural Engineering, J. Geotechnical Engineering, etc.) |
| Elsevier Paper | `elsevier_paper.js` | Elsevier engineering journals (Engineering Structures, Construction and Building Materials, etc.) |
| IEEE Paper | `ieee_paper.js` | IEEE transactions and conferences (IEEE Trans. on Neural Networks, IEEE Access, etc.) |
| Chinese Engineering | `engineering_paper_cn.js` | Chinese engineering journals (土木工程学报, 建筑结构学报, etc.) |
| International Engineering | `engineering_paper_en.js` | Generic international engineering journals |
| Energy/Buildings Journal | `energy_paper.js` | Applied Energy, Energy and Buildings, Building and Environment |
| ACM Conference | `acm_paper.js` | ACM conferences (KDD, SIGMOD, CHI, WWW, SIGIR, etc.) |
| Medical Journal | `medical_paper.js` | NEJM, Lancet, JAMA, BMJ |
| Chinese Energy/HVAC | `chinese_energy_paper.js` | 暖通空调, 建筑科学, 建筑节能 |

### How to Use

1. Identify the target journal/conference
2. Select the appropriate template from the table above
3. Load the template: `const template = require('./templates/<template_file>').<TEMPLATE_NAME>`
4. Generate the document using the template's formatting specifications
5. Save as .docx

### Template Specifications

Each template provides:
- Page size and margins
- Font specifications (title, headings, body, references)
- Line spacing and paragraph spacing
- Section structure (required and optional sections)
- Reference formatting style
- Citation format
- Special notes and requirements

### Common Requirements Across All Templates
- Times New Roman font (varies by template)
- Double-spaced or 1.5-spaced body text
- Numbered figures and tables with captions
- Complete reference metadata (DOI required)
- SI units preferred
- Clear section headings
