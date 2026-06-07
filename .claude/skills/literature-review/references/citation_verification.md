# Citation Verification Protocol

## Purpose
Ensure all citations in scientific documents are real, verifiable, and properly attributed. Prevent hallucinated or inaccurate references.

## Verification Steps

### Step 1: Existence Check
For each citation:
- [ ] Search for the paper by title in Google Scholar or Semantic Scholar
- [ ] Verify authors match the cited authors
- [ ] Verify year of publication matches
- [ ] Confirm the paper exists in the cited journal/proceedings

### Step 2: Metadata Verification
For each citation:
- [ ] DOI resolves correctly (https://doi.org/xxx)
- [ ] Volume and issue numbers are correct
- [ ] Page numbers are correct (or article number for online-only journals)
- [ ] Journal name is complete and correct (not abbreviated incorrectly)

### Step 3: Content Verification
For each citation:
- [ ] The cited claim is actually supported by the paper
- [ ] The citation is not taken out of context
- [ ] The methodology described in the citing paper matches what's claimed
- [ ] Results and conclusions are accurately represented

### Step 4: Cross-Reference Check
- [ ] Check if the paper has been retracted (use Retraction Watch database)
- [ ] Check for errata or corrections
- [ ] Verify the paper hasn't been superseded by a more recent version

## Tools for Verification
| Tool | URL | Use For |
|------|-----|---------|
| Google Scholar | scholar.google.com | General verification |
| Semantic Scholar | semanticscholar.org | AI-powered search, citation graph |
| CrossRef | crossref.org | DOI verification |
| DOI.org | doi.org | DOI resolution |
| Retraction Watch | retractiondatabase.org | Retraction checking |
| DBLP | dblp.org | CS conference/journal verification |
| Scopus | scopus.com | Citation metrics, metadata |

## Red Flags for Hallucinated Citations
- DOI that doesn't resolve
- Authors who don't exist or work in a different field
- Journal that doesn't publish in the cited topic area
- Year that predates the methodology described
- Results that seem too perfect or don't match the paper's quality level
- Citation appears in only one source and can't be found elsewhere

## Verification Reporting Template
```
Citation: [Author(s) (Year) Title. Journal, Volume, Pages. DOI]
Status: ✅ Verified / ⚠️ Partially Verified / ❌ Not Found
Source 1: [URL] - [Finding]
Source 2: [URL] - [Finding]
Issues: [List any discrepancies]
Action: [Keep as-is / Fix metadata / Remove and replace]
```
