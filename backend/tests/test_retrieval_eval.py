"""Retrieval ablation (app/eval/retrieval.py): label integrity, metric maths, and regression floors on the real model."""
import pytest

from app.domains import DOMAIN_ORDER
from app.eval import retrieval as ev
from app.rag.corpus import load_chunks


@pytest.fixture(scope="module")
def questions():
    return ev.load_questions()


def test_every_label_points_at_a_real_chunk(settings, questions):
    chunks = {d: load_chunks(settings.corpus_dir / d) for d in DOMAIN_ORDER}
    assert not ev.unlabeled(questions, chunks)
    assert {q.domain for q in questions} == set(DOMAIN_ORDER)
    assert {q.style for q in questions} == {"lexical", "paraphrase"}


def test_eval_questions_are_not_preset_prompts(questions):
    from app import domains as dom

    presets = {p.query for d in dom.list_domains() for p in d.presets} | {
        p.paraphrase for d in dom.list_domains() for p in d.presets if p.paraphrase
    }
    assert not presets & {q.query for q in questions}  # the warm caches must not flatter the eval


def test_summarize_and_bootstrap():
    s = ev.summarize([1, 3, None, 2])
    assert s == {"hit@1": 0.25, "hit@2": 0.5, "hit@4": 0.75, "mrr": (1 + 1 / 3 + 1 / 2) / 4}
    mean, lo, hi = ev.paired_bootstrap_ci([1.0, 1.0, 0.5], [0.5, 1.0, 0.5])
    assert mean == pytest.approx(1 / 6) and lo <= mean <= hi
    assert ev.paired_bootstrap_ci([1.0] * 5, [1.0] * 5) == (0.0, 0.0, 0.0)


@pytest.mark.model
def test_retrieval_quality_floors(settings, questions):
    """Floors sit just under the measured values (docs/retrieval-eval.md) so a retrieval regression fails CI."""
    from app.domains import build_domains
    from tests.conftest import REAL_EMBEDDER

    runtimes = build_domains(settings, REAL_EMBEDDER, warm=False)
    ranks = ev.run(runtimes, questions)
    shipped = ev.summarize(ranks[ev.CONFIGS[-1][0]])
    assert shipped["hit@4"] >= 0.90, shipped
    assert shipped["mrr"] >= 0.78, shipped
    for label, *_ in ev.CONFIGS[:2]:  # fusing the lenses must not rank worse than either lens alone
        assert shipped["mrr"] >= ev.summarize(ranks[label])["mrr"] - 0.01, (label, shipped)
