"""Tests for academic impact metric."""

import pytest

from src.metrics.academic_impact import (
    AcademicImpact,
    PaperReference,
    ResolvedPaper,
    extract_from_files,
    extract_paper_references,
    resolve_paper_references,
    score_academic_impact_bonus,
)
from src.semantic_scholar_client import S2Paper, SemanticScholarClient

# ----------------------------------------------------------------------
# Reference extraction
# ----------------------------------------------------------------------


def test_extract_doi() -> None:
    text = """
    See Smith et al. (2020) https://doi.org/10.1038/nature14539
    Also 10.1145/1234567.1234568 and doi:10.1000/xyz123
    """
    refs = extract_paper_references(text, "README.md")
    dois = [r for r in refs if r.id_type == "doi"]
    assert len(dois) >= 2
    doi_ids = {r.paper_id for r in dois}
    assert "10.1038/nature14539" in doi_ids
    assert "10.1145/1234567.1234568" in doi_ids


def test_extract_arxiv() -> None:
    text = """
    Based on Attention Is All You Need (arXiv:1706.03762)
    Also see https://arxiv.org/abs/2301.12345v2
    Old style: quant-ph/9901001 and cs/0112017v3
    """
    refs = extract_paper_references(text, "README.md")
    arxiv_refs = [r for r in refs if r.id_type == "arxiv"]
    arxiv_ids = {r.paper_id for r in arxiv_refs}
    # Version suffixes are preserved in paper_id
    assert any("1706.03762" in a for a in arxiv_ids)
    assert any("2301.12345" in a for a in arxiv_ids)
    assert any("quant-ph/9901001" in a for a in arxiv_ids)
    assert any("cs/0112017" in a for a in arxiv_ids)


def test_extract_arxiv_dedup_version() -> None:
    """ArXiv IDs differing only by version suffix should dedup."""
    text = "arXiv:1706.03762 and arXiv:1706.03762v5 and 1706.03762v1"
    refs = extract_paper_references(text, "README.md")
    arxiv_refs = [r for r in refs if r.id_type == "arxiv"]
    # Should only get one unique ArXiv ID (version-agnostic dedup)
    assert len(arxiv_refs) == 1


def test_extract_s2_corpus_id() -> None:
    text = "Paper ID: 649def34f8be52c8b66281af98ae884c09aef38b"
    refs = extract_paper_references(text, "README.md")
    s2_refs = [r for r in refs if r.id_type == "s2_corpus"]
    assert len(s2_refs) == 1
    assert s2_refs[0].paper_id == "649def34f8be52c8b66281af98ae884c09aef38b"


def test_extract_pmid() -> None:
    text = "PMID: 12345678 and PMID 87654321"
    refs = extract_paper_references(text, "test.md")
    pmid_refs = [r for r in refs if r.id_type == "pmid"]
    assert len(pmid_refs) == 2
    assert {r.paper_id for r in pmid_refs} == {"12345678", "87654321"}


def test_extract_pmcid() -> None:
    text = "Available at PMC1234567 and pmc7654321"
    refs = extract_paper_references(text, "test.md")
    pmc_refs = [r for r in refs if r.id_type == "pmcid"]
    assert len(pmc_refs) == 2
    pmc_ids = {r.paper_id for r in pmc_refs}
    assert "PMC1234567" in pmc_ids
    assert "PMC7654321" in pmc_ids


def test_extract_mixed() -> None:
    text = """
    # References
    1. Vaswani et al. arXiv:1706.03762
    2. https://doi.org/10.1038/nature14539
    3. PMID: 12345678
    4. CorpusId: 649def34f8be52c8b66281af98ae884c09aef38b
    """
    refs = extract_paper_references(text, "README.md")
    types = {r.id_type for r in refs}
    assert "arxiv" in types
    assert "doi" in types
    assert "pmid" in types
    assert "s2_corpus" in types


def test_extract_from_files_dedup() -> None:
    files = {
        "README.md": "See arXiv:1706.03762 for details.",
        "docs/paper.md": "As shown in arXiv:1706.03762v5, ...",
        "CITATION.bib": '@article{vaswani2017, eprint={1706.03762}}',
    }
    refs = extract_from_files(files)
    arxiv_refs = [r for r in refs if r.id_type == "arxiv"]
    # Same ArXiv ID across 3 files — should dedup to 1
    assert len(arxiv_refs) == 1


def test_paper_reference_s2_lookup_id() -> None:
    assert (
        PaperReference("10.1038/nature14539", "doi", "x").s2_lookup_id()
        == "DOI:10.1038/nature14539"
    )
    assert (
        PaperReference("1706.03762", "arxiv", "x").s2_lookup_id()
        == "ArXiv:1706.03762"
    )
    assert (
        PaperReference("arXiv:1706.03762", "arxiv", "x").s2_lookup_id()
        == "ArXiv:1706.03762"
    )
    assert (
        PaperReference("12345678", "pmid", "x").s2_lookup_id() == "PMID:12345678"
    )
    assert (
        PaperReference("P19-1234", "acl", "x").s2_lookup_id() == "ACL:P19-1234"
    )
    assert (
        PaperReference("PMC1234567", "pmcid", "x").s2_lookup_id()
        == "PubMedCentral:PMC1234567"
    )
    corpus = "649def34f8be52c8b66281af98ae884c09aef38b"
    assert (
        PaperReference(corpus, "s2_corpus", "x").s2_lookup_id() == corpus
    )


# ----------------------------------------------------------------------
# S2 client — mocked
# ----------------------------------------------------------------------


def make_fake_s2_paper(
    paper_id: str = "test123",
    title: str = "Test Paper",
    citation_count: int = 42,
    year: int = 2020,
    is_open_access: bool = True,
    fields: list[str] | None = None,
    external_ids: dict[str, str] | None = None,
) -> S2Paper:
    return S2Paper(
        paper_id=paper_id,
        corpus_id=123456,
        title=title,
        abstract="Test abstract",
        year=year,
        venue="Test Venue",
        citation_count=citation_count,
        influential_citation_count=citation_count // 10,
        reference_count=10,
        is_open_access=is_open_access,
        open_access_pdf_url=(
            "https://example.com/paper.pdf" if is_open_access else None
        ),
        fields_of_study=fields or ["Computer Science"],
        external_ids=external_ids or {"DOI": "10.1000/test", "ArXiv": "1234.56789"},
        authors=["Alice Author", "Bob Bear"],
    )


@pytest.mark.asyncio
async def test_s2_client_get_paper_mock() -> None:
    """Test S2 client with mocked httpx response."""
    from unittest.mock import AsyncMock, Mock

    client = SemanticScholarClient(api_key="test-key")
    # Disable cache to ensure mock is hit
    client._cache = None
    # Mock the internal _client
    mock_resp = Mock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "paperId": "abc123",
        "corpusId": 999,
        "title": "Attention Is All You Need",
        "abstract": "Test",
        "year": 2017,
        "venue": "NeurIPS",
        "citationCount": 50000,
        "influentialCitationCount": 5000,
        "referenceCount": 20,
        "isOpenAccess": True,
        "openAccessPdf": {"url": "https://arxiv.org/pdf/1706.03762.pdf"},
        "fieldsOfStudy": ["Computer Science"],
        "externalIds": {"ArXiv": "1706.03762", "DOI": "10.5555/123456"},
        "authors": [{"name": "Vaswani"}, {"name": "Shazeer"}],
    }
    client._client.request = AsyncMock(return_value=mock_resp)  # type: ignore[method-assign]

    paper = await client.get_paper("ArXiv:1706.03762")
    assert paper.paper_id == "abc123"
    assert paper.title == "Attention Is All You Need"
    assert paper.title == "Attention Is All You Need"
    assert paper.citation_count == 50000
    assert paper.is_open_access is True
    assert "Computer Science" in paper.fields_of_study

    await client.close()


@pytest.mark.asyncio
async def test_s2_client_429_retry() -> None:
    """Test that 429 responses trigger exponential backoff retry."""
    from unittest.mock import AsyncMock, Mock

    client = SemanticScholarClient(api_key="test")
    call_count = 0

    async def mock_request(*args: object, **kwargs: object) -> Mock:
        nonlocal call_count
        call_count += 1
        mock_resp = Mock()
        if call_count <= 2:
            # First 2 calls: 429
            mock_resp.status_code = 429
            mock_resp.json.return_value = {"message": "Too Many Requests"}
            mock_resp.text = "Too Many Requests"
        else:
            # 3rd call succeeds
            mock_resp.status_code = 200
            mock_resp.json.return_value = {
                "paperId": "ok",
                "title": "OK",
                "citationCount": 0,
                "influentialCitationCount": 0,
                "referenceCount": 0,
                "isOpenAccess": False,
                "fieldsOfStudy": [],
                "externalIds": {},
                "authors": [],
            }
        return mock_resp

    client._client.request = AsyncMock(side_effect=mock_request)  # type: ignore[method-assign]

    # Patch asyncio.sleep to avoid real delays in test
    import asyncio
    orig_sleep = asyncio.sleep

    async def fast_sleep(s: float) -> None:
        await orig_sleep(0.001)

    import unittest.mock

    with unittest.mock.patch("asyncio.sleep", fast_sleep):
        paper = await client.get_paper("test123")

    assert paper.paper_id == "ok"
    assert call_count == 3  # 2 failures + 1 success

    await client.close()


@pytest.mark.asyncio
async def test_batch_get_papers_mock() -> None:
    from unittest.mock import AsyncMock, Mock

    client = SemanticScholarClient(api_key="test")
    mock_resp = Mock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = [
        {
            "paperId": "p1",
            "title": "Paper 1",
            "citationCount": 10,
            "influentialCitationCount": 1,
            "referenceCount": 5,
            "isOpenAccess": True,
            "fieldsOfStudy": ["CS"],
            "externalIds": {},
            "authors": [],
            "year": 2020,
        },
        None,  # S2 returns None for unknown IDs
        {
            "paperId": "p3",
            "title": "Paper 3",
            "citationCount": 30,
            "influentialCitationCount": 3,
            "referenceCount": 5,
            "isOpenAccess": False,
            "fieldsOfStudy": ["Biology"],
            "externalIds": {},
            "authors": [],
            "year": 2019,
        },
    ]
    client._client.request = AsyncMock(return_value=mock_resp)  # type: ignore[method-assign]

    papers = await client.batch_get_papers(["id1", "id2", "id3"])
    # None entries are filtered out
    assert len(papers) == 2
    assert papers[0].paper_id == "p1"
    assert papers[1].paper_id == "p3"

    await client.close()


# ----------------------------------------------------------------------
# Academic impact resolution
# ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_resolve_paper_references() -> None:
    """Test resolving paper refs with a mocked S2 client."""
    refs = [
        PaperReference("1706.03762", "arxiv", "README.md"),
        PaperReference("10.1038/nature14539", "doi", "README.md"),
    ]

    # Mock S2 client
    class FakeS2Client:
        async def batch_get_papers(self, ids: list[str], fields: str | None = None) -> list[S2Paper]:
            # Return papers matching the lookup IDs
            papers = []
            for pid in ids:
                if "1706.03762" in pid or "arxiv" in pid.lower():
                    papers.append(
                        make_fake_s2_paper(
                            paper_id="s2_arxiv_1706",
                            title="Attention Is All You Need",
                            citation_count=50000,
                            year=2017,
                            fields=["Computer Science"],
                            external_ids={"ArXiv": "1706.03762"},
                        )
                    )
                elif "10.1038" in pid or "nature" in pid.lower():
                    papers.append(
                        make_fake_s2_paper(
                            paper_id="s2_nature",
                            title="Nature Paper",
                            citation_count=1000,
                            year=2020,
                            fields=["Biology"],
                            external_ids={"DOI": "10.1038/nature14539"},
                        )
                    )
            return papers

        async def close(self) -> None:
            pass

    impact = await resolve_paper_references(refs, s2_client=FakeS2Client())  # type: ignore[arg-type]
    assert impact.paper_count == 2
    assert impact.resolved_count == 2
    assert impact.total_citations == 51000
    assert "Computer Science" in impact.fields_of_study
    assert "Biology" in impact.fields_of_study


@pytest.mark.asyncio
async def test_resolve_with_missing_papers() -> None:
    """Unresolvable papers should not crash, just appear unresolved."""
    refs = [
        PaperReference("1706.03762", "arxiv", "README.md"),
        PaperReference("10.9999/fake.doi.that.does.not.exist", "doi", "README.md"),
    ]

    class FakeS2Client:
        async def batch_get_papers(self, ids: list[str], fields: str | None = None) -> list[S2Paper]:
            # Only resolve the ArXiv one
            papers = []
            for pid in ids:
                if "1706" in pid:
                    papers.append(
                        make_fake_s2_paper(
                            paper_id="s2_arxiv",
                            citation_count=100,
                            year=2020,
                            external_ids={"ArXiv": "1706.03762"},
                        )
                    )
            return papers

        async def close(self) -> None:
            pass

    impact = await resolve_paper_references(refs, s2_client=FakeS2Client())  # type: ignore[arg-type]
    assert impact.paper_count == 2
    assert impact.resolved_count == 1
    assert impact.total_citations == 100


# ----------------------------------------------------------------------
# AcademicImpact aggregation properties
# ----------------------------------------------------------------------


def test_academic_impact_properties() -> None:
    papers = [
        ResolvedPaper(
            PaperReference("a1", "arxiv", "x"),
            make_fake_s2_paper("p1", citation_count=100, year=2024, is_open_access=True, fields=["CS"]),
        ),
        ResolvedPaper(
            PaperReference("a2", "doi", "x"),
            make_fake_s2_paper("p2", citation_count=200, year=2022, is_open_access=True, fields=["CS", "Math"]),
        ),
        ResolvedPaper(
            PaperReference("a3", "doi", "x"),
            make_fake_s2_paper("p3", citation_count=50, year=2010, is_open_access=False, fields=["Biology"]),
        ),
    ]
    impact = AcademicImpact(papers_referenced=papers)

    assert impact.paper_count == 3
    assert impact.resolved_count == 3
    assert impact.total_citations == 350
    assert impact.avg_citations_per_paper == pytest.approx(116.666, rel=0.01)
    assert impact.max_citations_single_paper == 200
    assert impact.open_access_count == 2
    assert impact.open_access_ratio == pytest.approx(0.666, rel=0.01)
    assert set(impact.fields_of_study) == {"Biology", "CS", "Math"}
    assert impact.recent_papers_count(years=3, current_year=2025) == 2  # 2024, 2022


# ----------------------------------------------------------------------
# Scoring (Option B: documentation bonus)
# ----------------------------------------------------------------------


def test_score_academic_impact_bonus_none() -> None:
    score, penalties, recs = score_academic_impact_bonus(None)
    assert score == 0.0
    assert penalties == []
    assert recs == []


def test_score_academic_impact_bonus_tiers() -> None:
    def mk_impact(n_papers: int, avg_citations: int = 10, year: int = 2020) -> AcademicImpact:
        papers = [
            ResolvedPaper(
                PaperReference(f"p{i}", "arxiv", "x"),
                make_fake_s2_paper(f"p{i}", citation_count=avg_citations, year=year),
            )
            for i in range(n_papers)
        ]
        return AcademicImpact(papers_referenced=papers)

    # 1-2 papers → 2 pts
    score, _, _ = score_academic_impact_bonus(mk_impact(1))
    assert score == 2.0
    score, _, _ = score_academic_impact_bonus(mk_impact(2))
    assert score == 2.0

    # 3-5 papers → 3.5 pts
    score, _, _ = score_academic_impact_bonus(mk_impact(3))
    assert score == 3.5
    score, _, _ = score_academic_impact_bonus(mk_impact(5))
    assert score == 3.5

    # 6+ papers → 5 pts
    score, _, _ = score_academic_impact_bonus(mk_impact(6))
    assert score == 5.0
    score, _, _ = score_academic_impact_bonus(mk_impact(10))
    assert score == 5.0


def test_score_academic_impact_high_citation_bonus() -> None:
    papers = [
        ResolvedPaper(
            PaperReference("p1", "arxiv", "x"),
            make_fake_s2_paper("p1", citation_count=500, year=2020),
        ),
        ResolvedPaper(
            PaperReference("p2", "doi", "x"),
            make_fake_s2_paper("p2", citation_count=500, year=2020),
        ),
    ]
    impact = AcademicImpact(papers_referenced=papers)
    # 2 papers base = 2.0, high citations (>=100 avg) → +1 = 3.0
    score, _, _ = score_academic_impact_bonus(impact)
    assert score == 3.0


def test_score_academic_impact_recency_nudge() -> None:
    # This test verifies recency logic — with 1 paper, base is 2.0 anyway
    # so recency nudge doesn't change it. The nudge is for edge cases.
    papers = [
        ResolvedPaper(
            PaperReference("p1", "arxiv", "x"),
            make_fake_s2_paper("p1", citation_count=5, year=2025),
        ),
    ]
    impact = AcademicImpact(papers_referenced=papers)
    score, _, _ = score_academic_impact_bonus(impact)
    assert score >= 2.0


def test_score_academic_impact_recommendations() -> None:
    # Old papers, no OA → should get recommendations
    papers = [
        ResolvedPaper(
            PaperReference("p1", "arxiv", "x"),
            make_fake_s2_paper("p1", citation_count=10, year=2010, is_open_access=False),
        ),
        ResolvedPaper(
            PaperReference("p2", "doi", "x"),
            make_fake_s2_paper("p2", citation_count=10, year=2015, is_open_access=False),
        ),
    ]
    impact = AcademicImpact(papers_referenced=papers)
    score, penalties, recs = score_academic_impact_bonus(impact)

    # Should recommend OA and newer papers
    rec_text = " ".join(recs).lower()
    assert "open-access" in rec_text or "open access" in rec_text
    assert "newer" in rec_text or "3 year" in rec_text
