"""Verify the actual published text before completing a response stream."""
from __future__ import annotations


class AnswerStreamMismatchError(RuntimeError):
    def __init__(self, published: str, final: str):
        mismatch = next((i for i, (a, b) in enumerate(zip(published, final)) if a != b),
                        min(len(published), len(final)))
        self.published_chars = len(published)
        self.final_chars = len(final)
        self.mismatch_offset = mismatch
        super().__init__(
            "Der finale Antworttext stimmt nicht mit dem veröffentlichten Stream überein "
            f"(veröffentlicht: {len(published)} Zeichen, final: {len(final)} Zeichen, "
            f"erste Abweichung: Position {mismatch})"
        )


def unpublished_suffix(chunks: list[str], final: str) -> str:
    """Only extend an identical prefix; never repair by length or overwrite it."""
    published = "".join(chunks)
    if not final.startswith(published):
        raise AnswerStreamMismatchError(published, final)
    return final[len(published):]
