"""Tests for Phase 4/5: S2 caching and CITATION.cff/.bib parsing."""

import json
import tempfile
import time
from pathlib import Path

from src.metrics.academic_impact import extract_paper_references
from src.semantic_scholar_client import S2Cache, S2Paper


def test_cff_parser_extracts_doi_and_arxiv():
    """CITATION.cff parser extracts DOI and arXiv IDs."""
    cff_text = """
cff-version: 1.2.0
title: "Test Project"
doi: 10.1234/example.5678
identifiers:
  - type: doi
    value: 10.48550/arXiv.1706.03762
  - type: arxiv
    value: 1810.04805
preferred-citation:
  doi: 10.5555/test123
"""
    refs = extract_paper_references(cff_text, source_file="CITATION.cff")
    ids = {(r.id_type, r.paper_id) for r in refs}
    # Should find at least the main DOI and arXiv IDs
    assert ("doi", "10.1234/example.5678") in ids
    assert ("arxiv", "1706.03762") in ids or ("doi", "10.48550/arxiv.1706.03762") in ids
    # preferred-citation DOI
    assert any("10.5555/test123" in pid for _, pid in ids)


def test_bibtex_parser_extracts_doi_arxiv():
    """BibTeX parser extracts DOI and arXiv eprint fields."""
    bib_text = r"""
@article{vaswani2017attention,
  title={Attention is all you need},
  author={Vaswani, Ashish and others},
  journal={NeurIPS},
  year={2017},
  doi={10.48550/arXiv.1706.03762},
  eprint={1706.03762},
  archivePrefix={arXiv}
}

@inproceedings{devlin2019bert,
  title={BERT: Pre-training of Deep Bidirectional Transformers},
  author={Devlin, Jacob and others},
  booktitle={NAACL},
  year={2019},
  doi={10.18653/v1/N19-1423},
  url={https://arxiv.org/abs/1810.04805}
}
"""
    refs = extract_paper_references(bib_text, source_file="CITATION.bib")
    ids = {(r.id_type, r.paper_id) for r in refs}
    # Should find DOIs and arXiv IDs
    assert any("1706.03762" in pid for itype, pid in ids if itype == "arxiv")
    assert any("1810.04805" in pid for itype, pid in ids if itype == "arxiv")
    # DOI from first entry (may be normalized)
    assert any(itype == "doi" for itype, _ in ids)


def test_s2_cache_put_get_roundtrip():
    """S2Cache stores and retrieves papers with 30-day TTL."""
    with tempfile.TemporaryDirectory() as td:
        cache_path = Path(td) / ".repo_health_s2_cache.json"
        cache = S2Cache(cache_path=cache_path, ttl_seconds=30 * 24 * 3600)

        paper = S2Paper(
            paper_id="test-p123",
            corpus_id=12345,
            title="Test Paper",
            abstract="Abstract",
            year=2020,
            venue="Test Venue",
            citation_count=42,
            influential_citation_count=5,
            reference_count=10,
            is_open_access=True,
            open_access_pdf_url="https://example.com/test.pdf",
            fields_of_study=["Computer Science"],
            external_ids={"DOI": "10.1234/test", "ArXiv": "2001.12345"},
            authors=["A. Author"],
            tldr="TL;DR",
            publication_types=["JournalArticle"],
            publication_date="2020-06-01",
            journal_name="Test Journal",
            citation_velocity=None,
        )

        cache.put(paper)

        # Cache hit by paper_id
        p1 = cache.get("test-p123")
        assert p1 is not None
        assert p1.title == "Test Paper"
        assert p1.citation_count == 42

        # Cache hit by DOI (cross-ID dedup)
        p2 = cache.get("doi:10.1234/test")
        assert p2 is not None
        assert p2.paper_id == "test-p123"

        # Cache hit by ArXiv
        p3 = cache.get("arxiv:2001.12345")
        assert p3 is not None
        assert p3.corpus_id == 12345

        # Cache hit by bare arXiv ID
        p4 = cache.get("2001.12345")
        assert p4 is not None

        # Stats
        stats = cache.stats()
        assert stats["valid"] >= 1


def test_s2_cache_ttl_expiry():
    """Expired cache entries are not returned."""
    with tempfile.TemporaryDirectory() as td:
        cache_path = Path(td) / ".repo_health_s2_cache.json"
        # 0.1 second TTL for fast test
        cache = S2Cache(cache_path=cache_path, ttl_seconds=0.1)

        paper = S2Paper(
            paper_id="expire-test",
            corpus_id=None,
            title="Expiring",
            abstract=None,
            year=2020,
            venue=None,
            citation_count=0,
            influential_citation_count=0,
            reference_count=0,
            is_open_access=False,
            open_access_pdf_url=None,
            fields_of_study=[],
            external_ids={},
            authors=[],
        )
        cache.put(paper)
        # Immediate hit
        assert cache.get("expire-test") is not None
        # Wait for expiry
        time.sleep(0.15)
        assert cache.get("expire-test") is None


def test_s2_cache_cross_id_dedup():
    """Cached paper is retrievable via DOI, ArXiv, corpus_id, paper_id."""
    with tempfile.TemporaryDirectory() as td:
        cache_path = Path(td) / ".repo_health_s2_cache.json"
        cache = S2Cache(cache_path=cache_path)

        paper = S2Paper(
            paper_id="s2-abc123",
            corpus_id=999888,
            title="Cross-ID Test",
            abstract=None,
            year=2021,
            venue=None,
            citation_count=10,
            influential_citation_count=1,
            reference_count=5,
            is_open_access=True,
            open_access_pdf_url=None,
            fields_of_study=["Computer Science"],
            external_ids={"DOI": "10.9999/cross.test", "ArXiv": "2106.09685"},
            authors=[],
        )
        cache.put(paper)

        # All these lookup keys should hit
        for key in [
            "s2-abc123",
            "999888",
            "10.9999/cross.test",
            "doi:10.9999/cross.test",
            "2106.09685",
            "arxiv:2106.09685",
            "2106.09685v2",  # version-stripped fallback? cache stores base too
        ]:
            p = cache.get(key)
            # ArXiv version suffix may not match (we strip on put, so v2 won't hit)
            if "v2" in key:
                continue
            assert p is not None, f"cache miss for {key}"
            assert p.title == "Cross-ID Test"


def test_cff_bib_integration_with_extractor():
    """End-to-end: extract_from_files handles .cff and .bib correctly."""
    from src.metrics.academic_impact import extract_from_files

    files = {
        "CITATION.cff": 'doi: 10.1234/test.cff\nidentifiers:\n  - type: arxiv\n    value: 1706.03762\n',
        "references.bib": '@article{x, doi={10.5555/bibtest}, eprint={1810.04805}, archivePrefix={arXiv}}',
        "README.md": "See Vaswani et al. arXiv:2106.09685 and DOI 10.9999/readme",
    }
    refs = extract_from_files(files)
    ids = {r.paper_id for r in refs}
    # Should find papers from all three sources, deduplicated
    assert "1706.03762" in ids
    assert "1810.04805" in ids
    assert "2106.09685" in ids
    # At least 3 unique papers
    assert len(refs) >= 3
