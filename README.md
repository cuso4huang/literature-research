# Literature Research Skill

A Codex skill for traceable scholarly literature research across Semantic
Scholar, OpenAlex, Crossref, and arXiv.

It helps an agent:

- discover papers and expand searches;
- verify DOI and bibliographic metadata;
- deduplicate preprints and published versions;
- rank evidence without treating citation counts as quality scores;
- synthesize findings, limitations, disagreements, and research gaps;
- produce evidence tables and citation-ready references.

## Install

Copy `skills/literature-research` into your Codex skills directory:

```bash
mkdir -p "${CODEX_HOME:-$HOME/.codex}/skills"
cp -R skills/literature-research "${CODEX_HOME:-$HOME/.codex}/skills/"
```

Restart Codex after installation, then invoke it explicitly:

```text
Use $literature-research to find and verify recent work on AI agent evaluation.
```

The skill declares Semantic Scholar and arXiv MCP dependencies. Its bundled
metadata verifier uses the public Crossref and OpenAlex APIs and requires
Python 3 with network access. No third-party Python packages or API keys are
required. Setting `OPENALEX_MAILTO` is optional.

## Verify metadata directly

From the skill directory:

```bash
python3 scripts/verify_metadata.py --doi "10.1145/..." --pretty
python3 scripts/verify_metadata.py --title "Paper title" --year 2024 --pretty
```

## License

MIT

