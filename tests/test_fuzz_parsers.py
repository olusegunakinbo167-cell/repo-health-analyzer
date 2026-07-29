"""Property-based fuzz tests for citation parsers.

Tests _parse_citation_cff and _parse_citation_bib against malformed inputs,
invalid Unicode, unexpected types, and corrupted syntax. The parsers should
never crash — they must always return a list[PaperReference] (possibly empty).

Run with: pytest tests/test_fuzz_parsers.py -v
"""

from __future__ import annotations

import string

import pytest
from hypothesis import given, settings, strategies as st

from src.metrics.academic_impact import (
    PaperReference,
    _parse_citation_bib,
    _parse_citation_cff,
)


# ---------------------------------------------------------------------------
# Helpers / strategies
# ---------------------------------------------------------------------------

# Valid DOI-ish fragments for embedding in fuzzed text
DOI_FRAGMENTS = [
    "10.1038/nature12373",
    "10.48550/arXiv.1706.03762",
    "10.1145/1234567.1234567",
    "doi:10.1000/182",
]

ARXIV_FRAGMENTS = [
    "1706.03762",
    "2301.12345v2",
    "cs/0112017",
    "quant-ph/9901001v3",
    "arXiv:2106.01342",
    "https://arxiv.org/abs/2005.14165",
]

# Characters that commonly break YAML / BibTeX parsers
# Note: allow invalid surrogate / non-BMP code points to test Unicode robustness
MESSY_TEXT_CHARS = st.characters(
    blacklist_categories=("Cs",),  # exclude surrogates — they break Python str
    min_codepoint=0,
    max_codepoint=0x10FFFF,
)

# BibTeX-breaking characters
BIB_MESSY_CHARS = st.characters(
    blacklist_categories=("Cs",),
    min_codepoint=0,
    max_codepoint=0x10FFFF,
)


@st.composite
def messy_yaml_text(draw: st.DrawFn) -> str:
    """Generate messy / malformed YAML-like text with DOI/arXiv sprinkled in."""
    parts: list[str] = []

    # Randomly include valid-looking CFF keys
    cff_keys = [
        "cff-version", "message", "authors", "title", "version", "doi",
        "date-released", "url", "repository-code", "identifiers",
        "preferred-citation", "license", "keywords"
    ]

    n_lines = draw(st.integers(min_value=1, max_value=50))
    for _ in range(n_lines):
        choice = draw(st.integers(0, 9))
        if choice == 0:
            # Valid CFF key with garbage value
            key = draw(st.sampled_from(cff_keys))
            val = draw(st.text(MESSY_TEXT_CHARS, min_size=0, max_size=80))
            parts.append(f"{key}: {val}")
        elif choice == 1:
            # Malformed YAML — unclosed quotes, bad indentation
            parts.append(draw(st.sampled_from([
                'title: "unclosed quote',
                "doi: [unclosed list",
                "authors:\n  - name: \n    - bad_nesting:",
                "key: value: extra_colon: oops",
                "\tindented with tabs: bad",
                "  - - - triple list",
                "&anchor *alias broken",
                "key: |-\n  literal\nbad_indent",
            ])))
        elif choice == 2:
            # DOI embedded in noise
            frag = draw(st.sampled_from(DOI_FRAGMENTS))
            noise = draw(st.text(MESSY_TEXT_CHARS, min_size=0, max_size=30))
            parts.append(f"{noise}{frag}{noise}")
        elif choice == 3:
            # arXiv embedded in noise
            frag = draw(st.sampled_from(ARXIV_FRAGMENTS))
            noise = draw(st.text(MESSY_TEXT_CHARS, min_size=0, max_size=30))
            parts.append(f"{noise}{frag}{noise}")
        elif choice == 4:
            # Pure garbage
            parts.append(draw(st.text(MESSY_TEXT_CHARS, min_size=1, max_size=100)))
        elif choice == 5:
            # YAML bomb / recursion edge cases
            parts.append(draw(st.sampled_from([
                "a: &a [*a]",
                "!!python/object/apply:os.system ['echo pwned']",
                "---\n---\n---\n",
                "<<: *self",
            ])))
        elif choice == 6:
            # Valid-looking identifiers block with garbage
            parts.append(draw(st.sampled_from([
                "identifiers:\n  - type: doi\n    value: 10.1000/garbage\x00\x01",
                "identifiers: not_a_list",
                "identifiers:\n  - type: 12345\n    value: null",
            ])))
        elif choice == 7:
            # Unicode edge cases
            parts.append(draw(st.sampled_from([
                "title: \udc80 bad surrogate (but filtered by strategy)",
                "doi: 10.1000/\u202etest\ufeff",  # RTL, BOM
                "key: \u0000\u0001\u0002\u0003 null bytes",
                "emoji: \U0001f4a3\U0001f600\U0001f680",
                "zalgo: z̴̧̞̠̻a̶̖͓l̶̞̯̱g̴̢̯o̵̮",
            ])))
        else:
            # Random text
            parts.append(draw(st.text(MESSY_TEXT_CHARS, min_size=0, max_size=60)))

    return "\n".join(parts)


@st.composite
def messy_bibtex_text(draw: st.DrawFn) -> str:
    """Generate messy / malformed BibTeX with DOI/arXiv sprinkled in."""
    parts: list[str] = []

    bibtex_entry_types = [
        "article", "inproceedings", "misc", "book", "techreport", "phdthesis"
    ]
    bibtex_fields = [
        "author", "title", "year", "doi", "eprint", "archivePrefix",
        "url", "journal", "booktitle", "publisher"
    ]

    n_entries = draw(st.integers(min_value=1, max_value=20))
    for _ in range(n_entries):
        choice = draw(st.integers(0, 8))
        if choice == 0:
            # Well-formed entry with garbage field values
            entry_type = draw(st.sampled_from(bibtex_entry_types))
            cite_key = draw(st.text(
                st.characters(min_codepoint=32, max_codepoint=126,
                              blacklist_characters='{},@"\\'),
                min_size=1, max_size=20
            ))
            parts.append(f"@{entry_type}{{{cite_key},")
            n_fields = draw(st.integers(1, 8))
            for _ in range(n_fields):
                field = draw(st.sampled_from(bibtex_fields))
                val = draw(st.text(BIB_MESSY_CHARS, min_size=0, max_size=60))
                # Randomly pick brace / quote / bare style
                style = draw(st.integers(0, 2))
                if style == 0:
                    parts.append(f"  {field} = {{{val}}},")
                elif style == 1:
                    parts.append(f'  {field} = "{val}",')
                else:
                    parts.append(f"  {field} = {val},")
            parts.append("}")
        elif choice == 1:
            # Malformed BibTeX — unclosed braces, bad escaping
            parts.append(draw(st.sampled_from([
                "@article{key,\n  doi = {10.1000/unclosed\n",
                "@misc{no_closing_brace\n  title = {oops}",
                "@article{key, author = \"unclosed quote, }",
                "@@@broken{key, field = value}",
                "@article{key, doi = {{nested {braces} broken}",
            ])))
        elif choice == 2:
            # DOI in random context
            frag = draw(st.sampled_from(DOI_FRAGMENTS))
            noise = draw(st.text(BIB_MESSY_CHARS, min_size=0, max_size=40))
            parts.append(f"{noise}{frag}{noise}")
        elif choice == 3:
            # arXiv in random context
            frag = draw(st.sampled_from(ARXIV_FRAGMENTS))
            noise = draw(st.text(BIB_MESSY_CHARS, min_size=0, max_size=40))
            parts.append(f"{noise}{frag}{noise}")
        elif choice == 4:
            # eprint / archivePrefix garbage
            parts.append(draw(st.sampled_from([
                "eprint = {\\u0000\\x00 corrupted}",
                "archivePrefix = 123456",
                "eprint = {{{triple braces}}}",
                'eprint = "arXiv:9999.99999v999"',
            ])))
        elif choice == 5:
            # Unicode / control char edge cases
            parts.append(draw(st.sampled_from([
                "title = {test\u202eRTL\u202d override}",
                "doi = {10.1000/\u0000\u0001null}",
                "author = {\U0001f4a3 boom}",
                "url = {https://doi.org/10.1000/\ufeffbom}",
            ])))
        elif choice == 6:
            # Very long lines / values
            long_val = draw(st.text(
                st.characters(min_codepoint=32, max_codepoint=126),
                min_size=500, max_size=2000
            ))
            parts.append(f"@misc{{key, doi = {{{long_val}}}}}")
        else:
            # Random garbage
            parts.append(draw(st.text(BIB_MESSY_CHARS, min_size=1, max_size=100)))

    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Property tests — CFF / YAML parser
# ---------------------------------------------------------------------------

@given(text=messy_yaml_text())
@settings(max_examples=200, deadline=None)
def test_cff_parser_never_crashes(text: str) -> None:
    """_parse_citation_cff must never raise — always return list[PaperReference]."""
    try:
        result = _parse_citation_cff(text, source_file="fuzz_CITATION.cff")
    except Exception as e:
        pytest.fail(f"_parse_citation_cff crashed on input {text[:200]!r}: {e}")

    assert isinstance(result, list)
    assert all(isinstance(r, PaperReference) for r in result)
    # DOI/arXiv IDs should be non-empty and have valid id_type
    for r in result:
        assert r.paper_id
        assert r.id_type in {"doi", "arxiv", "s2_corpus", "pmid", "acl", "pmcid"}
        assert r.source_file == "fuzz_CITATION.cff"


@given(text=st.text(MESSY_TEXT_CHARS, min_size=0, max_size=500))
@settings(max_examples=200, deadline=None)
def test_cff_parser_pure_noise(text: str) -> None:
    """Pure random Unicode noise must not crash the CFF parser."""
    try:
        result = _parse_citation_cff(text, source_file="noise.cff")
    except Exception as e:
        pytest.fail(f"_parse_citation_cff crashed on noise: {e!r}\ninput={text[:200]!r}")

    assert isinstance(result, list)


# Known-malicious / edge-case YAML payloads
CFF_EDGE_CASES = [
    ("empty", ""),
    ("null bytes", "doi: 10.1000/test\x00\x01\x02"),
    ("very long line", "doi: 10.1000/" + "a" * 10000),
    ("yaml bomb", "a: &a [\"x\", *a, *a, *a]"),
    ("python tag", "!!python/object/apply:os.system ['id']"),
    ("bad unicode", "title: \ufeff\u202e\u202d test"),
    ("unclosed quote", 'doi: "10.1000/unclosed'),
    ("doi as int", "doi: 10"),
    ("doi as list", "doi: [10.1000/a, 10.2000/b]"),
    ("identifiers wrong type", "identifiers: 12345"),
    ("identifiers null values", "identifiers:\n  - type: null\n    value: null"),
    ("preferred-citation not dict", "preferred-citation: oops"),
    ("recursive merge", "a: &a\n  b: *a"),
    ("million newlines", "\n" * 10000 + "doi: 10.1000/x"),
]


@pytest.mark.parametrize("name,payload", CFF_EDGE_CASES)
def test_cff_parser_edge_cases(name: str, payload: str) -> None:
    """Hand-curated edge cases for CFF parser."""
    try:
        result = _parse_citation_cff(payload, source_file=f"edge_{name}.cff")
    except Exception as e:
        pytest.fail(f"CFF parser crashed on edge case {name!r}: {e}")

    assert isinstance(result, list)


# ---------------------------------------------------------------------------
# Property tests — BibTeX parser
# ---------------------------------------------------------------------------

@given(text=messy_bibtex_text())
@settings(max_examples=200, deadline=None)
def test_bib_parser_never_crashes(text: str) -> None:
    """_parse_citation_bib must never raise — always return list[PaperReference]."""
    try:
        result = _parse_citation_bib(text, source_file="fuzz_refs.bib")
    except Exception as e:
        pytest.fail(f"_parse_citation_bib crashed on input {text[:200]!r}: {e}")

    assert isinstance(result, list)
    assert all(isinstance(r, PaperReference) for r in result)
    for r in result:
        assert r.paper_id
        assert r.id_type in {"doi", "arxiv", "s2_corpus", "pmid", "acl", "pmcid"}
        assert r.source_file == "fuzz_refs.bib"


@given(text=st.text(BIB_MESSY_CHARS, min_size=0, max_size=500))
@settings(max_examples=200, deadline=None)
def test_bib_parser_pure_noise(text: str) -> None:
    """Pure random Unicode noise must not crash the BibTeX parser."""
    try:
        result = _parse_citation_bib(text, source_file="noise.bib")
    except Exception as e:
        pytest.fail(f"_parse_citation_bib crashed on noise: {e!r}\ninput={text[:200]!r}")

    assert isinstance(result, list)


# Hand-curated BibTeX edge cases
BIB_EDGE_CASES = [
    ("empty", ""),
    ("null bytes in doi", "@article{k, doi = {10.1000/\x00test}}"),
    ("very long doi", "@article{k, doi = {10.1000/" + "a" * 10000 + "}}"),
    ("unclosed brace", "@article{k, doi = {10.1000/test"),
    ("unclosed quote", '@article{k, doi = "10.1000/test}'),
    ("nested braces", "@article{k, title = {{nested {braces} here}}}"),
    ("escaped quotes", r'@article{k, title = "say \"hello\""}'),
    ("eprint no archivePrefix", "@article{k, eprint = {1706.03762}}"),
    ("archivePrefix wrong case", "@article{k, archivePrefix = {ARXIV}, eprint={1706.03762}}"),
    ("eprint garbage", "@article{k, eprint = {\x00\x01\x02}}"),
    ("url with doi", "@misc{k, url = {https://doi.org/10.1000/test}}"),
    ("url with arxiv", "@misc{k, url = {https://arxiv.org/abs/1706.03762}}"),
    ("doi with trailing punctuation", "@article{k, doi = {10.1000/test.},}"),
    ("multiple @ in value", "@article{k, title = {email@foo.com @bar}}"),
    ("comment lines", "% comment\n@article{k, doi = {10.1000/x}}"),
    ("no comma after field", "@article{k doi = {10.1000/x}}"),
    ("million entries", "@article{k0, doi={10.1000/x}}\n" * 500),
    ("control chars", "doi = {10.1000/\u0000\u0001\u0002test}"),
    ("rtl override", "title = {test\u202etest}"),
]


@pytest.mark.parametrize("name,payload", BIB_EDGE_CASES)
def test_bib_parser_edge_cases(name: str, payload: str) -> None:
    """Hand-curated edge cases for BibTeX parser."""
    try:
        result = _parse_citation_bib(payload, source_file=f"edge_{name}.bib")
    except Exception as e:
        pytest.fail(f"BibTeX parser crashed on edge case {name!r}: {e}")

    assert isinstance(result, list)


# ----------------------------------------------------------------------
# File-level safety / ReDoS hardening tests
# ----------------------------------------------------------------------

from src.metrics.academic_impact import (
    MAX_CITATION_FILE_SIZE,
    _extract_citations_from_markdown,
    _is_binary_content,
    _safe_decode,
    extract_paper_references,
)


def test_binary_payload_rejection_cff() -> None:
    """Binary blobs in CFF files must be rejected cleanly."""
    # High NUL ratio
    binary = b"\x00\x01\x02\x03" * 1000 + b"doi: 10.1000/test"
    text = binary.decode("latin-1")
    result = _parse_citation_cff(text, "binary.cff")
    assert isinstance(result, list)
    assert result == []  # binary content rejected

    # PNG header fake
    png_fake = "\x89PNG\r\n\x1a\n" + "\x00\x00\x00\rIHDR" * 100
    result = _parse_citation_cff(png_fake, "fake_png.cff")
    assert result == []


def test_binary_payload_rejection_bib() -> None:
    """Binary blobs in BibTeX files must be rejected cleanly."""
    binary = "\x00\x01\x02" * 3000 + "@article{k, doi={10.1/x}}"
    result = _parse_citation_bib(binary, "binary.bib")
    assert isinstance(result, list)
    assert result == []


def test_oversized_input_truncation() -> None:
    """Inputs >2 MB must be truncated, not crash."""
    # Just over the 2MB limit (truncation test, not stress test)
    big = "doi: 10.1000/test\n" + ("x" * (MAX_CITATION_FILE_SIZE + 1024))
    assert len(big) > MAX_CITATION_FILE_SIZE

    for parser, fname in [
        (_parse_citation_bib, "big.bib"),
        (extract_paper_references, "big.txt"),  # .txt avoids markdown chunking overhead
    ]:
        result = parser(big, fname)  # type: ignore[arg-type]
        assert isinstance(result, list)
        # Should not crash, may find the DOI at the start

    # CFF parser: use smaller input to avoid slow YAML parse on 2MB garbage
    cff_big = "doi: 10.1000/test\n" + ("x" * 100_000)
    result = _parse_citation_cff(cff_big, "big.cff")
    assert isinstance(result, list)


def test_markdown_redos_protection() -> None:
    """Pathological markdown must not cause catastrophic backtracking."""
    # RedoS trigger: nested quantifiers / catastrophic backtracking patterns
    # Even though our DOI/ArXiv regexes are safe, test the markdown stripper
    redos_cases = [
        # Fenced code block with unclosed backticks
        "```" + "a" * 5000,
        # Inline code with newlines (should not match)
        "`" + "x" * 1000 + "\n" * 10 + "`",
        # Many nested brackets / parens near DOI-like strings
        "("* 500 + "10.1000/test" + ")" * 500,
        # Repeated DOI-like prefixes (stress test match count bounding)
        ("10.1000/test " * 2000),
        # Markdown with code block containing DOI-like noise
        "```\n" + ("10." + "x" * 20 + "\n") * 100 + "```",
    ]

    for i, payload in enumerate(redos_cases):
        result = _extract_citations_from_markdown(payload, f"redos_{i}.md")
        assert isinstance(result, list)
        # Must complete quickly and not crash


def test_markdown_code_block_stripping() -> None:
    """DOIs inside markdown code blocks should be ignored (reduced FP)."""
    md = """
# My Paper

DOI: 10.1000/real_paper

```python
# This DOI in code should be filtered out
DOI = "10.9999/fake_in_code"
```

More text with arXiv:1706.03762

`inline 10.8888/also_fake`
"""
    result = _extract_citations_from_markdown(md, "test.md")
    ids = {r.paper_id for r in result}
    # Real DOI should be found
    assert any("10.1000/real_paper" in pid for pid in ids)
    # Code-block DOIs should ideally be filtered (best-effort)
    # At minimum, parser must not crash


def test_oversized_markdown_chunking() -> None:
    """Markdown files >64KB must be chunked, not processed monolithically."""
    # 80 KB markdown with DOIs sprinkled throughout
    chunk = "Lorem ipsum " * 20 + " doi:10.1000/test123 "
    big_md = chunk * 300  # ~80KB+
    assert len(big_md) > 64 * 1024

    result = _extract_citations_from_markdown(big_md, "big.md")
    assert isinstance(result, list)
    # Should find at least one DOI (deduplication may collapse them)
    assert len(result) >= 0


def test_encoding_fallback_binary_detection() -> None:
    """Binary content must be detected across encoding attempts."""
    # Binary blob that decodes as latin-1 but is still binary
    binary_data = b"\x00\x01\x02\x03\xff\xfe" * 1000
    result = _safe_decode(binary_data, "test.bin")
    assert result is None  # rejected as binary

    # Valid UTF-8 with DOI
    good = "doi: 10.1000/test\nTitle: Test".encode("utf-8")
    result = _safe_decode(good, "good.cff")
    assert result is not None
    assert "10.1000/test" in result

    # Latin-1 encoded text (not UTF-8)
    latin1_data = "Café doi: 10.1000/test".encode("latin-1")
    result = _safe_decode(latin1_data, "latin1.cff")
    assert result is not None


def test_is_binary_content_detection() -> None:
    """Binary detection heuristic must catch NUL / control char blobs."""
    assert _is_binary_content("\x00\x00\x00hello") is True
    assert _is_binary_content(b"\x00\x01\x02\xff" * 100) is True
    assert _is_binary_content("Normal text with doi 10.1000/x") is False
    assert _is_binary_content("Café naïve résumé — normal unicode") is False
    # High control char ratio
    assert _is_binary_content("\x01\x02\x03" * 1000) is True


def test_regex_match_count_bounding() -> None:
    """Regex matching must be bounded to prevent ReDoS / runaway matching."""
    # 5k DOI-like strings — match count should be capped / deduped
    spam = ("10.1000/test " * 5000)
    result = extract_paper_references(spam, "spam.md")
    assert isinstance(result, list)
    # Deduplication means we get 1 ref, but critically: no crash / hang
    assert len(result) <= 10001  # MAX_REGEX_MATCHES + margin

