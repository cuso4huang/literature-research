#!/usr/bin/env python3
"""Offline tests for conference_search.py."""

import tempfile
import unittest
from unittest.mock import MagicMock, patch
from pathlib import Path

import conference_search as cs


class FakeClient:
    def __init__(self, bodies):
        self.bodies = iter(bodies)

    def request(self, source, url, headers=None):
        return next(self.bodies)


class ConferenceSearchTests(unittest.TestCase):
    def test_identifier_normalization(self):
        self.assertEqual(cs.normalize_doi("https://doi.org/10.1145/ABC.1 "), "10.1145/abc.1")
        self.assertEqual(cs.arxiv_id("https://arxiv.org/pdf/2401.12345v2"), "2401.12345v2")

    def test_merge_preserves_published_and_preprint_versions(self):
        published = cs.Paper(title="Testing Agents", year=2025, doi="10.1/example", venue="ICSE", sources=["dblp"])
        preprint = cs.Paper(title="Testing Agents", year=2025, arxiv_id="2501.12345", abstract="Abstract", sources=["arxiv"])
        papers = cs.merge_papers([published, preprint])
        self.assertEqual(len(papers), 1)
        self.assertEqual(papers[0].version_status, "published_with_preprint")
        self.assertEqual(papers[0].access_status, "abstract_only")

    def test_download_rejects_html_then_accepts_pdf(self):
        paper = cs.Paper(title="A Paper", year=2026, authors=["Ada Lovelace"], open_pdf_candidates=[{"url": "https://bad", "source": "bad"}, {"url": "https://good", "source": "good"}])
        with tempfile.TemporaryDirectory() as directory:
            cs.download_pdf(FakeClient([b"<html>login</html>", b"%PDF-1.7\nvalid"]), paper, Path(directory))
            self.assertEqual(paper.access_status, "full_text_downloaded")
            self.assertTrue(Path(paper.downloaded_file).read_bytes().startswith(b"%PDF-"))

    def test_conference_filter_uses_whole_abbreviation(self):
        self.assertTrue(cs.conference_match(cs.Paper(title="x", venue="ICSE"), ["ICSE"]))
        self.assertFalse(cs.conference_match(cs.Paper(title="x", venue="ICSEW"), ["ICSE"]))

    def test_relevance_prioritizes_title_matches(self):
        title_match = cs.Paper(title="LLM software testing", abstract="")
        abstract_match = cs.Paper(title="An unrelated title", abstract="LLM software testing")
        self.assertGreater(cs.relevance_score(title_match, "LLM software testing"), cs.relevance_score(abstract_match, "LLM software testing"))

    def test_user_setting_reads_contact_email(self):
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / "literature-research"
            config.mkdir()
            (config / "settings.json").write_text('{"scholar_contact_email":"person@example.edu"}', encoding="utf-8")
            with patch.dict("os.environ", {"XDG_CONFIG_HOME": directory}):
                self.assertEqual(cs.user_setting("scholar_contact_email"), "person@example.edu")

    def test_user_setting_reads_openalex_key(self):
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / "literature-research"
            config.mkdir()
            (config / "settings.json").write_text('{"openalex_api_key":"test-key"}', encoding="utf-8")
            with patch.dict("os.environ", {"XDG_CONFIG_HOME": directory}):
                self.assertEqual(cs.user_setting("openalex_api_key"), "test-key")

    def test_request_log_url_redacts_api_keys(self):
        redacted = cs.redact_url("https://example.test/works?api_key=secret&search=testing")
        self.assertNotIn("secret", redacted)
        self.assertIn("search=testing", redacted)

    def test_dblp_request_bypasses_environment_proxy(self):
        response = MagicMock()
        response.__enter__.return_value = response
        response.status = 200
        response.read.return_value = b'{"result":{"hits":{"hit":[]}}}'
        direct_opener = MagicMock()
        direct_opener.open.return_value = response

        with patch.object(cs.urllib.request, "build_opener", return_value=direct_opener), patch.object(
            cs.urllib.request,
            "urlopen",
            side_effect=AssertionError("DBLP must not use the environment proxy opener"),
        ):
            client = cs.Client(timeout=1, retries=0)
            body = client.request("dblp", "https://dblp.org/search/publ/api?q=test&format=json")

        self.assertIn(b'"result"', body)
        direct_opener.open.assert_called_once()


if __name__ == "__main__":
    unittest.main()
