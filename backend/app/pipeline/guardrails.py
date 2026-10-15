"""Prompt-injection guardrail: detect and strip instruction-override sentences."""
import re

INJECTION_PATTERNS: dict[str, re.Pattern[str]] = {
    "override_instructions": re.compile(
        r"\b(ignore|disregard|forget|override)\b[^.!?]{0,40}\b(instructions?|rules?|prompts?|guidelines?)\b", re.I
    ),
    "role_hijack": re.compile(r"\b(you are now|act as|pretend (to be|you are)|from now on you)\b", re.I),
    "prompt_exfiltration": re.compile(
        r"\b(print|reveal|show|repeat|output|leak)\b[^.!?]{0,30}\b(system prompt|hidden prompt|instructions|api key|secrets?)\b",
        re.I,
    ),
    "forced_output": re.compile(r"\b(reply|respond|answer|say)\s+(only|exclusively)\b", re.I),
    "jailbreak_persona": re.compile(r"\b(jailbreak|DAN mode|developer mode|do anything now)\b", re.I),
}
_SENTENCE = re.compile(r"(?<=[.!?])\s+|\n+")


def scan(query: str) -> tuple[list[str], str]:
    """Return (matched pattern names, sanitized query with offending sentences removed)."""
    matched: list[str] = []
    kept: list[str] = []
    for sentence in _SENTENCE.split(query.strip()):
        hits = [name for name, rx in INJECTION_PATTERNS.items() if rx.search(sentence)]
        if hits:
            matched.extend(h for h in hits if h not in matched)
        elif sentence.strip():
            kept.append(sentence.strip())
    sanitized = " ".join(kept)
    # Drop discourse fillers left dangling at the front ("Anyway, ...").
    sanitized = re.sub(r"^(anyway|also|but|and|so|now|then)[,:]?\s+", "", sanitized, flags=re.I)
    return matched, sanitized
