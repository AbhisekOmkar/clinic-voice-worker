"""Per-turn language tagging (for metrics + reply-language policy hints).

Script-based detection: Devanagari codepoints mark Hindi; a mix marks a
code-switched turn; otherwise English. Romanised Hindi lands in 'en' here —
the tag drives metrics bucketing and TTS hints, never understanding (the
multilingual STT/LLM handle meaning directly).
"""

DEVANAGARI = (0x0900, 0x097F)


def tag_language(text: str) -> str:
    if not text:
        return "en"
    devanagari = sum(1 for ch in text if DEVANAGARI[0] <= ord(ch) <= DEVANAGARI[1])
    letters = sum(1 for ch in text if ch.isalpha())
    if letters == 0:
        return "en"
    ratio = devanagari / letters
    if ratio > 0.7:
        return "hi"
    if ratio > 0.1:
        return "mixed"
    return "en"
