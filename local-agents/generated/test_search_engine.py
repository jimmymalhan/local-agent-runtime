"""TDD tests for an in-memory SearchEngine."""

import unittest
from collections import defaultdict


class SearchEngine:
    """In-memory search engine supporting index, search (with AND/OR), and delete."""

    def __init__(self):
        self._index: dict[str, set[str]] = defaultdict(set)
        self._docs: dict[str, set[str]] = {}

    def index(self, doc_id: str, text: str) -> None:
        if doc_id in self._docs:
            self.delete(doc_id)
        tokens = self._tokenize(text)
        self._docs[doc_id] = tokens
        for token in tokens:
            self._index[token].add(doc_id)

    def search(self, query: str) -> list[str]:
        query = query.strip()
        if not query:
            return []

        tokens = query.split()
        if "OR" in tokens:
            return self._search_or(tokens)
        if "AND" in tokens:
            return self._search_and(tokens)
        return self._search_and_implicit(tokens)

    def delete(self, doc_id: str) -> None:
        if doc_id not in self._docs:
            return
        for token in self._docs[doc_id]:
            self._index[token].discard(doc_id)
            if not self._index[token]:
                del self._index[token]
        del self._docs[doc_id]

    def _tokenize(self, text: str) -> set[str]:
        return set(text.lower().split())

    def _search_and(self, tokens: list[str]) -> list[str]:
        terms = [t.lower() for t in tokens if t != "AND"]
        if not terms:
            return []
        result = self._index.get(terms[0], set()).copy()
        for term in terms[1:]:
            result &= self._index.get(term, set())
        return sorted(result)

    def _search_or(self, tokens: list[str]) -> list[str]:
        terms = [t.lower() for t in tokens if t != "OR"]
        result: set[str] = set()
        for term in terms:
            result |= self._index.get(term, set())
        return sorted(result)

    def _search_and_implicit(self, tokens: list[str]) -> list[str]:
        terms = [t.lower() for t in tokens]
        if not terms:
            return []
        result = self._index.get(terms[0], set()).copy()
        for term in terms[1:]:
            result &= self._index.get(term, set())
        return sorted(result)


class TestSearchEngineIndex(unittest.TestCase):
    def setUp(self):
        self.engine = SearchEngine()

    def test_index_single_document(self):
        self.engine.index("doc1", "hello world")
        results = self.engine.search("hello")
        self.assertEqual(results, ["doc1"])

    def test_index_multiple_documents(self):
        self.engine.index("doc1", "hello world")
        self.engine.index("doc2", "hello python")
        results = self.engine.search("hello")
        self.assertEqual(results, ["doc1", "doc2"])

    def test_index_overwrites_existing_doc(self):
        self.engine.index("doc1", "hello world")
        self.engine.index("doc1", "goodbye world")
        self.assertNotIn("doc1", self.engine.search("hello"))
        self.assertIn("doc1", self.engine.search("goodbye"))

    def test_index_empty_text(self):
        self.engine.index("doc1", "")
        results = self.engine.search("")
        self.assertEqual(results, [])


class TestSearchEngineSearch(unittest.TestCase):
    def setUp(self):
        self.engine = SearchEngine()
        self.engine.index("doc1", "the quick brown fox")
        self.engine.index("doc2", "the lazy brown dog")
        self.engine.index("doc3", "quick fox jumps high")

    def test_search_single_term(self):
        self.assertEqual(self.engine.search("quick"), ["doc1", "doc3"])

    def test_search_case_insensitive(self):
        self.assertEqual(self.engine.search("QUICK"), ["doc1", "doc3"])
        self.assertEqual(self.engine.search("Quick"), ["doc1", "doc3"])
        self.assertEqual(self.engine.search("Brown"), ["doc1", "doc2"])

    def test_search_no_results(self):
        self.assertEqual(self.engine.search("elephant"), [])

    def test_search_empty_query(self):
        self.assertEqual(self.engine.search(""), [])
        self.assertEqual(self.engine.search("   "), [])

    def test_search_returns_sorted(self):
        results = self.engine.search("the")
        self.assertEqual(results, sorted(results))


class TestSearchEngineAND(unittest.TestCase):
    def setUp(self):
        self.engine = SearchEngine()
        self.engine.index("doc1", "the quick brown fox")
        self.engine.index("doc2", "the lazy brown dog")
        self.engine.index("doc3", "quick fox jumps high")

    def test_and_explicit(self):
        results = self.engine.search("quick AND brown")
        self.assertEqual(results, ["doc1"])

    def test_and_no_overlap(self):
        results = self.engine.search("fox AND dog")
        self.assertEqual(results, [])

    def test_and_all_match(self):
        results = self.engine.search("the AND brown")
        self.assertEqual(results, ["doc1", "doc2"])

    def test_and_case_insensitive(self):
        results = self.engine.search("QUICK AND BROWN")
        self.assertEqual(results, ["doc1"])

    def test_and_single_term_with_keyword(self):
        results = self.engine.search("fox AND fox")
        self.assertEqual(results, ["doc1", "doc3"])

    def test_and_multiple_terms(self):
        results = self.engine.search("the AND quick AND brown")
        self.assertEqual(results, ["doc1"])

    def test_implicit_and_multi_word(self):
        results = self.engine.search("quick brown")
        self.assertEqual(results, ["doc1"])


class TestSearchEngineOR(unittest.TestCase):
    def setUp(self):
        self.engine = SearchEngine()
        self.engine.index("doc1", "the quick brown fox")
        self.engine.index("doc2", "the lazy brown dog")
        self.engine.index("doc3", "quick fox jumps high")

    def test_or_union(self):
        results = self.engine.search("fox OR dog")
        self.assertEqual(results, ["doc1", "doc2", "doc3"])

    def test_or_one_term_missing(self):
        results = self.engine.search("fox OR elephant")
        self.assertEqual(results, ["doc1", "doc3"])

    def test_or_both_missing(self):
        results = self.engine.search("elephant OR giraffe")
        self.assertEqual(results, [])

    def test_or_case_insensitive(self):
        results = self.engine.search("FOX OR DOG")
        self.assertEqual(results, ["doc1", "doc2", "doc3"])

    def test_or_multiple_terms(self):
        results = self.engine.search("dog OR jumps OR lazy")
        self.assertEqual(results, ["doc2", "doc3"])

    def test_or_deduplicated(self):
        results = self.engine.search("the OR brown")
        self.assertEqual(len(results), len(set(results)))


class TestSearchEngineDelete(unittest.TestCase):
    def setUp(self):
        self.engine = SearchEngine()
        self.engine.index("doc1", "hello world")
        self.engine.index("doc2", "hello python")

    def test_delete_removes_from_results(self):
        self.engine.delete("doc1")
        self.assertEqual(self.engine.search("hello"), ["doc2"])

    def test_delete_all_docs_for_term(self):
        self.engine.delete("doc1")
        self.assertEqual(self.engine.search("world"), [])

    def test_delete_nonexistent_doc(self):
        self.engine.delete("doc999")
        self.assertEqual(self.engine.search("hello"), ["doc1", "doc2"])

    def test_delete_then_reindex(self):
        self.engine.delete("doc1")
        self.engine.index("doc1", "new content")
        self.assertEqual(self.engine.search("new"), ["doc1"])
        self.assertEqual(self.engine.search("hello"), ["doc2"])

    def test_delete_cleans_index_fully(self):
        self.engine.delete("doc1")
        self.engine.delete("doc2")
        self.assertEqual(self.engine.search("hello"), [])
        self.assertEqual(self.engine._index, {})


class TestSearchEngineEdgeCases(unittest.TestCase):
    def setUp(self):
        self.engine = SearchEngine()

    def test_search_on_empty_engine(self):
        self.assertEqual(self.engine.search("anything"), [])

    def test_duplicate_words_in_document(self):
        self.engine.index("doc1", "hello hello hello")
        self.assertEqual(self.engine.search("hello"), ["doc1"])

    def test_large_document(self):
        text = " ".join(f"word{i}" for i in range(1000))
        self.engine.index("big", text)
        self.assertEqual(self.engine.search("word500"), ["big"])

    def test_many_documents(self):
        for i in range(100):
            self.engine.index(f"doc{i}", f"common term{i}")
        results = self.engine.search("common")
        self.assertEqual(len(results), 100)

    def test_index_case_insensitive_storage(self):
        self.engine.index("doc1", "Hello WORLD")
        self.assertEqual(self.engine.search("hello"), ["doc1"])
        self.assertEqual(self.engine.search("world"), ["doc1"])

    def test_and_or_as_regular_words(self):
        self.engine.index("doc1", "this and that")
        results = self.engine.search("this")
        self.assertEqual(results, ["doc1"])

    def test_delete_and_search_and_or(self):
        self.engine.index("doc1", "apple banana")
        self.engine.index("doc2", "banana cherry")
        self.engine.index("doc3", "cherry apple")
        self.engine.delete("doc2")
        self.assertEqual(self.engine.search("banana OR cherry"), ["doc1", "doc3"])
        self.assertEqual(self.engine.search("apple AND cherry"), ["doc3"])


if __name__ == "__main__":
    # Run assertions manually for quick verification
    engine = SearchEngine()

    # Basic indexing and search
    engine.index("doc1", "the quick brown fox")
    engine.index("doc2", "the lazy brown dog")
    engine.index("doc3", "quick fox jumps high")
    assert engine.search("quick") == ["doc1", "doc3"]
    assert engine.search("QUICK") == ["doc1", "doc3"]
    assert engine.search("elephant") == []

    # AND
    assert engine.search("quick AND brown") == ["doc1"]
    assert engine.search("fox AND dog") == []
    assert engine.search("the AND brown") == ["doc1", "doc2"]

    # OR
    assert engine.search("fox OR dog") == ["doc1", "doc2", "doc3"]
    assert engine.search("elephant OR giraffe") == []

    # Implicit AND (multi-word)
    assert engine.search("quick brown") == ["doc1"]

    # Delete
    engine.delete("doc1")
    assert engine.search("quick") == ["doc3"]
    assert engine.search("world") == []
    engine.delete("doc999")  # no-op

    # Reindex after delete
    engine.index("doc1", "new content here")
    assert engine.search("new") == ["doc1"]
    assert engine.search("brown") == ["doc2"]

    print("All assertions passed.")

    # Also run unittest suite
    unittest.main(verbosity=2)
