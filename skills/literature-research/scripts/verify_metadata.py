#!/usr/bin/env python3
"""Verify scholarly metadata against Crossref and OpenAlex without dependencies."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from difflib import SequenceMatcher
from typing import Any


USER_AGENT = "CodexLiteratureResearch/1.0 (metadata verification)"


def normalize_doi(value: str | None) -> str | None:
    if not value:
        return None
    value = value.strip().lower()
    value = re.sub(r"^(https?://(dx\.)?doi\.org/|doi:\s*)", "", value)
    return value.rstrip(" .")


def normalize_title(value: str | None) -> str:
    value = unicodedata.normalize("NFKC", value or "").lower()
    value = re.sub(r"[^\w\s]", " ", value, flags=re.UNICODE)
    return " ".join(value.split())


def get_json(url: str) -> dict[str, Any]:
    headers = {"Accept": "application/json", "User-Agent": USER_AGENT}
    request = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(request, timeout=25) as response:
        return json.load(response)


def crossref(doi: str | None, title: str | None, rows: int) -> list[dict[str, Any]]:
    if doi:
        url = "https://api.crossref.org/works/" + urllib.parse.quote(doi, safe="")
        return [get_json(url)["message"]]
    params = urllib.parse.urlencode(
        {
            "query.title": title,
            "rows": rows,
            "select": "DOI,title,author,published,issued,container-title,type,publisher,URL,score",
        }
    )
    return get_json("https://api.crossref.org/works?" + params)["message"]["items"]


def openalex(doi: str | None, title: str | None, rows: int) -> list[dict[str, Any]]:
    mailto = os.environ.get("OPENALEX_MAILTO")
    if doi:
        identifier = "https://doi.org/" + doi
        url = "https://api.openalex.org/works/" + urllib.parse.quote(identifier, safe="")
        if mailto:
            url += "?" + urllib.parse.urlencode({"mailto": mailto})
        return [get_json(url)]
    params: dict[str, Any] = {"search": title, "per-page": rows}
    if mailto:
        params["mailto"] = mailto
    return get_json(
        "https://api.openalex.org/works?" + urllib.parse.urlencode(params)
    )["results"]


def first(value: Any) -> Any:
    return value[0] if isinstance(value, list) and value else value


def year_from_crossref(record: dict[str, Any]) -> int | None:
    parts = (record.get("published") or record.get("issued") or {}).get(
        "date-parts", []
    )
    return parts[0][0] if parts and parts[0] else None


def compact_crossref(record: dict[str, Any]) -> dict[str, Any]:
    authors = []
    for author in record.get("author", []):
        authors.append(
            " ".join(filter(None, [author.get("given"), author.get("family")]))
        )
    return {
        "source": "crossref",
        "id": record.get("DOI"),
        "doi": normalize_doi(record.get("DOI")),
        "title": first(record.get("title")),
        "authors": authors,
        "year": year_from_crossref(record),
        "venue": first(record.get("container-title")),
        "type": record.get("type"),
        "publisher": record.get("publisher"),
        "url": record.get("URL"),
        "source_score": record.get("score"),
    }


def compact_openalex(record: dict[str, Any]) -> dict[str, Any]:
    authors = [
        item.get("author", {}).get("display_name")
        for item in record.get("authorships", [])
        if item.get("author", {}).get("display_name")
    ]
    location = record.get("primary_location") or {}
    source = location.get("source") or {}
    return {
        "source": "openalex",
        "id": record.get("id"),
        "doi": normalize_doi(record.get("doi")),
        "title": record.get("display_name") or record.get("title"),
        "authors": authors,
        "year": record.get("publication_year"),
        "venue": source.get("display_name"),
        "type": record.get("type"),
        "publisher": source.get("host_organization_name"),
        "url": location.get("landing_page_url") or record.get("id"),
        "cited_by_count": record.get("cited_by_count"),
    }


def best(
    records: list[dict[str, Any]], title: str | None, year: int | None
) -> dict[str, Any] | None:
    if not records:
        return None
    if not title:
        return records[0]
    target = normalize_title(title)

    def score(record: dict[str, Any]) -> float:
        similarity = SequenceMatcher(
            None, target, normalize_title(record.get("title"))
        ).ratio()
        if year and record.get("year") and abs(year - record["year"]) > 1:
            similarity -= 0.15
        return similarity

    return max(records, key=score)


def compare(
    cr: dict[str, Any] | None, oa: dict[str, Any] | None
) -> dict[str, Any]:
    if not cr and not oa:
        return {
            "status": "unverified",
            "reason": "No source returned a matching record.",
        }
    if not cr or not oa:
        source = (cr or oa or {}).get("source")
        return {
            "status": "partially_verified",
            "reason": f"Only {source} returned a record.",
        }
    doi_agreement = bool(cr.get("doi") and cr.get("doi") == oa.get("doi"))
    title_similarity = SequenceMatcher(
        None, normalize_title(cr.get("title")), normalize_title(oa.get("title"))
    ).ratio()
    year_agreement = (
        not cr.get("year")
        or not oa.get("year")
        or abs(cr["year"] - oa["year"]) <= 1
    )
    status = (
        "verified"
        if (doi_agreement or title_similarity >= 0.96) and year_agreement
        else "conflict"
    )
    return {
        "status": status,
        "doi_agreement": doi_agreement,
        "title_similarity": round(title_similarity, 4),
        "year_agreement": year_agreement,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--doi", help="DOI or DOI URL")
    group.add_argument("--title", help="Exact or approximate work title")
    parser.add_argument("--year", type=int, help="Expected publication year")
    parser.add_argument("--rows", type=int, default=5, choices=range(1, 21))
    parser.add_argument("--pretty", action="store_true")
    args = parser.parse_args()
    doi = normalize_doi(args.doi)
    output: dict[str, Any] = {
        "query": {"doi": doi, "title": args.title, "year": args.year},
        "errors": {},
    }

    try:
        cr_records = [
            compact_crossref(item)
            for item in crossref(doi, args.title, args.rows)
        ]
    except (
        urllib.error.URLError,
        urllib.error.HTTPError,
        TimeoutError,
        KeyError,
        ValueError,
    ) as exc:
        cr_records = []
        output["errors"]["crossref"] = str(exc)
    try:
        oa_records = [
            compact_openalex(item)
            for item in openalex(doi, args.title, args.rows)
        ]
    except (
        urllib.error.URLError,
        urllib.error.HTTPError,
        TimeoutError,
        KeyError,
        ValueError,
    ) as exc:
        oa_records = []
        output["errors"]["openalex"] = str(exc)

    cr_best = best(cr_records, args.title, args.year)
    oa_best = best(oa_records, args.title, args.year)
    output["crossref"] = {"best_match": cr_best, "candidates": cr_records}
    output["openalex"] = {"best_match": oa_best, "candidates": oa_records}
    output["verification"] = compare(cr_best, oa_best)
    print(
        json.dumps(
            output,
            ensure_ascii=False,
            indent=2 if args.pretty else None,
            sort_keys=args.pretty,
        )
    )
    return 0 if output["verification"]["status"] != "unverified" else 2


if __name__ == "__main__":
    sys.exit(main())
