"""Async Semantic Scholar API client.

Wraps the S2 Academic Graph API and Recommendations API.
https://api.semanticscholar.org/api-docs/
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

S2_GRAPH_BASE = "https://api.semanticscholar.org/graph/v1"
S2_RECOMM_BASE = "https://api.semanticscholar.org/recommendations/v1"

_DEFAULT_TIMEOUT = 30.0
_USER_AGENT = "repo-health-analyzer/0.3.0 (https://github.com/olusegunakinbo167-cell/repo-health-analyzer)"
_MAX_RETRIES = 5
_RETRY_BASE_DELAY = 1.5

# Cache config (Phase 4)
_S2_CACHE_FILENAME = ".repo_health_s2_cache.json"
_S2_CACHE_TTL_SECONDS = 30 * 24 * 3600  # 30 days


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
    # --- Enhanced academic impact fields (Phase 1) ---
    tldr: str | None = None
    publication_types: list[str] = None  # e.g. ["JournalArticle", "Review"]
    publication_date: str | None = None  # ISO date, e.g. "2017-06-12"
    journal_name: str | None = None
    citation_velocity: int | None = None  # citations / year, if available from S2

    def __post_init__(self) -> None:
        # Ensure publication_types is always a list
        if self.publication_types is None:
            object.__setattr__(self, "publication_types", [])

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

        # --- Enhanced fields ---
        # TLDR
        tldr_text: str | None = None
        tldr_obj = data.get("tldr")
        if isinstance(tldr_obj, dict):
            tldr_text = tldr_obj.get("text")

        # Publication types
        pub_types = data.get("publicationTypes") or []
        if not isinstance(pub_types, list):
            pub_types = []

        # Publication date (ISO)
        pub_date = data.get("publicationDate")

        # Journal name
        journal_name: str | None = None
        journal_obj = data.get("journal")
        if isinstance(journal_obj, dict):
            journal_name = journal_obj.get("name")

        # Citation velocity - S2 doesn't provide this directly in Graph API v1
        # Compute age-normalized velocity client-side in AcademicImpact metrics.
        # Leave as None here; could be populated from S2 Recommendations API later.
        citation_velocity = data.get("citationVelocity")
        if citation_velocity is not None:
            try:
                citation_velocity = int(citation_velocity)
            except (ValueError, TypeError):
                citation_velocity = None

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
            # Enhanced fields
            tldr=tldr_text,
            publication_types=pub_types,
            publication_date=pub_date,
            journal_name=journal_name,
            citation_velocity=citation_velocity,
        )

    def to_cache_dict(self) -> dict[str, Any]:
        """Serialize to JSON-serializable dict for disk cache."""
        return {
            "paperId": self.paper_id,
            "corpusId": self.corpus_id,
            "title": self.title,
            "abstract": self.abstract,
            "year": self.year,
            "venue": self.venue,
            "citationCount": self.citation_count,
            "influentialCitationCount": self.influential_citation_count,
            "referenceCount": self.reference_count,
            "isOpenAccess": self.is_open_access,
            "openAccessPdf": {"url": self.open_access_pdf_url} if self.open_access_pdf_url else None,
            "fieldsOfStudy": self.fields_of_study,
            "externalIds": self.external_ids,
            "authors": [{"name": n} for n in self.authors],
            "tldr": {"text": self.tldr} if self.tldr else None,
            "publicationTypes": self.publication_types,
            "publicationDate": self.publication_date,
            "journal": {"name": self.journal_name} if self.journal_name else None,
            "citationVelocity": self.citation_velocity,
        }


class SemanticScholarAPIError(RuntimeError):
    """Raised when an S2 API request fails after retries."""

    def __init__(self, status: int, message: str, payload: Any = None) -> None:
        super().__init__(f"S2 API error {status}: {message}")
        self.status = status
        self.payload = payload


# ----------------------------------------------------------------------
# S2 response cache (Phase 4)
# ----------------------------------------------------------------------


class S2Cache:
    """Local disk cache for S2 paper responses.

    Cache file: .repo_health_s2_cache.json
    TTL: 30 days
    Keys: normalized lookup IDs (doi:..., arxiv:..., pmid:..., corpus_id, s2_paper_id)
    Values: {timestamp: float, paper: S2Paper JSON}

    Cross-ID deduplication: when a paper is cached, all its external IDs
    (DOI, ArXiv, PMID, ACL, CorpusId, paperId) are indexed to the same
    cached entry, so lookups via any alias hit the cache.
    """

    def __init__(self, cache_path: str | Path | None = None, ttl_seconds: int = _S2_CACHE_TTL_SECONDS):
        if cache_path is None:
            # Default: repo root / CWD / home
            for base in [Path.cwd(), Path.home()]:
                p = base / _S2_CACHE_FILENAME
                if p.exists():
                    cache_path = p
                    break
            else:
                cache_path = Path.cwd() / _S2_CACHE_FILENAME

        self.cache_path = Path(cache_path)
        self.ttl_seconds = ttl_seconds
        self._mem_cache: dict[str, tuple[float, dict[str, Any]]] = {}
        self._loaded = False
        self._dirty = False

    def _load(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        if not self.cache_path.exists():
            return
        try:
            with self.cache_path.open("r", encoding="utf-8") as f:
                data = json.load(f)
            now = time.time()
            for key, entry in data.items():
                if not isinstance(entry, dict):
                    continue
                ts = entry.get("timestamp", 0)
                paper_json = entry.get("paper")
                if not paper_json:
                    continue
                # Expire stale entries
                if now - ts > self.ttl_seconds:
                    self._dirty = True
                    continue
                self._mem_cache[key.lower()] = (ts, paper_json)
        except Exception:
            # Corrupt cache — start fresh
            self._mem_cache.clear()

    def _save(self) -> None:
        if not self._dirty:
            return
        try:
            # Prune expired
            now = time.time()
            data = {
                k: {"timestamp": ts, "paper": pj}
                for k, (ts, pj) in self._mem_cache.items()
                if now - ts <= self.ttl_seconds
            }
            self.cache_path.parent.mkdir(parents=True, exist_ok=True)
            with self.cache_path.open("w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
            self._dirty = False
        except Exception:
            pass

    def get(self, lookup_id: str) -> S2Paper | None:
        """Get cached paper by any lookup ID. Returns None on miss/expiry."""
        self._load()
        key = lookup_id.lower()
        entry = self._mem_cache.get(key)
        if not entry:
            return None
        ts, paper_json = entry
        if time.time() - ts > self.ttl_seconds:
            # Expired
            del self._mem_cache[key]
            self._dirty = True
            return None
        try:
            return S2Paper.from_s2_json(paper_json)
        except Exception:
            return None

    def get_many(self, lookup_ids: list[str]) -> dict[str, S2Paper]:
        """Batch cache lookup. Returns {lookup_id: S2Paper} for hits."""
        self._load()
        now = time.time()
        out: dict[str, S2Paper] = {}
        expired_keys: list[str] = []
        for lid in lookup_ids:
            key = lid.lower()
            entry = self._mem_cache.get(key)
            if not entry:
                continue
            ts, paper_json = entry
            if now - ts > self.ttl_seconds:
                expired_keys.append(key)
                continue
            try:
                out[lid] = S2Paper.from_s2_json(paper_json)
            except Exception:
                continue
        # Clean expired
        for k in expired_keys:
            self._mem_cache.pop(k, None)
            self._dirty = True
        if expired_keys:
            self._save()
        return out

    def put(self, paper: S2Paper) -> None:
        """Cache a paper under all its known IDs (cross-ID dedup)."""
        self._load()
        ts = time.time()
        paper_json = paper.to_cache_dict()

        # Collect all lookup keys for this paper
        keys: set[str] = set()
        # S2 paperId
        if paper.paper_id:
            keys.add(paper.paper_id.lower())
        # CorpusId
        if paper.corpus_id:
            keys.add(str(paper.corpus_id).lower())
        # External IDs
        for k, v in (paper.external_ids or {}).items():
            if not v:
                continue
            v_str = str(v).lower()
            keys.add(v_str)
            # Also index with prefix (DOI:..., ArXiv:..., etc.)
            ku = k.upper()
            if ku == "DOI":
                keys.add(f"doi:{v_str}")
            elif ku == "ARXIV":
                keys.add(f"arxiv:{v_str}")
                # ArXiv version-stripped
                import re
                base = re.sub(r"v\d+$", "", v_str)
                keys.add(base)
                keys.add(f"arxiv:{base}")
            elif ku == "PUBMED":
                keys.add(f"pmid:{v_str}")
            elif ku == "ACL":
                keys.add(f"acl:{v_str}")

        # Write all keys
        for key in keys:
            self._mem_cache[key] = (ts, paper_json)
        self._dirty = True
        self._save()

    def put_many(self, papers: list[S2Paper]) -> None:
        """Batch cache multiple papers."""
        for p in papers:
            self.put(p)

    def stats(self) -> dict[str, int]:
        self._load()
        now = time.time()
        valid = sum(1 for ts, _ in self._mem_cache.values() if now - ts <= self.ttl_seconds)
        return {"entries": len(self._mem_cache), "valid": valid}


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
        *,
        cache: S2Cache | None = None,
        cache_path: str | Path | None = None,
        enable_cache: bool = True,
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

        # Phase 4: disk cache
        if enable_cache:
            self._cache = cache or S2Cache(cache_path=cache_path)
        else:
            self._cache = None

        # Cache stats
        self.cache_hits = 0
        self.cache_misses = 0

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
                # Respect Retry-After header if present (Phase 4)
                if resp.status_code == 429 and attempt < _MAX_RETRIES:
                    retry_after = None
                    try:
                        headers_get = getattr(resp, "headers", {}).get
                        if callable(headers_get):
                            retry_after = headers_get("Retry-After")
                    except Exception:
                        retry_after = None
                    sleep_s = None
                    if retry_after is not None:
                        try:
                            sleep_s = float(retry_after)
                        except (ValueError, TypeError):
                            sleep_s = None

                    if sleep_s is None:
                        # Exponential backoff with jitter
                        backoff = _RETRY_BASE_DELAY * (2**attempt)
                        # Harsher backoff when unauthenticated (shared pool)
                        if not self.api_key:
                            backoff *= 2.0
                        # Full jitter
                        import random
                        jitter = backoff * 0.3 * random.random()
                        sleep_s = max(0.5, backoff + jitter)

                    # Cap max sleep at 60s
                    sleep_s = min(sleep_s, 60.0)
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
                # Network-level errors — retry a couple times with backoff
                if attempt < 2:
                    import random
                    sleep_s = _RETRY_BASE_DELAY * (attempt + 1) * (1 + 0.2 * random.random())
                    await asyncio.sleep(sleep_s)
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
        "publicationVenue,publicationTypes,publicationDate,journal,authors,"
        "tldr"
    )

    @staticmethod
    def _normalize_lookup_id(paper_id: str) -> str:
        """Normalize S2 lookup ID for cache key consistency."""
        pid = paper_id.strip()
        # Strip common prefixes for canonical form, but keep them in cache keys too
        return pid

    def _cache_get(self, paper_id: str) -> S2Paper | None:
        if not self._cache:
            return None
        p = self._cache.get(paper_id)
        if p:
            self.cache_hits += 1
        else:
            self.cache_misses += 1
        return p

    def _cache_put(self, paper: S2Paper) -> None:
        if self._cache:
            self._cache.put(paper)

    async def get_paper(
        self, paper_id: str, fields: str | None = None,
        *,
        use_cache: bool = True,
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
        # Phase 4: cache check
        if use_cache and self._cache:
            cached = self._cache_get(paper_id)
            if cached:
                return cached

        fields = fields or self._DEFAULT_PAPER_FIELDS
        from urllib.parse import quote

        pid_enc = quote(paper_id, safe="")
        url = f"{S2_GRAPH_BASE}/paper/{pid_enc}"
        data = await self._request_with_retry(
            "GET", url, params={"fields": fields}
        )
        paper = S2Paper.from_s2_json(data)
        # Cache result
        self._cache_put(paper)
        return paper

    async def batch_get_papers(
        self, paper_ids: list[str], fields: str | None = None,
        *,
        use_cache: bool = True,
    ) -> list[S2Paper]:
        """Batch lookup multiple papers (up to ~500 per request).

        Phase 4: cache-aware, with cross-ID deduplication via corpusId.

        Returns:
            List of S2Paper objects, with unknown/missing papers filtered out.
            Order follows input paper_ids (minus missing entries).
            Duplicate papers (same corpusId) are deduplicated in the result.
        """
        if not paper_ids:
            return []

        fields = fields or self._DEFAULT_PAPER_FIELDS

        # Phase 4: serve from cache first
        cached_map: dict[str, S2Paper] = {}
        missing_ids: list[str] = []
        missing_indices: list[int] = []
        result_slots: list[S2Paper | None] = [None] * len(paper_ids)

        if use_cache and self._cache:
            cached_map = self._cache.get_many(paper_ids)
            self.cache_hits += len(cached_map)

        # Fill cache hits, collect misses with original index
        for idx, pid in enumerate(paper_ids):
            p = cached_map.get(pid) or cached_map.get(pid.lower())
            if p:
                result_slots[idx] = p
            else:
                missing_ids.append(pid)
                missing_indices.append(idx)

        if use_cache and self._cache:
            self.cache_misses += len(missing_ids)

        # Deduplicate missing_ids while tracking original positions
        seen: dict[str, list[int]] = {}
        dedup_missing: list[str] = []
        dedup_map: dict[str, list[int]] = {}  # query_id -> [original_indices]
        for midx, pid in enumerate(missing_ids):
            pl = pid.lower()
            orig_idx = missing_indices[midx]
            if pl not in dedup_map:
                dedup_map[pl] = []
                dedup_missing.append(pid)
            dedup_map[pl].append(orig_idx)

        missing_ids = dedup_missing

        # Fetch missing from S2 in chunks
        # Map query_id -> fetched paper (preserving S2 batch order)
        fetched_by_query: dict[str, S2Paper] = {}
        chunk_size = 100
        for i in range(0, len(missing_ids), chunk_size):
            batch = missing_ids[i:i + chunk_size]
            if not batch:
                continue
            url = f"{S2_GRAPH_BASE}/paper/batch"
            try:
                data = await self._request_with_retry(
                    "POST",
                    url,
                    params={"fields": fields},
                    json_body={"ids": batch},
                )
            except SemanticScholarAPIError:
                # On batch failure, try individual lookups
                for single_id in batch:
                    try:
                        p = await self.get_paper(single_id, fields=fields, use_cache=True)
                        fetched_by_query[single_id.lower()] = p
                    except Exception:
                        continue
                continue

            # Parse batch response – S2 preserves order, None for misses
            if isinstance(data, list):
                for q_idx, item in enumerate(data):
                    if q_idx >= len(batch):
                        break
                    query_id = batch[q_idx]
                    if item is None:
                        continue
                    try:
                        p = S2Paper.from_s2_json(item)
                        fetched_by_query[query_id.lower()] = p
                        # Cache immediately (cross-ID dedup inside put)
                        self._cache_put(p)
                    except Exception:
                        continue

        # Fill in fetched results into result_slots
        for pid, orig_indices in dedup_map.items():
            p = fetched_by_query.get(pid)
            if p:
                for orig_idx in orig_indices:
                    result_slots[orig_idx] = p

        # Build final list: filter None, deduplicate by corpusId/paper_id
        seen_corpus: set[str] = set()
        result: list[S2Paper] = []
        for p in result_slots:
            if p is None:
                continue
            dedup_key = str(p.corpus_id) if p.corpus_id else p.paper_id
            if dedup_key in seen_corpus:
                continue
            seen_corpus.add(dedup_key)
            result.append(p)

        return result

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
        papers = [S2Paper.from_s2_json(p) for p in results if isinstance(p, dict)]
        # Cache search results
        for p in papers:
            self._cache_put(p)
        return papers

    # ------------------------------------------------------------------
    # Cache utilities
    # ------------------------------------------------------------------

    def cache_stats(self) -> dict[str, Any]:
        """Return cache hit/miss stats."""
        base = self._cache.stats() if self._cache else {"entries": 0, "valid": 0}
        base.update({
            "hits": self.cache_hits,
            "misses": self.cache_misses,
            "hit_rate": (self.cache_hits / max(1, self.cache_hits + self.cache_misses)),
        })
        return base
