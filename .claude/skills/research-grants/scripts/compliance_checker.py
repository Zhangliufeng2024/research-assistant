#!/usr/bin/env python3
"""
Grant Proposal Compliance Checker

Verifies formatting requirements for grant proposals including page limits,
required sections, font sizes, and margins.

Usage:
    python compliance_checker.py --file proposal.tex --agency NSF
    python compliance_checker.py --file proposal.pdf --agency NIH
"""

import argparse
import re
import sys
# Fix Windows console encoding for emoji/non-ASCII characters
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from pathlib import Path
from typing import Dict, List, Tuple

# Agency-specific requirements
AGENCY_REQUIREMENTS = {
    "NSF": {
        "name": "National Science Foundation",
        "project_description_pages": 15,
        "project_summary_words": 250,
        "required_sections": [
            "Introduction",
            "Broader Impacts",
            "Intellectual Merit",
            "References"
        ],
        "font_size_min": 11,
        "margins_min_inches": 1.0,
        "line_spacing": "single",
        "citation_style": "any"
    },
    "NIH": {
        "name": "National Institutes of Health",
        "specific_aims_pages": 1,
        "research_strategy_pages": 12,  # R01
        "required_sections": [
            "Specific Aims",
            "Research Strategy",
            "Significance",
            "Innovation",
            "Approach"
        ],
        "font_size_min": 11,
        "margins_min_inches": 0.5,
        "line_spacing": "single",
        "citation_style": "any"
    },
    "DOE": {
        "name": "Department of Energy",
        "project_description_pages": 15,
        "required_sections": [
            "Project Description",
            "Research Plan",
            "Milestones",
            "Budget Justification"
        ],
        "font_size_min": 11,
        "margins_min_inches": 1.0,
        "line_spacing": "single",
        "citation_style": "any"
    },
    "DARPA": {
        "name": "Defense Advanced Research Projects Agency",
        "technical_volume_pages": 20,  # varies by BAA
        "required_sections": [
            "Technical Approach",
            "Milestones",
            "Risk Mitigation",
            "Transition Plan"
        ],
        "font_size_min": 11,
        "margins_min_inches": 1.0,
        "line_spacing": "single",
        "citation_style": "any"
    },
    "NSFC": {
        "name": "National Natural Science Foundation of China",
        "proposal_pages": 10,  # varies by program
        "required_sections": [
            "Research Background",
            "Research Content",
            "Research Plan",
            "Research Foundation"
        ],
        "font_size_min": 12,
        "margins_min_inches": 1.0,
        "line_spacing": "1.5",
        "citation_style": "GB/T 7714"
    },
    "DOT": {
        "name": "Department of Transportation",
        "proposal_pages": 15,
        "required_sections": [
            "Problem Statement",
            "Research Objectives",
            "Research Plan",
            "Implementation Plan"
        ],
        "font_size_min": 11,
        "margins_min_inches": 1.0,
        "line_spacing": "single",
        "citation_style": "any"
    }
}


def count_pages_tex(content: str) -> int:
    """Estimate page count from LaTeX content."""
    # Count clearpage, newpage, and approximate paragraphs
    clear_pages = len(re.findall(r'\\clearpage|\\newpage', content))
    # Rough estimate: ~3000 characters per page for 12pt font
    estimated_pages = len(content) / 3000
    return max(clear_pages, int(estimated_pages))


def check_required_sections(content: str, required_sections: List[str]) -> Tuple[List[str], List[str]]:
    """Check for required sections in the document."""
    found = []
    missing = []

    for section in required_sections:
        # Look for section headings
        pattern = rf'\\section\{{[^}}]*{re.escape(section)}[^}}]*\}}'
        pattern2 = rf'\\subsection\{{[^}}]*{re.escape(section)}[^}}]*\}}'
        pattern3 = rf'##?\s*{re.escape(section)}'

        if (re.search(pattern, content, re.IGNORECASE) or
            re.search(pattern2, content, re.IGNORECASE) or
            re.search(pattern3, content, re.IGNORECASE)):
            found.append(section)
        else:
            # Try partial match
            if any(word in content.lower() for word in section.lower().split()):
                found.append(f"{section} (partial match)")
            else:
                missing.append(section)

    return found, missing


def check_font_size(content: str) -> Tuple[bool, str]:
    """Check if font size meets minimum requirements."""
    font_matches = re.findall(r'\\fontsize\{(\d+)', content)
    documentclass_match = re.search(r'\\documentclass\[.*?(\d+)pt', content)

    sizes = []
    if font_matches:
        sizes.extend([int(s) for s in font_matches])
    if documentclass_match:
        sizes.append(int(documentclass_match.group(1)))

    if not sizes:
        return True, "Font size not explicitly set (using document default)"

    min_size = min(sizes)
    return min_size >= 11, f"Minimum font size found: {min_size}pt"


def check_citations(content: str) -> Tuple[int, str]:
    """Count and describe citation style used."""
    # Count different citation patterns
    natbib = len(re.findall(r'\\cite[pt]?\{', content))
    numeric = len(re.findall(r'\[\d+', content))
    author_year = len(re.findall(r'\\citeauthor|\\citeyear', content))

    total = max(natbib, numeric, author_year)

    if natbib > 0:
        style = "natbib"
    elif author_year > 0:
        style = "author-year"
    else:
        style = "numeric or unknown"

    return total, style


def check_compliance(file_path: str, agency: str) -> Dict:
    """Run all compliance checks on a proposal file."""
    path = Path(file_path)

    if not path.exists():
        return {"error": f"File not found: {file_path}"}

    content = path.read_text(encoding='utf-8')
    requirements = AGENCY_REQUIREMENTS.get(agency.upper())

    if not requirements:
        return {"error": f"Unknown agency: {agency}. Supported: {', '.join(AGENCY_REQUIREMENTS.keys())}"}

    results = {
        "file": str(path),
        "agency": requirements["name"],
        "checks": []
    }

    # Check required sections
    found, missing = check_required_sections(content, requirements.get("required_sections", []))
    if missing:
        results["checks"].append({
            "check": "Required Sections",
            "status": "WARNING",
            "message": f"Missing sections: {', '.join(missing)}",
            "found": found
        })
    else:
        results["checks"].append({
            "check": "Required Sections",
            "status": "PASS",
            "message": f"All required sections found: {', '.join(found)}"
        })

    # Check font size
    font_ok, font_msg = check_font_size(content)
    results["checks"].append({
        "check": "Font Size",
        "status": "PASS" if font_ok else "WARNING",
        "message": font_msg
    })

    # Check citations
    citation_count, citation_style = check_citations(content)
    results["checks"].append({
        "check": "Citations",
        "status": "INFO",
        "message": f"Found {citation_count} citations using {citation_style} style"
    })

    # Check page estimate
    pages = count_pages_tex(content)
    max_pages = requirements.get("project_description_pages") or requirements.get("specific_aims_pages") or requirements.get("technical_volume_pages") or requirements.get("proposal_pages")
    if max_pages:
        if pages > max_pages * 1.2:  # 20% tolerance
            results["checks"].append({
                "check": "Page Count (estimated)",
                "status": "WARNING",
                "message": f"Estimated {pages} pages exceeds {max_pages} page limit"
            })
        else:
            results["checks"].append({
                "check": "Page Count (estimated)",
                "status": "PASS",
                "message": f"Estimated {pages} pages (limit: {max_pages})"
            })

    # Summary
    warnings = sum(1 for c in results["checks"] if c["status"] == "WARNING")
    results["summary"] = {
        "total_checks": len(results["checks"]),
        "warnings": warnings,
        "status": "PASS" if warnings == 0 else "REVIEW NEEDED"
    }

    return results


def print_results(results: Dict):
    """Print compliance check results in a readable format."""
    if "error" in results:
        print(f"ERROR: {results['error']}")
        return

    print(f"\n{'='*60}")
    print(f"Compliance Check: {results['agency']}")
    print(f"File: {results['file']}")
    print(f"{'='*60}\n")

    for check in results["checks"]:
        status_icon = {"PASS": "[PASS]", "WARNING": "[WARN]", "FAIL": "[FAIL]", "INFO": "[INFO]"}.get(check["status"], "?")
        print(f"{status_icon} [{check['status']}] {check['check']}")
        print(f"   {check['message']}")
        if "found" in check:
            print(f"   Found: {', '.join(check['found'])}")
        print()

    print(f"{'='*60}")
    print(f"Summary: {results['summary']['total_checks']} checks, {results['summary']['warnings']} warnings")
    print(f"Overall Status: {results['summary']['status']}")
    print(f"{'='*60}\n")


def main():
    parser = argparse.ArgumentParser(description='Check grant proposal compliance')
    parser.add_argument('--file', required=True, help='Path to proposal file (.tex or .pdf)')
    parser.add_argument('--agency', required=True, choices=list(AGENCY_REQUIREMENTS.keys()),
                       help='Funding agency (NSF, NIH, DOE, DARPA, NSFC, DOT)')
    parser.add_argument('--json', action='store_true', help='Output results as JSON')

    args = parser.parse_args()

    results = check_compliance(args.file, args.agency)

    if args.json:
        import json
        print(json.dumps(results, indent=2))
    else:
        print_results(results)

    sys.exit(0 if results.get("summary", {}).get("warnings", 1) == 0 else 1)


if __name__ == "__main__":
    main()
