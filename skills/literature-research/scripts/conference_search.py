#!/usr/bin/env python3
"""Search computer-science conference papers and download verified open PDFs.

Uses only the Python standard library. API records are untrusted data: this
program parses metadata and downloads documents but never executes retrieved
content.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import random
import re
import sys
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


USER_AGENT = "CodexLiteratureResearch/2.0"
DEFAULT_VENUES = "ICSE,FSE,ASE,ISSTA,ICST,MSR,SANER,ICSME,RE,ESEM,ISSRE"


def user_setting(name: str) -> str:
    config_home = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    path = config_home / "literature-research" / "settings.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return ""
    value = data.get(name) if isinstance(data, dict) else None
    return value.strip() if isinstance(value, str) else ""


def redact_url(url: str) -> str:
    parts = urllib.parse.urlsplit(url)
    query = []
    for key, value in urllib.parse.parse_qsl(parts.query, keep_blank_values=True):
        query.append((key, "<redacted>" if key.lower() in {"api_key", "apikey"} else value))
    return urllib.parse.urlunsplit((parts.scheme, parts.netloc, parts.path, urllib.parse.urlencode(query), parts.fragment))


def normalize_doi(value: str | None) -> str | None:
    if not value:
        return None
    value = re.sub(r"^(https?://(dx\.)?doi\.org/|doi:\s*)", "", value.strip(), flags=re.I)
    return value.rstrip(" .").lower() or None


def normalize_title(value: str | None) -> str:
    value = unicodedata.normalize("NFKC", value or "").lower()
    value = re.sub(r"[^\w\s]", " ", value, flags=re.UNICODE)
    return " ".join(value.split())


def arxiv_id(value: str | None) -> str | None:
    if not value:
        return None
    match = re.search(r"(?:arxiv:|arxiv\.org/(?:abs|pdf)/)?(\d{4}\.\d{4,5}(?:v\d+)?)", value, re.I)
    return match.group(1) if match else None


def text(value: Any) -> str | None:
    if isinstance(value, list):
        value = value[0] if value else None
    return str(value).strip() if value is not None and str(value).strip() else None


@dataclass
class Paper:
    title: str
    authors: list[str] = field(default_factory=list)
    year: int | None = None
    venue: str | None = None
    doi: str | None = None
    arxiv_id: str | None = None
    dblp_key: str | None = None
    abstract: str | None = None
    citation_count: int | None = None
    relevance_score: float = 0.0
    sources: list[str] = field(default_factory=list)
    landing_urls: list[str] = field(default_factory=list)
    open_pdf_candidates: list[dict[str, str]] = field(default_factory=list)
    version_status: str = "version_unconfirmed"
    access_status: str = "metadata_only"
    downloaded_file: str | None = None
    download_error: str | None = None

    def merge(self, other: "Paper") -> None:
        self.authors = self.authors or other.authors
        self.year = self.year or other.year
        self.venue = self.venue or other.venue
        self.doi = self.doi or other.doi
        self.arxiv_id = self.arxiv_id or other.arxiv_id
        self.dblp_key = self.dblp_key or other.dblp_key
        self.abstract = self.abstract or other.abstract
        self.citation_count = max(x for x in (self.citation_count, other.citation_count) if x is not None) if any(x is not None for x in (self.citation_count, other.citation_count)) else None
        self.sources = sorted(set(self.sources + other.sources))
        self.landing_urls = list(dict.fromkeys(self.landing_urls + other.landing_urls))
        seen = {(x.get("url"), x.get("source")) for x in self.open_pdf_candidates}
        self.open_pdf_candidates.extend(x for x in other.open_pdf_candidates if (x.get("url"), x.get("source")) not in seen)
        if self.doi and self.arxiv_id:
            self.version_status = "published_with_preprint"
        elif self.doi or self.dblp_key:
            self.version_status = "published_conference_version"
        elif self.arxiv_id:
            self.version_status = "preprint"
        if self.abstract:
            self.access_status = "abstract_only"
        if self.open_pdf_candidates:
            self.access_status = "open_pdf_found"


class Client:
    def __init__(self, timeout: int = 30, retries: int = 4):
        self.timeout = timeout
        self.retries = retries
        self.contact = os.environ.get("SCHOLAR_CONTACT_EMAIL", "").strip() or user_setting("scholar_contact_email")
        self.events: list[dict[str, Any]] = []
        self.last_request_at: dict[str, float] = {}
        # In some managed environments the HTTPS proxy completes CONNECT but
        # drops DBLP's TLS stream.  DBLP is publicly reachable directly, so use
        # a source-scoped opener without environment proxies.  Other scholarly
        # APIs keep the default opener and its configured proxy behavior.
        self.dblp_opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def request(self, source: str, url: str, headers: dict[str, str] | None = None) -> bytes:
        request_headers = {"Accept": "application/json", "User-Agent": USER_AGENT + (f" (mailto:{self.contact})" if self.contact else "")}
        request_headers.update(headers or {})
        started = time.monotonic()
        for attempt in range(self.retries + 1):
            try:
                if source == "semantic_scholar":
                    wait = 1.1 - (time.monotonic() - self.last_request_at.get(source, 0.0))
                    if wait > 0:
                        time.sleep(wait)
                    self.last_request_at[source] = time.monotonic()
                request = urllib.request.Request(url, headers=request_headers)
                if source == "dblp":
                    response_context = self.dblp_opener.open(request, timeout=self.timeout)
                else:
                    response_context = urllib.request.urlopen(request, timeout=self.timeout)
                with response_context as response:
                    body = response.read()
                    self.events.append({"source": source, "url": redact_url(url), "status": response.status, "bytes": len(body), "elapsed_seconds": round(time.monotonic() - started, 3)})
                    return body
            except urllib.error.HTTPError as exc:
                retryable = exc.code == 429 or 500 <= exc.code < 600
                if retryable and attempt < self.retries:
                    retry_after = exc.headers.get("Retry-After")
                    delay = float(retry_after) if retry_after and retry_after.isdigit() else min(16, 2**attempt) + random.random()
                    time.sleep(delay)
                    continue
                self.events.append({"source": source, "url": redact_url(url), "status": exc.code, "error": str(exc), "elapsed_seconds": round(time.monotonic() - started, 3)})
                raise
            except (urllib.error.URLError, TimeoutError, OSError) as exc:
                if attempt < self.retries:
                    time.sleep(min(16, 2**attempt) + random.random())
                    continue
                self.events.append({"source": source, "url": redact_url(url), "status": None, "error": str(exc), "elapsed_seconds": round(time.monotonic() - started, 3)})
                raise
        raise RuntimeError("unreachable")

    def json(self, source: str, url: str, headers: dict[str, str] | None = None) -> dict[str, Any]:
        return json.loads(self.request(source, url, headers).decode("utf-8"))


def year_value(value: Any) -> int | None:
    try:
        return int(value) if value else None
    except (TypeError, ValueError):
        return None


def search_dblp(client: Client, query: str, limit: int) -> list[Paper]:
    params = urllib.parse.urlencode({"q": query, "format": "json", "h": min(limit, 1000), "c": 0})
    data = client.json("dblp", "https://dblp.org/search/publ/api?" + params)
    hits = data.get("result", {}).get("hits", {}).get("hit", [])
    papers = []
    for hit in hits:
        info = hit.get("info", {})
        raw_authors = info.get("authors", {}).get("author", [])
        if isinstance(raw_authors, (str, dict)):
            raw_authors = [raw_authors]
        authors = [text(x.get("text") if isinstance(x, dict) else x) for x in raw_authors]
        doi = normalize_doi(text(info.get("doi")))
        url = text(info.get("url"))
        papers.append(Paper(title=text(info.get("title")) or "", authors=[x for x in authors if x], year=year_value(info.get("year")), venue=text(info.get("venue")), doi=doi, dblp_key=(url.rsplit("/", 1)[-1] if url else None), sources=["dblp"], landing_urls=[x for x in [url, text(info.get("ee"))] if x]))
    return papers


def search_semantic_scholar(client: Client, query: str, limit: int) -> list[Paper]:
    fields = "title,authors,year,venue,abstract,citationCount,externalIds,url,openAccessPdf"
    params = urllib.parse.urlencode({"query": query, "limit": min(limit, 100), "fields": fields})
    headers = {}
    semantic_scholar_key = os.environ.get("SEMANTIC_SCHOLAR_API_KEY", "").strip() or user_setting("semantic_scholar_api_key")
    if semantic_scholar_key:
        headers["x-api-key"] = semantic_scholar_key
    data = client.json("semantic_scholar", "https://api.semanticscholar.org/graph/v1/paper/search?" + params, headers)
    papers = []
    for item in data.get("data", []):
        ids = item.get("externalIds") or {}
        pdf = item.get("openAccessPdf") or {}
        pdf_url = text(pdf.get("url"))
        papers.append(Paper(title=text(item.get("title")) or "", authors=[x.get("name") for x in item.get("authors", []) if x.get("name")], year=year_value(item.get("year")), venue=text(item.get("venue")), doi=normalize_doi(ids.get("DOI")), arxiv_id=arxiv_id(ids.get("ArXiv")), abstract=text(item.get("abstract")), citation_count=year_value(item.get("citationCount")), sources=["semantic_scholar"], landing_urls=[x for x in [text(item.get("url"))] if x], open_pdf_candidates=([{"url": pdf_url, "source": "semantic_scholar"}] if pdf_url else [])))
    return papers


def oa_pdf(location: dict[str, Any] | None) -> str | None:
    return text((location or {}).get("pdf_url"))


def search_openalex(client: Client, query: str, limit: int, start_year: int | None, end_year: int | None) -> list[Paper]:
    params: dict[str, Any] = {"search": query, "per_page": min(limit, 100)}
    filters = ["type:article"]
    if start_year:
        filters.append(f"from_publication_date:{start_year}-01-01")
    if end_year:
        filters.append(f"to_publication_date:{end_year}-12-31")
    params["filter"] = ",".join(filters)
    openalex_key = os.environ.get("OPENALEX_API_KEY", "").strip() or user_setting("openalex_api_key")
    if openalex_key:
        params["api_key"] = openalex_key
    data = client.json("openalex", "https://api.openalex.org/works?" + urllib.parse.urlencode(params))
    papers = []
    for item in data.get("results", []):
        location = item.get("primary_location") or {}
        source = location.get("source") or {}
        pdfs = []
        for candidate in [location, item.get("best_oa_location")]:
            url = oa_pdf(candidate)
            if url and url not in [x["url"] for x in pdfs]:
                pdfs.append({"url": url, "source": "openalex"})
        papers.append(Paper(title=text(item.get("display_name")) or "", authors=[x.get("author", {}).get("display_name") for x in item.get("authorships", []) if x.get("author", {}).get("display_name")], year=year_value(item.get("publication_year")), venue=text(source.get("display_name")), doi=normalize_doi(item.get("doi")), arxiv_id=next((arxiv_id(x) for x in (item.get("ids") or {}).values() if arxiv_id(x)), None), abstract=None, citation_count=year_value(item.get("cited_by_count")), sources=["openalex"], landing_urls=[x for x in [text(location.get("landing_page_url")), text(item.get("id"))] if x], open_pdf_candidates=pdfs))
    return papers


def search_crossref(client: Client, query: str, limit: int, start_year: int | None, end_year: int | None) -> list[Paper]:
    params: dict[str, Any] = {"query.bibliographic": query, "rows": min(limit, 100), "filter": "type:proceedings-article"}
    if start_year:
        params["filter"] += f",from-pub-date:{start_year}-01-01"
    if end_year:
        params["filter"] += f",until-pub-date:{end_year}-12-31"
    if client.contact:
        params["mailto"] = client.contact
    data = client.json("crossref", "https://api.crossref.org/works?" + urllib.parse.urlencode(params))
    papers = []
    for item in data.get("message", {}).get("items", []):
        date_parts = (item.get("published") or item.get("issued") or {}).get("date-parts", [])
        year = year_value(date_parts[0][0]) if date_parts and date_parts[0] else None
        authors = [" ".join(x for x in [a.get("given"), a.get("family")] if x) for a in item.get("author", [])]
        papers.append(Paper(title=text(item.get("title")) or "", authors=authors, year=year, venue=text(item.get("container-title")), doi=normalize_doi(item.get("DOI")), abstract=text(item.get("abstract")), sources=["crossref"], landing_urls=[x for x in [text(item.get("URL"))] if x]))
    return papers


def search_arxiv(client: Client, query: str, limit: int, delay: float) -> list[Paper]:
    if delay:
        time.sleep(delay)
    params = urllib.parse.urlencode({"search_query": "all:" + query, "start": 0, "max_results": min(limit, 100), "sortBy": "relevance"})
    raw = client.request("arxiv", "https://export.arxiv.org/api/query?" + params, {"Accept": "application/atom+xml"}).decode("utf-8", "replace")
    import xml.etree.ElementTree as ET
    root = ET.fromstring(raw)
    ns = {"a": "http://www.w3.org/2005/Atom", "arxiv": "http://arxiv.org/schemas/atom"}
    papers = []
    for entry in root.findall("a:entry", ns):
        identifier = arxiv_id(text(entry.findtext("a:id", namespaces=ns)))
        published = text(entry.findtext("a:published", namespaces=ns))
        doi = normalize_doi(text(entry.findtext("arxiv:doi", namespaces=ns)))
        authors = [text(x.findtext("a:name", namespaces=ns)) for x in entry.findall("a:author", ns)]
        pdf = f"https://arxiv.org/pdf/{identifier}" if identifier else None
        papers.append(Paper(title=" ".join((text(entry.findtext("a:title", namespaces=ns)) or "").split()), authors=[x for x in authors if x], year=year_value(published[:4] if published else None), venue=text(entry.findtext("arxiv:journal_ref", namespaces=ns)), doi=doi, arxiv_id=identifier, abstract=" ".join((text(entry.findtext("a:summary", namespaces=ns)) or "").split()), sources=["arxiv"], landing_urls=([f"https://arxiv.org/abs/{identifier}"] if identifier else []), open_pdf_candidates=([{"url": pdf, "source": "arxiv"}] if pdf else [])))
    return papers


def add_unpaywall(client: Client, paper: Paper) -> None:
    if not paper.doi or not client.contact:
        return
    url = "https://api.unpaywall.org/v2/" + urllib.parse.quote(paper.doi, safe="/") + "?" + urllib.parse.urlencode({"email": client.contact})
    data = client.json("unpaywall", url)
    location = data.get("best_oa_location") or {}
    pdf = text(location.get("url_for_pdf"))
    if pdf:
        paper.open_pdf_candidates.append({"url": pdf, "source": "unpaywall"})
        paper.sources = sorted(set(paper.sources + ["unpaywall"]))


def add_core(client: Client, paper: Paper) -> None:
    key = os.environ.get("CORE_API_KEY")
    if not key or not paper.doi:
        return
    params = urllib.parse.urlencode({"q": f'doi:"{paper.doi}"', "limit": 10})
    data = client.json("core", "https://api.core.ac.uk/v3/search/works?" + params, {"Authorization": "Bearer " + key})
    for item in data.get("results", []):
        url = text(item.get("downloadUrl"))
        if url:
            paper.open_pdf_candidates.append({"url": url, "source": "core"})
            paper.sources = sorted(set(paper.sources + ["core"]))
            break


def merge_papers(papers: list[Paper]) -> list[Paper]:
    merged: list[Paper] = []
    by_key: dict[str, Paper] = {}
    for paper in papers:
        if not paper.title:
            continue
        keys = []
        if paper.doi:
            keys.append("doi:" + paper.doi)
        if paper.arxiv_id:
            keys.append("arxiv:" + re.sub(r"v\d+$", "", paper.arxiv_id))
        keys.append(f"title:{normalize_title(paper.title)}:{paper.year or ''}")
        target = next((by_key[k] for k in keys if k in by_key), None)
        if target is None:
            target = paper
            merged.append(target)
        else:
            target.merge(paper)
        for key in keys:
            by_key[key] = target
    for paper in merged:
        paper.merge(Paper(title=paper.title))
    return merged


def conference_match(paper: Paper, venues: list[str]) -> bool:
    haystack = f" {paper.venue or ''} "
    return any(re.search(rf"\b{re.escape(venue)}\b", haystack, re.I) for venue in venues)


def relevance_score(paper: Paper, query: str) -> float:
    query_terms = set(normalize_title(query).split())
    if not query_terms:
        return 0.0
    title_terms = set(normalize_title(paper.title).split())
    abstract_terms = set(normalize_title(paper.abstract).split())
    title_overlap = len(query_terms & title_terms) / len(query_terms)
    abstract_overlap = len(query_terms & abstract_terms) / len(query_terms)
    return round(title_overlap * 0.8 + abstract_overlap * 0.2, 4)


def safe_filename(paper: Paper) -> str:
    author = paper.authors[0].split()[-1] if paper.authors else "unknown"
    title = re.sub(r"[^A-Za-z0-9._-]+", "-", paper.title)[:80].strip("-") or "paper"
    return f"{author}-{paper.year or 'undated'}-{title}.pdf"


def download_pdf(client: Client, paper: Paper, directory: Path) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    errors = []
    for candidate in paper.open_pdf_candidates:
        url = candidate.get("url")
        if not url:
            continue
        try:
            body = client.request("pdf:" + candidate.get("source", "unknown"), url, {"Accept": "application/pdf"})
            if not body.startswith(b"%PDF-"):
                errors.append(f"{candidate.get('source')}: response is not a PDF")
                continue
            path = directory / safe_filename(paper)
            path.write_bytes(body)
            paper.downloaded_file = str(path)
            paper.access_status = "full_text_downloaded"
            paper.download_error = None
            return
        except Exception as exc:  # preserve per-candidate failures in the manifest
            errors.append(f"{candidate.get('source')}: {exc}")
    paper.download_error = "; ".join(errors) if errors else "no open PDF candidate"


def write_outputs(out: Path, args: argparse.Namespace, papers: list[Paper], client: Client, source_errors: dict[str, str]) -> None:
    out.mkdir(parents=True, exist_ok=True)
    created = datetime.now(timezone.utc).isoformat()
    payload = {"search": {"query": args.query, "start_year": args.start_year, "end_year": args.end_year, "venues": args.venues, "limit": args.limit, "peer_reviewed_conferences_only": args.conference_only, "searched_at": created}, "configured": {"contact_email": bool(client.contact), "semantic_scholar_api_key": bool(os.environ.get("SEMANTIC_SCHOLAR_API_KEY", "").strip() or user_setting("semantic_scholar_api_key")), "openalex_api_key": bool(os.environ.get("OPENALEX_API_KEY", "").strip() or user_setting("openalex_api_key")), "core_api_key": bool(os.environ.get("CORE_API_KEY")), "ieee_xplore_api_key": bool(os.environ.get("IEEE_XPLORE_API_KEY"))}, "source_errors": source_errors, "requests": client.events, "papers": [asdict(x) for x in papers]}
    (out / "results.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    fields = ["title", "authors", "year", "venue", "doi", "arxiv_id", "dblp_key", "sources", "relevance_score", "version_status", "access_status", "downloaded_file", "download_error"]
    with (out / "results.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for paper in papers:
            row = asdict(paper)
            row["authors"] = "; ".join(paper.authors)
            row["sources"] = "; ".join(paper.sources)
            writer.writerow({key: row.get(key) for key in fields})


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--query", required=True, help="English research query")
    parser.add_argument("--start-year", type=int)
    parser.add_argument("--end-year", type=int)
    parser.add_argument("--limit", type=int, default=20, help="Maximum papers in the final result")
    parser.add_argument("--venues", default=DEFAULT_VENUES, help="Comma-separated venue abbreviations")
    parser.add_argument("--conference-only", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--download", action="store_true", help="Download verified open PDF candidates")
    parser.add_argument("--output", type=Path, default=Path("literature-results"))
    parser.add_argument("--sources", default="dblp,semantic_scholar,openalex,crossref,arxiv")
    parser.add_argument("--timeout", type=int, default=30)
    parser.add_argument("--retries", type=int, default=4)
    parser.add_argument("--arxiv-delay", type=float, default=3.0)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.start_year and args.end_year and args.start_year > args.end_year:
        raise SystemExit("--start-year must not exceed --end-year")
    sources = [x.strip() for x in args.sources.split(",") if x.strip()]
    unknown = set(sources) - {"dblp", "semantic_scholar", "openalex", "crossref", "arxiv"}
    if unknown:
        raise SystemExit("unknown sources: " + ", ".join(sorted(unknown)))
    client = Client(args.timeout, args.retries)
    found: list[Paper] = []
    errors: dict[str, str] = {}
    functions = {
        "dblp": lambda: search_dblp(client, args.query, args.limit),
        "semantic_scholar": lambda: search_semantic_scholar(client, args.query, args.limit),
        "openalex": lambda: search_openalex(client, args.query, args.limit, args.start_year, args.end_year),
        "crossref": lambda: search_crossref(client, args.query, args.limit, args.start_year, args.end_year),
        "arxiv": lambda: search_arxiv(client, args.query, args.limit, args.arxiv_delay),
    }
    for source in sources:
        try:
            found.extend(functions[source]())
        except Exception as exc:
            errors[source] = str(exc)
    papers = merge_papers(found)
    if args.start_year:
        papers = [x for x in papers if x.year is None or x.year >= args.start_year]
    if args.end_year:
        papers = [x for x in papers if x.year is None or x.year <= args.end_year]
    venues = [x.strip() for x in args.venues.split(",") if x.strip()]
    if args.conference_only:
        papers = [x for x in papers if conference_match(x, venues)]
    for paper in papers:
        paper.relevance_score = relevance_score(paper, args.query)
    papers.sort(key=lambda x: (x.relevance_score, x.citation_count or 0, x.year or 0), reverse=True)
    papers = papers[: args.limit]
    for paper in papers:
        try:
            add_unpaywall(client, paper)
        except Exception as exc:
            paper.download_error = "unpaywall: " + str(exc)
        try:
            add_core(client, paper)
        except Exception as exc:
            paper.download_error = ((paper.download_error + "; ") if paper.download_error else "") + "core: " + str(exc)
        paper.merge(Paper(title=paper.title))
        if args.download:
            download_pdf(client, paper, args.output / "pdfs")
    write_outputs(args.output, args, papers, client, errors)
    print(json.dumps({"papers": len(papers), "downloaded": sum(bool(x.downloaded_file) for x in papers), "source_errors": errors, "results": str(args.output / "results.json")}, ensure_ascii=False))
    return 0 if papers else 2


if __name__ == "__main__":
    sys.exit(main())
