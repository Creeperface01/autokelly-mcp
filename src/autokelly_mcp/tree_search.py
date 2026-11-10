"""Diacritics-insensitive fuzzy search over a parsed group tree."""

from __future__ import annotations

import difflib
import unicodedata

from autokelly_mcp.models import TreeNode

_FUZZY_THRESHOLD = 0.75
_FUZZY_MIN_WORD_LEN = 4


def normalize(s: str) -> str:
    """Lowercase ``s`` without diacritics and with collapsed whitespace."""
    decomposed = unicodedata.normalize("NFKD", s)
    without_marks = "".join(char for char in decomposed if not unicodedata.combining(char))
    return " ".join(without_marks.casefold().split())


def _words(normalised: str) -> list[str]:
    """Split normalised text into words on whitespace and ``/``."""
    return [word for word in normalised.replace("/", " ").split() if word]


def _fuzzy_match(query_word: str, words: list[str]) -> bool:
    """Return True when ``query_word`` is close to any word in ``words``."""
    if len(query_word) < _FUZZY_MIN_WORD_LEN:
        return False
    return any(
        difflib.SequenceMatcher(None, query_word, word).ratio() >= _FUZZY_THRESHOLD
        for word in words
    )


def search_tree(roots: list[TreeNode], query: str, limit: int = 15) -> list[dict]:
    """Search the group tree for ``query``.

    A node matches only when every query word is a substring of the
    normalised node text or path, or fuzzily matches a word there.
    Results are ranked leaf-first, then by score, then by path length,
    keeping tree order as the final tie-break.
    """
    query_words = _words(normalize(query))
    if not query_words:
        return []

    ranked: list[tuple[int, float, int, int, TreeNode, list[str]]] = []
    order = 0

    def visit(node: TreeNode, path: list[str]) -> None:
        nonlocal order
        texts = [*path, node.text]
        norms = [normalize(text) for text in texts]
        own_text = norms[-1]
        own_words = _words(own_text)
        path_text = " ".join(norms)
        path_words = _words(path_text)

        score = 0.0
        for query_word in query_words:
            if query_word in own_text:
                score += 1.0
            elif query_word in path_text:
                continue
            elif _fuzzy_match(query_word, own_words) or _fuzzy_match(query_word, path_words):
                score += 0.5
            else:
                break
        else:
            leaf = not node.children
            ranked.append((0 if leaf else 1, -score, len(texts), order, node, texts))
        order += 1
        for child in node.children:
            visit(child, texts)

    for root in roots:
        visit(root, [])

    ranked.sort(key=lambda item: (item[0], item[1], item[2], item[3]))
    return [
        {
            "id": node.id,
            "text": node.text,
            "path": texts,
            "openable": bool(node.token),
            "leaf": not node.children,
        }
        for _, _, _, _, node, texts in ranked[:limit]
    ]
