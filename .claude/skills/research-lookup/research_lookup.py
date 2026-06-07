#!/usr/bin/env python3
"""
Advanced Multi-Tiered Research Lookup Tool

Routes research queries through a tiered strategy:
1. Academic Strict: Semantic Scholar + OpenAlex + Parallel (concurrent) -> LLM Synthesis
2. Deep Web/Market: Tavily + Parallel (Broad Coverage)
3. General Summary: SEARCH_MODEL via LLM_BASE_URL (Quick Overview)

Prioritizes academic databases for scientific queries to eliminate hallucination.
Supplementary SEARCH_MODEL is invoked when academic databases return thin results.
"""

import os
import sys
import json
import re
import time
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed, Future
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional


def _load_env():
    """Load .env from cwd and parent directories (does not override existing env vars)."""
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    cwd = Path.cwd()
    for p in [cwd] + list(cwd.parents):
        env_file = p / ".env"
        if env_file.exists():
            load_dotenv(dotenv_path=env_file, override=False)
            return
    # Also try script's parent directories
    script_dir = Path(__file__).resolve().parent
    for p in [script_dir] + list(script_dir.parents):
        env_file = p / ".env"
        if env_file.exists():
            load_dotenv(dotenv_path=env_file, override=False)
            return


_load_env()


class ResearchLookup:
    """Intelligent Research Router and Synthesizer."""

    # High-confidence academic intent keywords (explicit paper/citation requests)
    EXPLICIT_ACADEMIC_KEYWORDS = [
        "find papers", "find paper", "cite", "citation", "citations",
        "doi", "pubmed", "pmid", "peer-reviewed", "peer reviewed",
        "systematic review", "meta-analysis", "arxiv", "seminal",
        "highly cited", "landmark study", "clinical trials",
    ]

    # High-confidence web/market intent keywords
    EXPLICIT_WEB_KEYWORDS = [
        "market size", "market share", "market report",
        "company profile", "companies in",
        "pricing of", "stock price", "official site",
        "product documentation", "release notes", "startup funding",
        "industry report", "industry analysis",
    ]

    # Broad academic keywords (lower priority — may appear as background words)
    GENERAL_ACADEMIC_KEYWORDS = [
        "papers", "paper", "articles", "article",
        "journal", "literature", "scholarly",
        "preprint", "research studies", "find local data",
    ]

    def __init__(self, force_backend: Optional[str] = None):
        """Initialize clients and check API availability."""
        self.force_backend = force_backend

        # API Keys
        self.sem_scholar_key = os.getenv("SEMANTIC_SCHOLAR_API_KEY")
        self.openalex_email = os.getenv("OPENALEX_EMAIL")
        self.tavily_key = os.getenv("TAVILY_API_KEY")
        self.parallel_key = os.getenv("PARALLEL_API_KEY")
        self.openrouter_key = os.getenv("LLM_API_KEY")

        # Base URLs
        self.openrouter_url = os.getenv("LLM_BASE_URL", "https://openrouter.ai/api/v1")
        self.parallel_url = os.getenv("PARALLEL_BASE_URL", "https://api.parallel.ai")
        self.tavily_url = "https://api.tavily.com"
        self.sem_scholar_url = "https://api.semanticscholar.org/graph/v1"
        self.openalex_url = "https://api.openalex.org"

        # Models
        self.synth_model = os.getenv("SCIENTIFIC_WRITER_MODEL", "google/gemini-2.0-flash-001")
        self.search_model = os.getenv("SEARCH_MODEL", "perplexity/sonar-pro-search")

    def _detect_intent(self, query: str) -> str:
        """Classify the query into a routing tier using a three-level priority system.

        Priority order:
        1. EXPLICIT_ACADEMIC_KEYWORDS  → academic_strict  (highest confidence)
        2. EXPLICIT_WEB_KEYWORDS       → broad_web        (highest confidence)
        3. GENERAL_ACADEMIC_KEYWORDS   → academic_strict  (lower confidence)
        4. Default                     → general
        """
        if self.force_backend:
            return self.force_backend

        q = query.lower()

        # Level 1: explicit academic intent (paper/citation lookups)
        if any(kw in q for kw in self.EXPLICIT_ACADEMIC_KEYWORDS):
            return "academic_strict"

        # Level 2: explicit web/market intent
        if any(kw in q for kw in self.EXPLICIT_WEB_KEYWORDS):
            return "broad_web"

        # Level 3: broad academic terms (may be background words, but lean academic)
        if any(kw in q for kw in self.GENERAL_ACADEMIC_KEYWORDS):
            return "academic_strict"

        return "general"

    # --- Backend Clients ---

    def _semantic_scholar_search(self, query: str, limit: int = 5) -> List[Dict[str, Any]]:
        """Query Semantic Scholar for academic papers (with one retry on network error)."""
        if not self.sem_scholar_key:
            return []

        endpoint = f"{self.sem_scholar_url}/paper/search"
        headers = {"x-api-key": self.sem_scholar_key}
        params = {
            "query": query,
            "limit": limit,
            "fields": "title,authors,year,abstract,citationCount,venue,externalIds,url"
        }

        for attempt in range(2):
            try:
                resp = requests.get(endpoint, headers=headers, params=params, timeout=15)
                resp.raise_for_status()
                data = resp.json().get("data", [])
                results = []
                for item in data:
                    # Filter None values from authors list to prevent join failures
                    authors = [
                        a.get("name") for a in item.get("authors", [])
                        if isinstance(a, dict) and a.get("name")
                    ]
                    results.append({
                        "source": "Semantic Scholar",
                        "title": item.get("title"),
                        "authors": authors,
                        "year": item.get("year"),
                        "venue": item.get("venue"),
                        "citations": item.get("citationCount"),
                        "doi": item.get("externalIds", {}).get("DOI"),
                        "abstract": item.get("abstract"),
                        "url": item.get("url")
                    })
                return results
            except requests.exceptions.HTTPError as e:
                # Do not retry on client errors (4xx)
                print(f"[Warning] Semantic Scholar HTTP error: {e}", file=sys.stderr)
                return []
            except Exception as e:
                if attempt == 0:
                    print(f"[Warning] Semantic Scholar error (retrying): {e}", file=sys.stderr)
                    time.sleep(2)
                else:
                    print(f"[Warning] Semantic Scholar error: {e}", file=sys.stderr)
        return []

    def _openalex_search(self, query: str, limit: int = 5) -> List[Dict[str, Any]]:
        """Query OpenAlex for publications (with one retry on network error)."""
        endpoint = f"{self.openalex_url}/works"
        params = {
            "search": query,
            "per_page": limit,
            "sort": "cited_by_count:desc"
        }
        if self.openalex_email:
            params["mailto"] = self.openalex_email

        for attempt in range(2):
            try:
                resp = requests.get(endpoint, params=params, timeout=15)
                resp.raise_for_status()
                results = []
                for item in resp.json().get("results", []):
                    # Safely extract venue (primary_location or source can be None)
                    venue = None
                    primary_loc = item.get("primary_location")
                    if primary_loc and isinstance(primary_loc, dict):
                        source = primary_loc.get("source")
                        if source and isinstance(source, dict):
                            venue = source.get("display_name")

                    # Safely extract DOI — support multiple prefix formats
                    raw_doi = item.get("doi") or ""
                    doi = re.sub(r'^https?://(dx\.)?doi\.org/', '', raw_doi).strip() if raw_doi else ""

                    # Safely extract authors (display_name can be None)
                    authors = []
                    for a in item.get("authorships", []):
                        author_obj = a.get("author", {})
                        name = author_obj.get("display_name") if isinstance(author_obj, dict) else None
                        if name:
                            authors.append(name)

                    results.append({
                        "source": "OpenAlex",
                        "title": item.get("display_name"),
                        "authors": authors,
                        "year": item.get("publication_year"),
                        "venue": venue,
                        "citations": item.get("cited_by_count"),
                        "doi": doi,
                        "abstract": None,
                        "url": item.get("doi") or item.get("id")
                    })
                return results
            except requests.exceptions.HTTPError as e:
                print(f"[Warning] OpenAlex HTTP error: {e}", file=sys.stderr)
                return []
            except Exception as e:
                if attempt == 0:
                    print(f"[Warning] OpenAlex error (retrying): {e}", file=sys.stderr)
                    time.sleep(2)
                else:
                    print(f"[Warning] OpenAlex error: {e}", file=sys.stderr)
        return []

    def _parallel_research(self, query: str) -> Dict[str, Any]:
        """Call Parallel Chat API for supplementary academic context.

        Used concurrently inside _academic_strict_route to enrich context without
        replacing structured paper metadata from SS and OA.
        """
        if not self.parallel_key:
            return {"success": False, "error": "No PARALLEL_API_KEY"}
        try:
            from openai import OpenAI
        except ImportError:
            return {"success": False, "error": "openai package not installed"}

        try:
            client = OpenAI(api_key=self.parallel_key, base_url=self.parallel_url)
            model = os.getenv("PARALLEL_MODEL", "core")
            response = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": f"Academic research context: {query}"}],
                stream=False,
            )
            return {
                "success": True,
                "response": response.choices[0].message.content or "",
                "model": model,
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    def _tavily_search(self, query: str) -> Dict[str, Any]:
        """Query Tavily for web search and context."""
        if not self.tavily_key:
            return {"success": False, "error": "No Tavily API Key"}

        endpoint = f"{self.tavily_url}/search"
        payload = {
            "api_key": self.tavily_key,
            "query": query,
            "search_depth": "advanced",
            "include_raw_content": False
        }

        try:
            resp = requests.post(endpoint, json=payload, timeout=20)
            resp.raise_for_status()
            data = resp.json()
            return {
                "success": True,
                "response": "\n\n".join([f"### {r['title']}\n{r['content']}\nLink: {r['url']}" for r in data.get("results", [])]),
                "sources": [{"title": r["title"], "url": r["url"]} for r in data.get("results", [])],
                "backend": "tavily"
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    def _llm_synthesis(self, query: str, context: str, system_prompt: str) -> Dict[str, Any]:
        """Use LLM to synthesize a report from context."""
        if not self.openrouter_key:
            return {"success": False, "error": "No LLM_API_KEY for synthesis"}

        headers = {
            "Authorization": f"Bearer {self.openrouter_key}",
            "Content-Type": "application/json"
        }

        payload = {
            "model": self.synth_model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"Query: {query}\n\nData received from databases:\n{context}"}
            ]
        }

        try:
            resp = requests.post(f"{self.openrouter_url}/chat/completions", headers=headers, json=payload, timeout=60)
            resp.raise_for_status()
            content = resp.json()["choices"][0]["message"]["content"]
            return {"success": True, "response": content}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def _deduplicate_results(self, results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Remove duplicate papers from combined SS + OA results.

        Deduplication is based on DOI (exact match) and normalised title prefix
        (first 80 characters, lowercased).  Papers without DOI or title are kept.
        """
        seen_dois: set = set()
        seen_titles: set = set()
        unique: List[Dict[str, Any]] = []

        for r in results:
            doi = (r.get("doi") or "").strip().lower()
            title = (r.get("title") or "").strip().lower()[:80]

            # Skip if we've already seen this DOI
            if doi and doi in seen_dois:
                continue
            # Skip if we've already seen this title prefix
            if title and title in seen_titles:
                continue

            if doi:
                seen_dois.add(doi)
            if title:
                seen_titles.add(title)
            unique.append(r)

        return unique

    # --- High Level Routes ---

    def _academic_strict_route(self, query: str) -> Dict[str, Any]:
        """Academic pipeline: SS + OA + Parallel run concurrently, SEARCH_MODEL as supplement.

        All three sources fire simultaneously via ThreadPoolExecutor:
        - Semantic Scholar → structured paper metadata (title, DOI, citations, abstract)
        - OpenAlex        → structured paper metadata (sorted by citation count)
        - Parallel        → synthesised academic context text (if PARALLEL_API_KEY set)

        After dedup, if combined papers < 3, SEARCH_MODEL is called as a supplementary
        source to fill gaps and broaden context for the final LLM synthesis step.
        """
        sources_active = ["Semantic Scholar", "OpenAlex"]
        if self.parallel_key:
            sources_active.append("Parallel")
        print(f"[Research] Querying {' + '.join(sources_active)} concurrently...", file=sys.stderr)

        # --- Concurrent fetch ---
        ss_results: List[Dict[str, Any]] = []
        oa_results: List[Dict[str, Any]] = []
        parallel_result: Dict[str, Any] = {"success": False}

        with ThreadPoolExecutor(max_workers=3) as executor:
            futures: Dict[str, Future] = {
                "ss": executor.submit(self._semantic_scholar_search, query),
                "oa": executor.submit(self._openalex_search, query),
            }
            if self.parallel_key:
                futures["parallel"] = executor.submit(self._parallel_research, query)

            for key, future in futures.items():
                try:
                    result = future.result(timeout=30)
                    if key == "ss":
                        ss_results = result
                    elif key == "oa":
                        oa_results = result
                    elif key == "parallel":
                        parallel_result = result
                except Exception as e:
                    print(f"[Warning] {key} future failed: {e}", file=sys.stderr)

        combined = self._deduplicate_results(ss_results + oa_results)

        # --- Supplementary SEARCH_MODEL when academic DBs are thin ---
        search_supplement = ""
        if len(combined) < 3 and self.openrouter_key:
            print(
                f"[Research] Thin DB results ({len(combined)} papers), supplementing with SEARCH_MODEL ({self.search_model})...",
                file=sys.stderr
            )
            supp = self._general_route(query)
            if supp.get("success"):
                search_supplement = (
                    f"\n\n--- Web Search Supplement ({self.search_model}) ---\n"
                    f"{supp['response']}"
                )

        # --- If all sources empty, fall back to general ---
        if not combined and not parallel_result.get("success") and not search_supplement:
            print("[Research] No results from any source. Falling back to general search.", file=sys.stderr)
            return self._general_route(query)

        # --- Build context for synthesis ---
        context_blocks = []
        sources = []
        for i, res in enumerate(combined):
            clean_authors = [a for a in res.get('authors', []) if a] or ["Unknown"]
            authors = ", ".join(clean_authors[:3]) + (" et al." if len(clean_authors) > 3 else "")
            block = (
                f"[{i+1}] {res.get('title', 'Unknown')} ({res.get('year', 'N/A')})\n"
                f"Authors: {authors}\n"
                f"Venue: {res.get('venue', 'N/A')}\n"
                f"Citations: {res.get('citations', 'N/A')}\n"
                f"DOI: {res.get('doi', 'N/A')}\n"
                f"Abstract: {res.get('abstract') or 'N/A'}"
            )
            context_blocks.append(block)
            sources.append({
                "title": res.get('title'),
                "url": res.get('url'),
                "doi": res.get('doi'),
                "source": res.get('source')
            })

        context_str = "\n\n---\n\n".join(context_blocks)

        # Append Parallel context if available
        if parallel_result.get("success") and parallel_result.get("response"):
            context_str += f"\n\n--- Parallel Research Context ---\n{parallel_result['response']}"

        # Append SEARCH_MODEL supplement if triggered
        context_str += search_supplement

        # --- Synthesize ---
        system_prompt = (
            "You are a professional academic synthesizer. Write a systematic report based on the provided data. "
            "Use markdown headers. Include specific DOIs and citation counts. "
            "If a paper is highly cited, highlight it as a landmark study. Be objective and concise."
        )

        synth = self._llm_synthesis(query, context_str, system_prompt)
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        if synth["success"]:
            synth.update({
                "backend": "hybrid_academic",
                "model": self.synth_model,
                "sources": sources,
                "query": query,
                "timestamp": timestamp
            })
            return synth

        # Synthesis failed — explicitly mark as degraded so callers can tell
        synth.update({
            "success": False,
            "degraded": True,
            "backend": "hybrid_academic",
            "model": self.synth_model,
            "query": query,
            "timestamp": timestamp,
            "sources": sources,
            "response": "Synthesis failed, raw paper data is in sources."
        })
        return synth

    def _broad_web_route(self, query: str) -> Dict[str, Any]:
        """Tavily/Parallel route for market/news."""
        if self.tavily_key:
            print("[Research] Routing to Tavily...", file=sys.stderr)
            res = self._tavily_search(query)
            if res["success"]:
                res.update({"query": query, "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "model": "tavily-advanced"})
                return res

        # Fallback to Parallel
        if self.parallel_key:
            print("[Research] Routing to Parallel...", file=sys.stderr)
            return self._parallel_lookup(query)

        return self._general_route(query)

    def _general_route(self, query: str) -> Dict[str, Any]:
        """SEARCH_MODEL route via LLM_BASE_URL."""
        if not self.openrouter_key:
            return {
                "success": False,
                "error": "No LLM_API_KEY set. Cannot perform general search.",
                "query": query,
                "backend": "general",
                "model": self.search_model,
                "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            }
        print(f"[Research] Routing to General Search ({self.search_model})...", file=sys.stderr)

        headers = {
            "Authorization": f"Bearer {self.openrouter_key}",
            "Content-Type": "application/json"
        }

        payload = {
            "model": self.search_model,
            "messages": [{"role": "user", "content": query}]
        }

        try:
            resp = requests.post(f"{self.openrouter_url}/chat/completions", headers=headers, json=payload, timeout=90)
            resp.raise_for_status()
            data = resp.json()
            content = data["choices"][0]["message"]["content"]

            # Extract sources if provided by Perplexity / compatible search models
            sources = []
            if "citations" in data:
                sources = [{"url": c} for c in data["citations"]]
            elif "search_results" in data:
                sources = [{"title": r.get("title"), "url": r.get("url")} for r in data["search_results"]]

            return {
                "success": True,
                "query": query,
                "response": content,
                "sources": sources,
                "backend": "general",
                "model": self.search_model,
                "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    def _parallel_lookup(self, query: str) -> Dict[str, Any]:
        """Parallel client for broad_web route (standalone call, not concurrent)."""
        try:
            from openai import OpenAI
        except ImportError:
            return {"success": False, "error": "OpenAI package missing"}

        client = OpenAI(api_key=self.parallel_key, base_url=self.parallel_url)
        model = os.getenv("PARALLEL_MODEL", "core")

        try:
            response = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": query}],
                stream=False,
            )
            content = response.choices[0].message.content or ""
            return {
                "success": True,
                "query": query,
                "response": content,
                "backend": "parallel",
                "model": model,
                "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    def lookup(self, query: str) -> Dict[str, Any]:
        """Main entry point for lookup."""
        intent = self._detect_intent(query)
        print(f"[Research] Intent detected: {intent}", file=sys.stderr)

        if intent == "academic_strict":
            return self._academic_strict_route(query)
        elif intent == "broad_web":
            return self._broad_web_route(query)
        else:
            return self._general_route(query)

    def batch_lookup(self, queries: List[str]) -> List[Dict[str, Any]]:
        return [self.lookup(q) for q in queries]


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Multi-Tier Research Router")
    parser.add_argument("query", nargs="?", help="Research query")
    parser.add_argument("-o", "--output", help="Save result to file")
    parser.add_argument("--json", action="store_true", help="JSON output")
    parser.add_argument("--force-backend", choices=["academic_strict", "broad_web", "general"], help="Force tier")
    args = parser.parse_args()

    if not args.query:
        parser.print_help()
        return

    research = ResearchLookup(force_backend=args.force_backend)
    result = research.lookup(args.query)

    if args.json:
        output_text = json.dumps(result, indent=2, ensure_ascii=False)
    else:
        if result.get("success"):
            lines = [
                f"\n{'='*40}",
                f"Backend: {result['backend']} | Model: {result['model']}",
                f"{'='*40}\n",
                result["response"],
            ]
            if result.get("sources"):
                lines.append(f"\nSources ({len(result['sources'])}):")
                for i, s in enumerate(result["sources"]):
                    lines.append(f"  [{i+1}] {s.get('title', 'Unknown')} - {s.get('url', s.get('doi', ''))}")
            output_text = "\n".join(lines)
        else:
            lines = [f"Error: {result.get('error', 'Unknown error')}"]
            if result.get("degraded"):
                lines.append("Note: Result is degraded — synthesis failed but source data is available.")
            output_text = "\n".join(lines)

    print(output_text)

    if args.output:
        out_path = Path(args.output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(output_text, encoding="utf-8")
        print(f"\n[Saved] {out_path}", file=sys.stderr)


if __name__ == "__main__":
    main()
