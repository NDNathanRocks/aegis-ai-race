"""Prompt-injection guardrail: detect and strip instruction-override sentences.

This is one layer, not a proof. A pattern filter cannot catch every paraphrase, so the system also relies on: user text
being passed as data under an untrusted-input instruction, no tools or secrets in the model's context, output that must
validate against a strict Pydantic schema, and the hallucination critic. Detection runs on a normalised copy (NFKC,
zero-width characters stripped, common leetspeak folded, whitespace collapsed) and on a letters-only copy, so trivial
obfuscation ("Ign0re", zero-width splits, "Ignoreallpreviousinstructions") does not slip through.
"""
import re
import unicodedata

INJECTION_PATTERNS: dict[str, re.Pattern[str]] = {
    "override_instructions": re.compile(
        r"\b(ignore|disregard|forget|override|bypass)\b[^.!?]{0,40}\b(instructions?|rules?|prompts?|guidelines?|"
        r"directions?|commands?|constraints?|above|told|said)\b",
        re.I,
    ),
    "new_instructions": re.compile(
        r"\b(new|updated|revised|real|actual|additional)\s+(instructions?|rules?|directions?|system prompt)\b", re.I
    ),
    "role_hijack": re.compile(r"\b(you are now|act as|pretend (to be|you are)|from now on you)\b", re.I),
    "prompt_exfiltration": re.compile(
        r"\b(print|reveal|show|repeat|output|leak)\b[^.!?]{0,30}\b(system prompt|hidden prompt|hidden rules|instructions|"
        r"rules|configuration|api key|secrets?|credentials?)\b",
        re.I,
    ),
    "forced_output": re.compile(r"\b(reply|respond|answer|say)\s+(only|exclusively)\b", re.I),
    "jailbreak_persona": re.compile(r"\b(jailbreak|DAN mode|developer mode|do anything now)\b", re.I),
    # Fake structure: closing our CONTEXT/QUESTION framing or opening a fake system/assistant turn.
    "delimiter_spoof": re.compile(
        r"</?\s*(context|question|system|assistant|user|instructions?)\s*>|^\s*(system|assistant|developer)\s*:|"
        r"\[/?(inst|system)\]|<\|[a-z_]+\|>",
        re.I | re.M,
    ),
}
# Letters-only form, for "Ignoreallpreviousinstructions" and "i g n o r e ..." style obfuscation.
_SQUASHED = re.compile(
    r"(ignore|disregard|forget|override|bypass)[a-z]{0,12}(previous|prior|above|earlier|all|your|the|any)[a-z]{0,12}"
    r"(instructions?|rules?|prompts?|directions?|guidelines?)|(reveal|print|show|leak|output)(your|the)?"
    r"(systemprompt|hiddenprompt|hiddenrules|apikey)"
)
_LEET = str.maketrans({"0": "o", "1": "i", "3": "e", "4": "a", "5": "s", "7": "t", "@": "a", "$": "s", "!": "i"})
_SENTENCE = re.compile(r"(?<=[.!?])\s+|\n+")


def _variants(sentence: str) -> tuple[str, str]:
    """(normalised, letters-only) copies of a sentence, used for detection only."""
    text = unicodedata.normalize("NFKC", sentence)
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Cf")  # zero-width / bidi controls
    norm = re.sub(r"\s+", " ", text.translate(_LEET)).strip()
    return norm, re.sub(r"[^a-z]", "", norm.lower())


def scan(query: str) -> tuple[list[str], str]:
    """Return (matched pattern names, sanitized query with offending sentences removed)."""
    matched: list[str] = []
    kept: list[str] = []
    for sentence in _SENTENCE.split(query.strip()):
        norm, squashed = _variants(sentence)
        hits = [name for name, rx in INJECTION_PATTERNS.items() if rx.search(sentence) or rx.search(norm)]
        if not hits and _SQUASHED.search(squashed):
            hits = ["obfuscated_override"]
        if hits:
            matched.extend(h for h in hits if h not in matched)
        elif sentence.strip():
            kept.append(sentence.strip())
    sanitized = " ".join(kept)
    # Drop discourse fillers left dangling at the front ("Anyway, ...").
    sanitized = re.sub(r"^(anyway|also|but|and|so|now|then)[,:]?\s+", "", sanitized, flags=re.I)
    return matched, sanitized
