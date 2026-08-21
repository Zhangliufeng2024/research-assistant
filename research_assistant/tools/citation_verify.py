"""BibTeX citation verification via Crossref, Semantic Scholar, and OpenAlex.

Provides ``verify_citations()`` -- an async tool registered in ToolRegistry
that checks each BibTeX entry against real publication databases and produces
a structured Markdown verification report.

Verification strategy (four-tier fallback):
  1. DOI direct lookup on Crossref     -- deterministic, most reliable
  2. Title+author search on Crossref   -- fuzzy, word-level Jaccard similarity
  3. Title search on Semantic Scholar  -- fallback for non-Crossref publishers
  4. Title search on OpenAlex          -- final fallback

Status labels
-------------
  verified   : confidence >= 0.80
  uncertain  : confidence 0.55-0.79  (partial match, needs manual check)
  unverified : confidence < 0.55     (not found on any source)
"""

from __future__ import annotations

import asyncio
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

import httpx

from ..core import safe_resolve
from ..docgen import parse_bibtex

# ---------------------------------------------------------------------------
# Thresholds and constants
# ---------------------------------------------------------------------------

_VERIFIED_THRESHOLD: float = 0.80
_UNCERTAIN_THRESHOLD: float = 0.55
_MAX_CONCURRENT: int = 4
_REQUEST_DELAY: float = 0.35   # polite inter-request gap (seconds per slot)
_HTTP_TIMEOUT: float = 12.0


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

@dataclass
class CitationResult:
    """Verification result for a single BibTeX entry."""
    key: str
    title: str
    doi: str
    year: int
    authors: str
    status: str = "unverified"      # "verified" | "uncertain" | "unverified"
    confidence: float = 0.0         # 0.0 - 1.0
    matched_title: str | None = None
    matched_doi: str | None = None
    source: str = ""                 # which API resolved it
    note: str = ""


@dataclass
class VerificationReport:
    """Aggregated results for one .bib file."""
    bib_path: str = ""
    total: int = 0
    verified: int = 0
    uncertain: int = 0
    unverified: int = 0
    results: list = field(default_factory=list)

    @property
    def verification_rate(self) -> float:
        return self.verified / self.total if self.total else 0.0

    @property
    def pass_rate(self) -> float:
        return (self.verified + self.uncertain) / self.total if self.total else 0.0


# ---------------------------------------------------------------------------
# Similarity helpers
# ---------------------------------------------------------------------------

def _normalize(text: str) -> str:
    text = re.sub(r"[^a-z0-9 ]", " ", text.lower())
    return re.sub(r"\s+", " ", text).strip()


def _jaccard(a: str, b: str) -> float:
    """Word-level Jaccard similarity between two strings."""
    wa = set(_normalize(a).split())
    wb = set(_normalize(b).split())
    if not wa or not wb:
        return 0.0
    return len(wa & wb) / len(wa | wb)


def _classify(confidence: float) -> str:
    if confidence >= _VERIFIED_THRESHOLD:
        return "verified"
    if confidence >= _UNCERTAIN_THRESHOLD:
        return "uncertain"
    return "unverified"


# ---------------------------------------------------------------------------
# Tier 1: Crossref DOI direct lookup
# ---------------------------------------------------------------------------

async def _crossref_doi(
    doi: str, expected_title: str, client: httpx.AsyncClient
) -> CitationResult | None:
    """Verify a DOI via Crossref /works/{doi}."""
    if not doi:
        return None
    url = f"https://api.crossref.org/works/{doi.strip()}"
    try:
        resp = await client.get(url, timeout=_HTTP_TIMEOUT)
        if resp.status_code == 200:
            msg = resp.json().get("message", {})
            found_title = (msg.get("title") or [""])[0]
            sim = _jaccard(expected_title, found_title) if (expected_title and found_title) else 0.5
            confidence = round(0.75 + sim * 0.25, 3)
            return CitationResult(
                key="", title=expected_title, doi=doi, year=0, authors="",
                status=_classify(confidence), confidence=confidence,
                matched_title=found_title, matched_doi=doi,
                source="crossref_doi",
                note=f"DOI resolved on Crossref (title similarity {sim:.2f})",
            )
        if resp.status_code == 404:
            return CitationResult(
                key="", title=expected_title, doi=doi, year=0, authors="",
                status="unverified", confidence=0.0,
                source="crossref_doi",
                note="DOI not found on Crossref (HTTP 404) -- likely fabricated",
            )
    except (httpx.TimeoutException, httpx.RequestError):
        pass
    return None


# ---------------------------------------------------------------------------
# Tier 2: Crossref title+author search
# ---------------------------------------------------------------------------

async def _crossref_title(
    title: str, authors: str, client: httpx.AsyncClient
) -> CitationResult | None:
    """Search Crossref by bibliographic query."""
    if not title:
        return None
    first_surname = ""
    if authors:
        part = re.split(r"[,;]| and ", authors)[0].strip()
        words = part.split()
        first_surname = words[-1] if words else ""
    query = f"{title} {first_surname}".strip()
    params = {
        "query.bibliographic": query,
        "rows": "5",
        "select": "DOI,title,author,published-print,published-online",
        "mailto": "citation-verify@research-assistant.local",
    }
    try:
        resp = await client.get(
            "https://api.crossref.org/works", params=params, timeout=_HTTP_TIMEOUT
        )
        if resp.status_code != 200:
            return None
        items = resp.json().get("message", {}).get("items", [])
        best_sim, best_item = 0.0, None
        for item in items:
            candidate = (item.get("title") or [""])[0]
            sim = _jaccard(title, candidate)
            if sim > best_sim:
                best_sim, best_item = sim, item
        if best_item and best_sim >= _UNCERTAIN_THRESHOLD:
            found_title = (best_item.get("title") or [""])[0]
            found_doi = best_item.get("DOI", "")
            confidence = round(best_sim, 3)
            return CitationResult(
                key="", title=title, doi="", year=0, authors=authors,
                status=_classify(confidence), confidence=confidence,
                matched_title=found_title, matched_doi=found_doi,
                source="crossref_title",
                note=f"Title match on Crossref (similarity {best_sim:.2f})",
            )
    except (httpx.TimeoutException, httpx.RequestError):
        pass
    return None


# ---------------------------------------------------------------------------
# Tier 3: Semantic Scholar title search
# ---------------------------------------------------------------------------

async def _semantic_scholar_title(
    title: str, ss_api_key: str, client: httpx.AsyncClient
) -> CitationResult | None:
    """Search Semantic Scholar by title."""
    if not title:
        return None
    params = {"query": title, "fields": "title,externalIds", "limit": "5"}
    headers: dict[str, str] = {}
    if ss_api_key:
        headers["x-api-key"] = ss_api_key
    try:
        resp = await client.get(
            "https://api.semanticscholar.org/graph/v1/paper/search",
            params=params, headers=headers, timeout=_HTTP_TIMEOUT,
        )
        if resp.status_code != 200:
            return None
        items = resp.json().get("data", [])
        best_sim, best_item = 0.0, None
        for item in items:
            sim = _jaccard(title, item.get("title", ""))
            if sim > best_sim:
                best_sim, best_item = sim, item
        if best_item and best_sim >= _UNCERTAIN_THRESHOLD:
            found_title = best_item.get("title", "")
            found_doi = (best_item.get("externalIds") or {}).get("DOI", "")
            confidence = round(best_sim, 3)
            return CitationResult(
                key="", title=title, doi="", year=0, authors="",
                status=_classify(confidence), confidence=confidence,
                matched_title=found_title, matched_doi=found_doi,
                source="semantic_scholar",
                note=f"Title match on Semantic Scholar (similarity {best_sim:.2f})",
            )
    except (httpx.TimeoutException, httpx.RequestError):
        pass
    return None


# ---------------------------------------------------------------------------
# Tier 4: OpenAlex title search
# ---------------------------------------------------------------------------

async def _openalex_title(
    title: str, email: str, client: httpx.AsyncClient
) -> CitationResult | None:
    """Search OpenAlex by title."""
    if not title:
        return None
    params: dict[str, str] = {"search": title, "per_page": "5", "select": "title,doi"}
    if email:
        params["mailto"] = email
    try:
        resp = await client.get(
            "https://api.openalex.org/works", params=params, timeout=_HTTP_TIMEOUT
        )
        if resp.status_code != 200:
            return None
        items = resp.json().get("results", [])
        best_sim, best_item = 0.0, None
        for item in items:
            sim = _jaccard(title, item.get("title", "") or "")
            if sim > best_sim:
                best_sim, best_item = sim, item
        if best_item and best_sim >= _UNCERTAIN_THRESHOLD:
            found_title = best_item.get("title", "")
            raw_doi = best_item.get("doi", "")
            found_doi = raw_doi.replace("https://doi.org/", "").strip() if raw_doi else ""
            confidence = round(best_sim, 3)
            return CitationResult(
                key="", title=title, doi="", year=0, authors="",
                status=_classify(confidence), confidence=confidence,
                matched_title=found_title, matched_doi=found_doi,
                source="openalex",
                note=f"Title match on OpenAlex (similarity {best_sim:.2f})",
            )
    except (httpx.TimeoutException, httpx.RequestError):
        pass
    return None


# ---------------------------------------------------------------------------
# Per-citation orchestration
# ---------------------------------------------------------------------------

async def _verify_one(
    ref,
    client: httpx.AsyncClient,
    ss_api_key: str,
    openalex_email: str,
) -> CitationResult:
    """Four-tier verification for a single BibTeX reference."""
    base = CitationResult(
        key=ref.key,
        title=ref.title or "",
        doi=getattr(ref, "doi", "") or "",
        year=ref.year or 0,
        authors=ref.authors or "",
    )

    if base.doi:
        result = await _crossref_doi(base.doi, base.title, client)
        if result:
            result.key, result.year, result.authors = base.key, base.year, base.authors
            return result

    if base.title:
        result = await _crossref_title(base.title, base.authors, client)
        if result and result.confidence >= _UNCERTAIN_THRESHOLD:
            result.key, result.year = base.key, base.year
            return result

    if base.title:
        result = await _semantic_scholar_title(base.title, ss_api_key, client)
        if result and result.confidence >= _UNCERTAIN_THRESHOLD:
            result.key, result.year, result.authors = base.key, base.year, base.authors
            return result

    if base.title:
        result = await _openalex_title(base.title, openalex_email, client)
        if result and result.confidence >= _UNCERTAIN_THRESHOLD:
            result.key, result.year, result.authors = base.key, base.year, base.authors
            return result

    base.status = "unverified"
    base.note = "Not found on Crossref, Semantic Scholar, or OpenAlex"
    return base


async def _verify_batch(
    refs: list,
    ss_api_key: str,
    openalex_email: str,
) -> list:
    """Verify all refs with bounded concurrency and polite rate limiting."""
    semaphore = asyncio.Semaphore(_MAX_CONCURRENT)

    async def _limited(ref, idx: int) -> CitationResult:
        async with semaphore:
            await asyncio.sleep(idx * _REQUEST_DELAY)
            return await _verify_one(ref, client, ss_api_key, openalex_email)

    async with httpx.AsyncClient(
        headers={"User-Agent": "ResearchAssistant/3.0 (citation-verifier)"}
    ) as client:
        tasks = [_limited(ref, i) for i, ref in enumerate(refs)]
        raw = await asyncio.gather(*tasks, return_exceptions=True)

    results: list = []
    for ref, outcome in zip(refs, raw):
        if isinstance(outcome, Exception):
            results.append(CitationResult(
                key=ref.key, title=ref.title or "",
                doi=getattr(ref, "doi", "") or "",
                year=ref.year or 0, authors=ref.authors or "",
                status="unverified", confidence=0.0,
                note=f"Verification error: {outcome}",
            ))
        else:
            results.append(outcome)
    return results


# ---------------------------------------------------------------------------
# Report formatting
# ---------------------------------------------------------------------------

def _format_report(report: VerificationReport) -> str:
    """Render a Markdown verification report."""
    lines = [
        "# Citation Verification Report", "",
        f"**BibTeX file:** `{report.bib_path}`", "",
        "## Summary", "",
        "| Metric | Value |",
        "|--------|-------|",
        f"| Total citations | **{report.total}** |",
        f"| Verified (high confidence) | **{report.verified}** |",
        f"| Uncertain (partial match) | **{report.uncertain}** |",
        f"| Unverified (not found) | **{report.unverified}** |",
        f"| Verification rate | **{report.verification_rate:.0%}** |",
        f"| Pass rate (verified + uncertain) | **{report.pass_rate:.0%}** |",
        "",
    ]
    if report.unverified > 0:
        lines += [
            "> [!CAUTION]",
            f"> **{report.unverified} citation(s) could not be verified.**",
            "> These must be manually checked -- they may be fabricated.",
            "",
        ]
    elif report.uncertain > 0:
        lines += [
            "> [!WARNING]",
            f"> **{report.uncertain} citation(s) are uncertain** (partial title match).",
            "> Please review and confirm they are correct.",
            "",
        ]
    else:
        lines += ["> [!NOTE]", "> All citations verified successfully.", ""]

    lines += ["## Detailed Results", ""]
    status_tag_map = {"verified": "VERIFIED", "uncertain": "UNCERTAIN", "unverified": "UNVERIFIED"}
    for r in report.results:
        tag = status_tag_map.get(r.status, "UNKNOWN")
        lines.append(f"### [{tag}] `{r.key}`")
        lines.append(f"- **Title**: {r.title or '(missing)'}")
        if r.doi:
            lines.append(f"- **DOI**: `{r.doi}`")
        if r.year:
            lines.append(f"- **Year**: {r.year}")
        if r.authors:
            lines.append(f"- **Authors**: {r.authors[:120]}")
        if r.matched_title and r.matched_title != r.title:
            lines.append(f"- **Matched as**: {r.matched_title}")
        if r.matched_doi and not r.doi:
            lines.append(f"- **Found DOI**: `{r.matched_doi}`")
        lines.append(f"- **Confidence**: {r.confidence:.0%}")
        lines.append(f"- **Source**: {r.source or 'none'}")
        lines.append(f"- **Note**: {r.note}")
        lines.append("")

    if report.unverified > 0:
        lines += [
            "## Unverified Citations -- Action Required", "",
            "The following citations must be resolved before paper submission:", "",
        ]
        for r in report.results:
            if r.status == "unverified":
                t = r.title[:80] + "..." if len(r.title) > 80 else r.title
                lines.append(f"- `{r.key}` -- {t}")
        lines += [
            "",
            "**Suggested actions:**",
            "1. Search the title on Google Scholar / Semantic Scholar",
            "2. If the paper exists, add its correct DOI to references.bib",
            "3. If the paper does not exist, replace with a real verified citation",
            "4. Re-run verify_citations after corrections",
        ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Public tool function
# ---------------------------------------------------------------------------

async def verify_bibtex_file(bib_file) -> VerificationReport:
    """Programmatic citation verification for one .bib file.

    Parses *bib_file*, checks every entry against Crossref / Semantic
    Scholar / OpenAlex, and returns a populated :class:`VerificationReport`.
    This is the entry point used by quality gates; ``verify_citations`` is
    the tool-facing wrapper around it.

    Raises:
        FileNotFoundError: bib file missing.
        ValueError: wrong suffix, unparsable content, or no entries.
    """
    bib_path = Path(bib_file)
    if not bib_path.exists():
        raise FileNotFoundError(f"BibTeX file not found: {bib_file}")
    if bib_path.suffix.lower() != ".bib":
        raise ValueError(f"Expected a .bib file, got: {bib_file}")

    try:
        refs = parse_bibtex(str(bib_path))
    except Exception as e:
        raise ValueError(f"Error parsing {bib_file}: {e}") from e
    if not refs:
        raise ValueError(f"No citations found in {bib_file}.")

    ss_api_key = os.getenv("SEMANTIC_SCHOLAR_API_KEY", "")
    openalex_email = os.getenv("OPENALEX_EMAIL", "")
    results = await _verify_batch(refs, ss_api_key, openalex_email)

    report = VerificationReport(bib_path=str(bib_path), total=len(refs))
    for r in results:
        report.results.append(r)
        if r.status == "verified":
            report.verified += 1
        elif r.status == "uncertain":
            report.uncertain += 1
        else:
            report.unverified += 1
    return report


async def verify_citations(
    bib_file: str,
    output_file: str | None = None,
    sandbox: str | None = None,
) -> str:
    """Verify all BibTeX citations against Crossref, Semantic Scholar, and OpenAlex.

    Args:
        bib_file:    Absolute path to the .bib file to verify.
        output_file: Optional path to save the Markdown report.
        sandbox:     Working-directory sandbox path (injected by ToolRegistry).

    Returns:
        A concise summary string, with the full Markdown report appended
        when *output_file* is not specified.
    """
    bib_path = Path(bib_file)
    if sandbox:
        try:
            bib_path = safe_resolve(bib_path, Path(sandbox))
        except ValueError as e:
            return f"Error: {e}"

    try:
        report = await verify_bibtex_file(bib_path)
    except FileNotFoundError as e:
        return f"Error: {e}"
    except ValueError as e:
        return f"Error: {e}"

    report_md = _format_report(report)

    saved_to = ""
    if output_file:
        out_path = Path(output_file)
        if sandbox:
            try:
                check_dir = out_path.parent if out_path.parent.exists() else out_path.parent.parent
                safe_resolve(check_dir, Path(sandbox))
            except ValueError as e:
                return f"Error: output_file path escapes sandbox: {e}"
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(report_md, encoding="utf-8")
        saved_to = str(out_path)

    summary_lines = [
        f"Citation Verification Complete: {bib_path.name}",
        f"  Total: {report.total} | Verified: {report.verified} | "
        f"Uncertain: {report.uncertain} | Unverified: {report.unverified}",
        f"  Verification rate: {report.verification_rate:.0%} | "
        f"Pass rate: {report.pass_rate:.0%}",
    ]
    if report.unverified > 0:
        summary_lines.append(
            f"\nACTION REQUIRED: {report.unverified} unverified citation(s):"
        )
        for r in report.results:
            if r.status == "unverified":
                summary_lines.append(f"  FAIL [{r.key}] {r.title[:70]}")
        summary_lines.append(
            "\nThese citations MUST be replaced with real, verifiable papers."
        )
    elif report.uncertain > 0:
        summary_lines.append(
            f"\n{report.uncertain} uncertain citation(s) need manual review:"
        )
        for r in report.results:
            if r.status == "uncertain":
                summary_lines.append(
                    f"  WARN [{r.key}] {r.title[:60]} (confidence: {r.confidence:.0%})"
                )
    else:
        summary_lines.append("\nAll citations verified successfully.")

    if saved_to:
        summary_lines.append(f"\nFull report saved to: {saved_to}")
    else:
        summary_lines.append("\n--- Full Report ---\n")
        summary_lines.append(report_md)

    return "\n".join(summary_lines)
