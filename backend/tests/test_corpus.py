from app.rag.corpus import corpus_version, load_documents


def test_manifest_loads_six_documents(settings):
    docs = load_documents(settings.corpus_dir)
    assert len(docs) == 6
    assert {d.category for d in docs} >= {"Vendor SLA Contract", "Finance Policy", "Cloud Infrastructure SOP"}


def test_chunks_have_metadata_and_unique_ids(chunks):
    assert 25 <= len(chunks) <= 80
    assert len({c.chunk_id for c in chunks}) == len(chunks)
    for c in chunks:
        assert c.doc_title in c.text
        assert c.text.strip()
        assert len(c.text.split()) <= 200


def test_credit_tiers_live_in_a_single_chunk(chunks):
    tier = [c for c in chunks if "25% of the monthly fee" in c.text]
    assert len(tier) == 1
    assert tier[0].doc_id == "vendor_sla_northwind_cloud"


def test_corpus_version_is_stable(settings):
    assert corpus_version(settings.corpus_dir) == corpus_version(settings.corpus_dir)
