# Evidence and Deduplication Policy

## Evidence levels

- **Full text inspected:** Detailed claims and quotations may be made with page or section locations.
- **Abstract inspected:** Use only for high-level purpose, method, and reported conclusions; label as abstract-based.
- **Metadata inspected:** Use only for bibliographic facts and discovery.
- **Secondary citation:** Treat as a lead and retrieve the primary work before relying on it.

## Identity hierarchy

1. Exact normalized DOI
2. Exact arXiv identifier and version
3. PMID or another stable database identifier
4. Normalized title, compatible year, and overlapping authors

Normalize DOI values by lowercasing and removing `https://doi.org/`, `http://dx.doi.org/`, and `doi:`. Normalize titles with Unicode normalization, lowercase, whitespace collapse, and punctuation removal.

## Versions

Preserve relationships among preprint, accepted manuscript, conference paper, journal extension, correction, and retraction. Prefer the version of record for bibliographic citation while linking an openly accessible preprint when useful. Do not merge works merely because their titles are similar.

## Verification labels

- **Verified:** Crossref and OpenAlex agree on identity and core metadata, or an authoritative DOI/publisher record resolves the identity.
- **Partially verified:** Only one structured source confirms the record, or sources have a minor explainable disagreement.
- **Conflict:** Sources disagree materially about identity, year, venue, or work type.
- **Unverified:** No authoritative match was obtained.

## Review quality

Record search date, databases, query strings, filters, and inclusion decisions. For systematic-style work, preserve excluded full-text candidates and reasons. Treat citation counts as database- and time-dependent signals.
