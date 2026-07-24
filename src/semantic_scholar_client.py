"""Async Semantic Scholar API client.

Wraps the S2 Academic Graph API and Recommendations API.
https://api.semanticscholar.org/api-docs/
"""

from __future__ import annotations

import asyncio
import os
import time
from dataclasses import dataclass
from typing import Any

import httpx

S2_GRAPH_BASE = "https://api.semanticscholar.org/graph/v1"
S2_RECOMM_BASE = "https://api.semanticscholar.org/recommendations/v1"

_DEFAULT_TIMEOUT = 30.0
_USER_AGENT = "repo-health-analyzer/0.2.0 (https://github.com/olusegunakinbo167-cell/repo-health-analyzer)"
_MAX_RETRIES = 5
_RETRY_BASE_DELAY = 1.5


@dataclass(slots=True)
class S2Paper:
    """Normalized paper metadata from S2."""

    paper_id: str
    corpus_id: int | None
    title: str | None
    abstract: str | None
    year: int | None
    venue: str | None
    citation_count: int
    influential_citation_count: int
    reference_count: int
    is_open_access: bool
    open_access_pdf_url: str | None
    fields_of_study: list[str]
    external_ids: dict[str, str]
    authors: list[str]

    @classmethod
    def from_s2_json(cls, data: dict[str, Any]) -> S2Paper:
        """Parse an S2 Graph API paper response."""
        oa_pdf = data.get("openAccessPdf")
        pdf_url = oa_pdf.get("url") if isinstance(oa_pdf, dict) else None

        authors_raw = data.get("authors", [])
        authors = [a.get("name", "") for a in authors_raw if isinstance(a, dict)]

        # externalIds may be None
        ext_ids = data.get("externalIds") or {}
        if not isinstance(ext_ids, dict):
            ext_ids = {}

        fos = data.get("fieldsOfStudy") or []
        if not isinstance(fos, list):
            fos = []

        return cls(
            paper_id=str(data.get("paperId", "")),
            corpus_id=data.get("corpusId"),
            title=data.get("title"),
            abstract=data.get("abstract"),
            year=data.get("year"),
            venue=data.get("venue"),
            citation_count=int(data.get("citationCount", 0) or 0),
            influential_citation_count=int(data.get("influentialCitationCount", 0) or 0),
            reference_count=int(data.get("referenceCount", 0) or 0),
            is_open_access=bool(data.get("isOpenAccess", False)),
            open_access_pdf_url=pdf_url,
            fields_of_study=fos,
            external_ids=ext_ids,
            authors=authors,
        )


class SemanticScholarAPIError(RuntimeError):
    """Raised when an S2 API request fails after retries."""

    def __init__(self, status: int, message: str, payload: Any = None) -> None:
        super().__init__(f"S2 API error {status}: {message}")
        self.status = status
        self.payload = payload


class SemanticScholarClient:
    """Async Semantic Scholar Graph / Recommendations API client.

    API key is optional.  Unauthenticated requests share a global rate limit
    and may be throttled during peak use.  With a key, you get a dedicated
    ~1 req/s.

    Set S2_API_KEY or SEMANTIC_SCHOLAR_API_KEY env var, or pass api_key
    explicitly.

    Get a free key at: https://www.semanticscholar.org/product/api#api-key-form
    """

    def __init__(
        self,
        api_key: str | None = None,
        timeout: float = _DEFAULT_TIMEOUT,
        trust_env: bool = False,
    ) -> None:
        self.api_key = (
            api_key
            or os.getenv("S2_API_KEY")
            or os.getenv("SEMANTIC_SCHOLAR_API_KEY")
            or ""
        )
        headers = {
            "Accept": "application/json",
            "User-Agent": _USER_AGENT,
        }
        if self.api_key:
            headers["x-api-key"] = self.api_key

        self._client = httpx.AsyncClient(
            timeout=timeout,
            headers=headers,
            follow_redirects=True,
            trust_env=trust_env,
        )

    async def close(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> SemanticScholarClient:
        return self

    async def __aexit__(self, *args: object) -> None:
        await self.close()

    # ------------------------------------------------------------------
    # Internal: retry wrapper
    # ------------------------------------------------------------------

    async def _request_with_retry(
        self,
        method: str,
        url: str,
        *,
        json_body: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
    ) -> Any:
        """Execute HTTP request with 429 exponential backoff."""
        last_error: SemanticScholarAPIError | None = None

        for attempt in range(_MAX_RETRIES + 1):
            try:
                resp = await self._client.request(
                    method, url, json=json_body, params=params
                )
                if resp.status_code == 429 and attempt < _MAX_RETRIES:
                    # Exponential backoff with jitter
                    backoff = _RETRY_BASE_DELAY * (2**attempt)
                    # Harsher backoff when unauthenticated (shared pool)
                    if not self.api_key:
                        backoff *= 2.0
                    # Cheap jitter
                    jitter = backoff * 0.2 * (0.5 - (time.time() % 1))
                    sleep_s = max(0.5, backoff + jitter)
                    await asyncio.sleep(sleep_s)
                    continue

                if resp.status_code >= 400:
                    try:
                        payload = resp.json()
                        msg = payload.get("message") or payload.get("error") or resp.text
                    except Exception:
                        payload = None
                        msg = resp.text
                    raise SemanticScholarAPIError(resp.status_code, msg, payload)

                return resp.json()

            except httpx.HTTPError as exc:
                # Network-level errors — retry a couple times
                if attempt < 2:
                    await asyncio.sleep(_RETRY_BASE_DELAY * (attempt + 1))
                    continue
                raise SemanticScholarAPIError(0, f"Network error: {exc}") from exc

        if last_error:
            raise last_error
        raise SemanticScholarAPIError(0, "Max retries exceeded")

    # ------------------------------------------------------------------
    # Paper lookup
    # ------------------------------------------------------------------

    _DEFAULT_PAPER_FIELDS = (
        "paperId,corpusId,externalIds,url,title,abstract,"
        "venue,year,referenceCount,citationCount,influentialCitationCount,"
        "isOpenAccess,openAccessPdf,fieldsOfStudy,s2FieldsOfStudy,"
        "publicationVenue,publicationTypes,publicationDate,journal,authors"
    )

    async def get_paper(
        self, paper_id: str, fields: str | None = None
    ) -> S2Paper:
        """Get paper details by S2 ID / DOI / ArXiv / PMID / etc.

        Paper ID formats accepted by S2:
        - S2 CorpusId (numeric or 40-char hex)
        - DOI:<doi>  e.g. "DOI:10.1038/nature14539"
        - ArXiv:<id> e.g. "ArXiv:1706.03762"
        - PMID:<id>, MAG:<id>, ACL:<id>, PubMedCentral:<id>

        Returns:
            S2Paper with normalized metadata.
        """
        fields = fields or self._DEFAULT_PAPER_FIELDS
        from urllib.parse import quote

        pid_enc = quote(paper_id, safe="")
        url = f"{S2_GRAPH_BASE}/paper/{pid_enc}"
        data = await self._request_with_retry(
            "GET", url, params={"fields": fields}
        )
        return S2Paper.from_s2_json(data)

    async def batch_get_papers(
        self, paper_ids: list[str], fields: str | None = None
    ) -> list[S2Paper]:
        """Batch lookup multiple papers (up to ~500 per request).

        Returns:
            List of S2Paper objects, in the same order as paper_ids.
            Missing/unknown papers appear as None in the results list
            from S2 — we filter those out.  Use the len() to check.
        """
        if not paper_ids:
            return []

        fields = fields or self._DEFAULT_PAPER_FIELDS
        url = f"{S2_GRAPH_BASE}/paper/batch"
        data = await self._request_with_retry(
            "POST",
            url,
            params={"fields": fields},
            json_body={"ids": paper_ids},
        )
        # S2 batch endpoint returns a list, with None for unknown IDs
        papers: list[S2Paper] = []
        if isinstance(data, list):
            for item in data:
                if item is None:
                    continue
                try:
                    papers.append(S2Paper.from_s2_json(item))
                except Exception:
                    # Skip malformed entries, don't break the batch
                    continue
        return papers

    # ------------------------------------------------------------------
    # Paper search
    # ------------------------------------------------------------------

    async def search_papers(
        self,
        query: str,
        limit: int = 10,
        offset: int = 0,
        year: str | None = None,
        fields_of_study: list[str] | None = None,
        open_access_pdf: bool = False,
        fields: str | None = None,
    ) -> list[S2Paper]:
        """Search papers by keyword (relevance search)."""
        fields = fields or self._DEFAULT_PAPER_FIELDS
        params: dict[str, Any] = {
            "query": query,
            "limit": str(limit),
            "offset": str(max(0, offset)),
            "fields": fields,
        }
        if year:
            params["year"] = year
        if fields_of_study:
            params["fieldsOfStudy"] = ",".join(fields_of_study)
        if open_access_pdf:
            params["openAccessPdf"] = ""

        url = f"{S2_GRAPH_BASE}/paper/search"
        data = await self._request_with_retry("GET", url, params=params)
        results = data.get("data", []) if isinstance(data, dict) else []
        return [S2Paper.from_s2_json(p) for p in results if isinstance(p, dict)]
