import json

import pytest

from app.domains import DOMAIN_ORDER
from app.rag.corpus import corpus_version, domain_dirs, load_chunks, load_documents

FOOTER = "Demo knowledge base; not legal, tax or medical advice."


def _dir(settings, d):
    return settings.corpus_dir / d


def test_four_domain_directories(settings):
    assert [p.name for p in domain_dirs(settings.corpus_dir)] == sorted(DOMAIN_ORDER)


@pytest.mark.parametrize("domain", DOMAIN_ORDER)
def test_manifest_matches_files_and_has_source_notes(settings, domain):
    d = _dir(settings, domain)
    manifest = json.loads((d / "manifest.json").read_text(encoding="utf-8"))
    ids = {e["id"] for e in manifest["documents"]}
    assert ids == {p.stem for p in d.glob("*.md")}
    assert all(e.get("source_note") for e in manifest["documents"])
    for doc in load_documents(d):
        assert FOOTER in doc.text, doc.id


@pytest.mark.parametrize("domain", DOMAIN_ORDER)
def test_chunks_have_metadata_and_unique_ids(settings, domain):
    chunks = load_chunks(_dir(settings, domain))
    assert 8 <= len(chunks) <= 80
    assert len({c.chunk_id for c in chunks}) == len(chunks)
    atomic = {d.id for d in load_documents(_dir(settings, domain)) if d.atomic}
    for c in chunks:
        assert c.doc_title in c.text and c.text.strip()
        if c.doc_id not in atomic:
            assert len(c.text.split()) <= 240


def test_b2b_has_legacy_distractor_and_nine_docs(settings):
    docs = {d.id: d for d in load_documents(_dir(settings, "b2b_sla"))}
    assert "northwind_legacy_2023_sla" in docs and "SUPERSEDED" in docs["northwind_legacy_2023_sla"].text
    assert len(docs) == 9


def test_credit_tiers_live_in_a_single_chunk(settings):
    tier = [c for c in load_chunks(_dir(settings, "b2b_sla")) if "25% of the monthly fee" in c.text]
    assert len(tier) == 1 and tier[0].doc_id == "vendor_sla_northwind_cloud"


def test_bc_superseded_cap_only_in_labelled_bulletin(settings):
    d = _dir(settings, "bc_tenancy_cra")
    for doc in load_documents(d):
        if "3.0%" in doc.text:
            assert doc.id in ("rtb_bulletin_2025_superseded",), doc.id
    assert "2.3%" in (d / "rent_increase_rules_bc.md").read_text(encoding="utf-8")


def test_root_resolves_to_default_domain(settings):
    assert [d.id for d in load_documents(settings.corpus_dir)] == [d.id for d in load_documents(_dir(settings, "b2b_sla"))]


def test_corpus_version_is_stable_and_per_domain(settings):
    assert corpus_version(settings.corpus_dir) == corpus_version(settings.corpus_dir)
    assert corpus_version(_dir(settings, "nutrition")) != corpus_version(_dir(settings, "b2b_sla"))
