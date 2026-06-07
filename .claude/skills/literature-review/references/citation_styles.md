# Citation Styles Reference

This document provides detailed guidelines for formatting citations in various academic styles commonly used in literature reviews.

## APA Style (7th Edition)

### Journal Articles

**Format**: Author, A. A., Author, B. B., & Author, C. C. (Year). Title of article. *Title of Periodical*, *volume*(issue), page range. https://doi.org/xx.xxx/yyyy

**Example**: Smith, J. D., Johnson, M. L., & Williams, K. R. (2023). Machine learning approaches in drug discovery. *Nature Reviews Drug Discovery*, *22*(4), 301-318. https://doi.org/10.1038/nrd.2023.001

### Books

**Format**: Author, A. A. (Year). *Title of work: Capital letter also for subtitle*. Publisher Name. https://doi.org/xxxx

**Example**: Kumar, V., Abbas, A. K., & Aster, J. C. (2021). *Robbins and Cotran pathologic basis of disease* (10th ed.). Elsevier.

### Book Chapters

**Format**: Author, A. A., & Author, B. B. (Year). Title of chapter. In E. E. Editor & F. F. Editor (Eds.), *Title of book* (pp. xx-xx). Publisher.

**Example**: Brown, P. O., & Botstein, D. (2020). Exploring the new world of the genome with DNA microarrays. In M. B. Eisen & P. O. Brown (Eds.), *DNA microarrays: A molecular cloning manual* (pp. 1-45). Cold Spring Harbor Laboratory Press.

### Preprints

**Format**: Author, A. A., & Author, B. B. (Year). Title of preprint. *Repository Name*. https://doi.org/xxxx

**Example**: Zhang, Y., Chen, L., & Wang, H. (2024). Novel therapeutic targets in Alzheimer's disease. *bioRxiv*. https://doi.org/10.1101/2024.01.001

### Conference Papers

**Format**: Author, A. A. (Year, Month day-day). Title of paper. In E. E. Editor (Ed.), *Title of conference proceedings* (pp. xx-xx). Publisher. https://doi.org/xxxx

---

## Nature Style

### Journal Articles

**Format**: Author, A. A., Author, B. B. & Author, C. C. Title of article. *J. Name* **volume**, page range (year).

**Example**: Smith, J. D., Johnson, M. L. & Williams, K. R. Machine learning approaches in drug discovery. *Nat. Rev. Drug Discov.* **22**, 301-318 (2023).

### Books

**Format**: Author, A. A. & Author, B. B. *Book Title* (Publisher, Year).

**Example**: Kumar, V., Abbas, A. K. & Aster, J. C. *Robbins and Cotran Pathologic Basis of Disease* 10th edn (Elsevier, 2021).

### Multiple Authors

- 1-2 authors: List all
- 3+ authors: List first author followed by "et al."

**Example**: Zhang, Y. et al. Novel therapeutic targets in Alzheimer's disease. *bioRxiv* https://doi.org/10.1101/2024.01.001 (2024).

---

## Chicago Style (Author-Date)

### Journal Articles

**Format**: Author, First Name Middle Initial. Year. "Article Title." *Journal Title* volume, no. issue (Month): page range. https://doi.org/xxxx.

**Example**: Smith, John D., Mary L. Johnson, and Karen R. Williams. 2023. "Machine Learning Approaches in Drug Discovery." *Nature Reviews Drug Discovery* 22, no. 4 (April): 301-318. https://doi.org/10.1038/nrd.2023.001.

### Books

**Format**: Author, First Name Middle Initial. Year. *Book Title: Subtitle*. Edition. Place: Publisher.

**Example**: Kumar, Vinay, Abul K. Abbas, and Jon C. Aster. 2021. *Robbins and Cotran Pathologic Basis of Disease*. 10th ed. Philadelphia: Elsevier.

---

## Vancouver Style (Numbered)

### Journal Articles

**Format**: Author AA, Author BB, Author CC. Title of article. Abbreviated Journal Name. Year;volume(issue):page range.

**Example**: Smith JD, Johnson ML, Williams KR. Machine learning approaches in drug discovery. Nat Rev Drug Discov. 2023;22(4):301-18.

### Books

**Format**: Author AA, Author BB. Title of book. Edition. Place: Publisher; Year.

**Example**: Kumar V, Abbas AK, Aster JC. Robbins and Cotran pathologic basis of disease. 10th ed. Philadelphia: Elsevier; 2021.

### Citation in Text

Use superscript numbers in order of appearance: "Recent studies^1,2^ have shown..."

---

## IEEE Style

### Journal Articles

**Format**: [#] A. A. Author, B. B. Author, and C. C. Author, "Title of article," *Abbreviated Journal Name*, vol. x, no. x, pp. xxx-xxx, Month Year.

**Example**: [1] J. D. Smith, M. L. Johnson, and K. R. Williams, "Machine learning approaches in drug discovery," *Nat. Rev. Drug Discov.*, vol. 22, no. 4, pp. 301-318, Apr. 2023.

### Books

**Format**: [#] A. A. Author, *Title of Book*, xth ed. City, State: Publisher, Year.

**Example**: [2] V. Kumar, A. K. Abbas, and J. C. Aster, *Robbins and Cotran Pathologic Basis of Disease*, 10th ed. Philadelphia, PA: Elsevier, 2021.

---

## Common Abbreviations for Journal Names

- Nature: Nat.
- Science: Science
- Cell: Cell
- Nature Reviews Drug Discovery: Nat. Rev. Drug Discov.
- Journal of the American Chemical Society: J. Am. Chem. Soc.
- Proceedings of the National Academy of Sciences: Proc. Natl. Acad. Sci. U.S.A.
- PLOS ONE: PLoS ONE
- Bioinformatics: Bioinformatics
- Nucleic Acids Research: Nucleic Acids Res.

---

## DOI Best Practices

1. **Always verify DOIs**: Use the verify_citations.py script to check all DOIs
2. **Format as URLs**: https://doi.org/10.xxxx/yyyy (preferred over doi:10.xxxx/yyyy)
3. **No period after DOI**: DOI should be the last element without trailing punctuation
4. **Resolve redirects**: Check that DOIs resolve to the correct article

---

## In-Text Citation Guidelines

### APA Style
- (Smith et al., 2023)
- Smith et al. (2023) demonstrated...
- Multiple citations: (Brown, 2022; Smith et al., 2023; Zhang, 2024)

### Nature Style
- Superscript numbers: Recent studies^1,2^ have shown...
- Or: Recent studies (refs 1,2) have shown...

### Chicago Style
- (Smith, Johnson, and Williams 2023)
- Smith, Johnson, and Williams (2023) found...

---

## Reference List Organization

### By Citation Style
- **APA, Chicago**: Alphabetical by first author's last name
- **Nature, Vancouver, IEEE**: Numerical order of first appearance in text

### Hanging Indents
Most styles use hanging indents where the first line is flush left and subsequent lines are indented.

### Consistency
Maintain consistent formatting throughout:
- Capitalization (title case vs. sentence case)
- Journal name abbreviations
- DOI presentation
- Author name format

---

## Engineering Citation Examples

### ASCE (American Society of Civil Engineers) — Author-Year

- In-text: (Smith and Jones 2023) or Smith and Jones (2023)
- Reference: Smith, A. B., and Jones, C. D. (2023). "Seismic performance of steel moment connections." *J. Struct. Eng.*, 149(5), 04023045.
- Note: Article number replaces page range for ASCE journals

### IEEE — Numbered [1]

- In-text: [1], [1]-[3]
- Reference: [1] A. B. Smith and C. D. Jones, "Seismic performance of steel moment connections," *J. Struct. Eng.*, vol. 149, no. 5, Art. no. 04023045, May 2023.
- Note: Use "Art. no." for article numbers

### Elsevier Engineering — Harvard

- In-text: (Smith and Jones, 2023) or Smith and Jones (2023)
- Reference: Smith, A.B., Jones, C.D., 2023. Seismic performance of steel moment connections. Engineering Structures 278, 115542.
- Note: Journal name in full; article number for no-page journals

### GB/T 7714-2015 (Chinese Standard)

- In-text: [1] or (Smith, 2023)
- Reference (Chinese): [1] 张三, 李四. 钢结构梁柱节点抗震性能试验研究[J]. 建筑结构学报, 2023, 44(5): 1-12.
- Reference (English): [1] SMITH A B, JONES C D. Seismic performance of steel moment connections[J]. Journal of Structural Engineering, 2023, 149(5): 04023045.
- Note: Authors in UPPERCASE for English; document type marker [J] for journal, [C] for conference, [D] for dissertation

### ACM — Author-Year

- In-text: (Smith and Jones 2023)
- Reference: Alice B. Smith and Charlie D. Jones. 2023. Seismic performance of steel moment connections. *J. Struct. Eng.* 149, 5 (2023), 1–12.

---

## Engineering Journal Abbreviations

| Full Name | Abbreviation (ASCE/IEEE) | Abbreviation (Elsevier) |
|-----------|-------------------------|------------------------|
| Journal of Structural Engineering | J. Struct. Eng. | J. Constr. Steel Res. |
| Journal of Geotechnical and Geoenvironmental Engineering | J. Geotech. Geoenviron. Eng. | Soils Found. |
| Journal of Materials in Civil Engineering | J. Mater. Civ. Eng. | Cem. Concr. Res. |
| Journal of Computing in Civil Engineering | J. Comput. Civ. Eng. | Adv. Eng. Inform. |
| Journal of Environmental Engineering | J. Environ. Eng. | J. Environ. Manage. |
| Journal of Hydraulic Engineering | J. Hydraul. Eng. | J. Hydrol. |
| Water Research | Water Res. | Water Res. |
| Environmental Science & Technology | Environ. Sci. Technol. | Environ. Sci. Technol. |
| Building and Environment | Build. Environ. | Build. Environ. |
| Automation in Construction | Autom. Constr. | Autom. Constr. |
| Engineering Structures | Eng. Struct. | Eng. Struct. |
| Computers & Structures | Comput. Struct. | Comput. Struct. |
| Earthquake Engineering & Structural Dynamics | Earthquake Eng. Struct. Dyn. | Earthquake Eng. Struct. Dyn. |
| IEEE Transactions on Neural Networks and Learning Systems | IEEE Trans. Neural Netw. Learn. Syst. | — |
| IEEE Transactions on Industrial Informatics | IEEE Trans. Ind. Inform. | — |
