"""
TDD Regex Engine: RegexMatcher(pattern).match(text) -> Match|None
Supports: . * + ? ^ $ [] () groups
"""

import unittest
from dataclasses import dataclass, field
from typing import Optional


# ─── Result type ───

@dataclass
class Match:
    matched: str
    groups: tuple = field(default_factory=tuple)
    start: int = 0
    end: int = 0

    def group(self, n: int = 0) -> str:
        if n == 0:
            return self.matched
        return self.groups[n - 1]


# ─── AST nodes ───

class Literal:
    def __init__(self, ch: str):
        self.ch = ch

class Dot:
    pass

class Anchor:
    def __init__(self, kind: str):
        self.kind = kind  # '^' or '$'

class CharClass:
    def __init__(self, chars: set, negated: bool = False):
        self.chars = chars
        self.negated = negated

class Group:
    def __init__(self, expr: list, index: int):
        self.expr = expr
        self.index = index

class Quantifier:
    def __init__(self, node, kind: str):
        self.node = node
        self.kind = kind  # '*', '+', '?'


# ─── Parser ───

class Parser:
    def __init__(self, pattern: str):
        self.pattern = pattern
        self.pos = 0
        self.group_count = 0

    def parse(self) -> list:
        return self._parse_seq()

    def _parse_seq(self) -> list:
        nodes = []
        while self.pos < len(self.pattern):
            ch = self.pattern[self.pos]
            if ch == ')':
                break
            node = self._parse_atom()
            if node is not None:
                if self.pos < len(self.pattern) and self.pattern[self.pos] in '*+?':
                    q = self.pattern[self.pos]
                    self.pos += 1
                    node = Quantifier(node, q)
                nodes.append(node)
        return nodes

    def _parse_atom(self):
        ch = self.pattern[self.pos]
        if ch == '^':
            self.pos += 1
            return Anchor('^')
        if ch == '$':
            self.pos += 1
            return Anchor('$')
        if ch == '.':
            self.pos += 1
            return Dot()
        if ch == '[':
            return self._parse_char_class()
        if ch == '(':
            return self._parse_group()
        if ch == '\\':
            self.pos += 1
            if self.pos < len(self.pattern):
                esc = self.pattern[self.pos]
                self.pos += 1
                return Literal(esc)
            return Literal('\\')
        self.pos += 1
        return Literal(ch)

    def _parse_char_class(self):
        self.pos += 1  # skip '['
        negated = False
        if self.pos < len(self.pattern) and self.pattern[self.pos] == '^':
            negated = True
            self.pos += 1
        chars = set()
        while self.pos < len(self.pattern) and self.pattern[self.pos] != ']':
            if (self.pos + 2 < len(self.pattern) and
                    self.pattern[self.pos + 1] == '-' and
                    self.pattern[self.pos + 2] != ']'):
                start_c = self.pattern[self.pos]
                end_c = self.pattern[self.pos + 2]
                for o in range(ord(start_c), ord(end_c) + 1):
                    chars.add(chr(o))
                self.pos += 3
            else:
                chars.add(self.pattern[self.pos])
                self.pos += 1
        if self.pos < len(self.pattern):
            self.pos += 1  # skip ']'
        return CharClass(chars, negated)

    def _parse_group(self):
        self.pos += 1  # skip '('
        self.group_count += 1
        idx = self.group_count
        expr = self._parse_seq()
        if self.pos < len(self.pattern) and self.pattern[self.pos] == ')':
            self.pos += 1
        return Group(expr, idx)


# ─── Engine ───

class RegexMatcher:
    def __init__(self, pattern: str):
        self.pattern = pattern
        parser = Parser(pattern)
        self.ast = parser.parse()
        self.num_groups = parser.group_count

    def match(self, text: str) -> Optional[Match]:
        """Try to match pattern against text. Anchored at start unless pattern is unanchored."""
        # If pattern starts with ^, only try at position 0
        if self.ast and isinstance(self.ast[0], Anchor) and self.ast[0].kind == '^':
            groups = [None] * self.num_groups
            result = self._match_nodes(self.ast[1:], text, 0, len(text), groups)
            if result is not None:
                return Match(
                    matched=text[:result],
                    groups=tuple(g if g is not None else '' for g in groups),
                    start=0,
                    end=result,
                )
            return None

        # Try matching at every position
        for start in range(len(text) + 1):
            groups = [None] * self.num_groups
            result = self._match_nodes(self.ast, text, start, len(text), groups)
            if result is not None:
                return Match(
                    matched=text[start:result],
                    groups=tuple(g if g is not None else '' for g in groups),
                    start=start,
                    end=result,
                )
        return None

    def _match_nodes(self, nodes, text, pos, text_len, groups) -> Optional[int]:
        if not nodes:
            return pos

        node = nodes[0]
        rest = nodes[1:]

        if isinstance(node, Anchor):
            if node.kind == '$':
                if pos == text_len:
                    return self._match_nodes(rest, text, pos, text_len, groups)
                return None
            if node.kind == '^':
                if pos == 0:
                    return self._match_nodes(rest, text, pos, text_len, groups)
                return None

        if isinstance(node, Literal):
            if pos < text_len and text[pos] == node.ch:
                return self._match_nodes(rest, text, pos + 1, text_len, groups)
            return None

        if isinstance(node, Dot):
            if pos < text_len:
                return self._match_nodes(rest, text, pos + 1, text_len, groups)
            return None

        if isinstance(node, CharClass):
            if pos < text_len:
                in_class = text[pos] in node.chars
                if node.negated:
                    in_class = not in_class
                if in_class:
                    return self._match_nodes(rest, text, pos + 1, text_len, groups)
            return None

        if isinstance(node, Group):
            return self._match_group(node, rest, text, pos, text_len, groups)

        if isinstance(node, Quantifier):
            return self._match_quantifier(node, rest, text, pos, text_len, groups)

        return None

    def _match_group(self, node, rest, text, pos, text_len, groups):
        # Try matching the group's inner expression, then continue with rest
        saved = groups[:]
        inner_end = self._match_nodes(node.expr, text, pos, text_len, groups)
        if inner_end is not None:
            groups[node.index - 1] = text[pos:inner_end]
            result = self._match_nodes(rest, text, inner_end, text_len, groups)
            if result is not None:
                return result
        # Restore groups on failure
        for i in range(len(groups)):
            groups[i] = saved[i]
        return None

    def _match_quantifier(self, node, rest, text, pos, text_len, groups):
        kind = node.kind
        inner = node.node

        if kind == '?':
            # Greedy: try matching once first, then zero
            saved = groups[:]
            one = self._match_single(inner, text, pos, text_len, groups)
            if one is not None:
                result = self._match_nodes(rest, text, one, text_len, groups)
                if result is not None:
                    return result
            for i in range(len(groups)):
                groups[i] = saved[i]
            return self._match_nodes(rest, text, pos, text_len, groups)

        if kind == '*':
            # Greedy: match as many as possible, then backtrack
            positions = [pos]
            saved_groups = [groups[:]]
            p = pos
            while True:
                sg = groups[:]
                one = self._match_single(inner, text, p, text_len, groups)
                if one is None or one == p:
                    for i in range(len(groups)):
                        groups[i] = sg[i]
                    break
                positions.append(one)
                saved_groups.append(groups[:])
                p = one

            for i in range(len(positions) - 1, -1, -1):
                for j in range(len(groups)):
                    groups[j] = saved_groups[i][j]
                result = self._match_nodes(rest, text, positions[i], text_len, groups)
                if result is not None:
                    return result
            return None

        if kind == '+':
            # Must match at least once
            one = self._match_single(inner, text, pos, text_len, groups)
            if one is None or one == pos:
                return None
            positions = [one]
            saved_groups = [groups[:]]
            p = one
            while True:
                sg = groups[:]
                nxt = self._match_single(inner, text, p, text_len, groups)
                if nxt is None or nxt == p:
                    for i in range(len(groups)):
                        groups[i] = sg[i]
                    break
                positions.append(nxt)
                saved_groups.append(groups[:])
                p = nxt

            for i in range(len(positions) - 1, -1, -1):
                for j in range(len(groups)):
                    groups[j] = saved_groups[i][j]
                result = self._match_nodes(rest, text, positions[i], text_len, groups)
                if result is not None:
                    return result
            return None

        return None

    def _match_single(self, node, text, pos, text_len, groups) -> Optional[int]:
        """Match a single instance of a node (unwrapped from quantifier)."""
        if isinstance(node, Group):
            inner_end = self._match_nodes(node.expr, text, pos, text_len, groups)
            if inner_end is not None:
                groups[node.index - 1] = text[pos:inner_end]
                return inner_end
            return None
        return self._match_nodes([node], text, pos, text_len, groups)


# ─── Tests ───

class TestRegexLiteral(unittest.TestCase):
    def test_exact_match(self):
        m = RegexMatcher("hello").match("hello")
        self.assertIsNotNone(m)
        self.assertEqual(m.matched, "hello")

    def test_no_match(self):
        self.assertIsNone(RegexMatcher("hello").match("world"))

    def test_partial_match_finds_substring(self):
        m = RegexMatcher("ell").match("hello")
        self.assertIsNotNone(m)
        self.assertEqual(m.matched, "ell")
        self.assertEqual(m.start, 1)

    def test_empty_pattern_matches_empty(self):
        m = RegexMatcher("").match("")
        self.assertIsNotNone(m)
        self.assertEqual(m.matched, "")

    def test_empty_pattern_matches_any_string(self):
        m = RegexMatcher("").match("abc")
        self.assertIsNotNone(m)
        self.assertEqual(m.matched, "")


class TestDot(unittest.TestCase):
    def test_dot_matches_any_char(self):
        m = RegexMatcher("h.llo").match("hello")
        self.assertIsNotNone(m)
        self.assertEqual(m.matched, "hello")

    def test_dot_does_not_match_empty(self):
        self.assertIsNone(RegexMatcher(".").match(""))

    def test_multiple_dots(self):
        m = RegexMatcher("...").match("abc")
        self.assertIsNotNone(m)
        self.assertEqual(m.matched, "abc")

    def test_dot_in_middle(self):
        m = RegexMatcher("a.c").match("axc")
        self.assertIsNotNone(m)
        self.assertEqual(m.matched, "axc")


class TestStar(unittest.TestCase):
    def test_star_zero_times(self):
        m = RegexMatcher("ab*c").match("ac")
        self.assertIsNotNone(m)
        self.assertEqual(m.matched, "ac")

    def test_star_one_time(self):
        m = RegexMatcher("ab*c").match("abc")
        self.assertIsNotNone(m)
        self.assertEqual(m.matched, "abc")

    def test_star_many_times(self):
        m = RegexMatcher("ab*c").match("abbbbc")
        self.assertIsNotNone(m)
        self.assertEqual(m.matched, "abbbbc")

    def test_dot_star(self):
        m = RegexMatcher("a.*c").match("aXYZc")
        self.assertIsNotNone(m)
        self.assertEqual(m.matched, "aXYZc")

    def test_star_greedy(self):
        m = RegexMatcher("a.*b").match("aXbYb")
        self.assertIsNotNone(m)
        self.assertEqual(m.matched, "aXbYb")


class TestPlus(unittest.TestCase):
    def test_plus_requires_one(self):
        self.assertIsNone(RegexMatcher("ab+c").match("ac"))

    def test_plus_one(self):
        m = RegexMatcher("ab+c").match("abc")
        self.assertIsNotNone(m)
        self.assertEqual(m.matched, "abc")

    def test_plus_many(self):
        m = RegexMatcher("ab+c").match("abbbc")
        self.assertIsNotNone(m)
        self.assertEqual(m.matched, "abbbc")

    def test_dot_plus(self):
        m = RegexMatcher("a.+c").match("axyzc")
        self.assertIsNotNone(m)
        self.assertEqual(m.matched, "axyzc")

    def test_dot_plus_needs_at_least_one(self):
        self.assertIsNone(RegexMatcher("a.+c").match("ac"))


class TestQuestion(unittest.TestCase):
    def test_question_zero(self):
        m = RegexMatcher("colou?r").match("color")
        self.assertIsNotNone(m)
        self.assertEqual(m.matched, "color")

    def test_question_one(self):
        m = RegexMatcher("colou?r").match("colour")
        self.assertIsNotNone(m)
        self.assertEqual(m.matched, "colour")

    def test_question_does_not_match_two(self):
        self.assertIsNone(RegexMatcher("^ab?c$").match("abbc"))


class TestAnchors(unittest.TestCase):
    def test_caret_matches_start(self):
        m = RegexMatcher("^hello").match("hello world")
        self.assertIsNotNone(m)
        self.assertEqual(m.matched, "hello")

    def test_caret_no_match_midstring(self):
        self.assertIsNone(RegexMatcher("^world").match("hello world"))

    def test_dollar_matches_end(self):
        m = RegexMatcher("world$").match("hello world")
        self.assertIsNotNone(m)
        self.assertEqual(m.matched, "world")

    def test_dollar_no_match_not_at_end(self):
        self.assertIsNone(RegexMatcher("hello$").match("hello world"))

    def test_caret_and_dollar_exact(self):
        m = RegexMatcher("^exact$").match("exact")
        self.assertIsNotNone(m)
        self.assertEqual(m.matched, "exact")

    def test_caret_and_dollar_no_extra(self):
        self.assertIsNone(RegexMatcher("^exact$").match("not exact"))

    def test_caret_empty(self):
        m = RegexMatcher("^$").match("")
        self.assertIsNotNone(m)
        self.assertEqual(m.matched, "")


class TestCharClass(unittest.TestCase):
    def test_simple_class(self):
        m = RegexMatcher("[abc]").match("b")
        self.assertIsNotNone(m)
        self.assertEqual(m.matched, "b")

    def test_class_no_match(self):
        self.assertIsNone(RegexMatcher("^[abc]$").match("d"))

    def test_class_range(self):
        m = RegexMatcher("[a-z]").match("m")
        self.assertIsNotNone(m)
        self.assertEqual(m.matched, "m")

    def test_class_range_no_match(self):
        self.assertIsNone(RegexMatcher("^[a-z]$").match("5"))

    def test_negated_class(self):
        m = RegexMatcher("[^abc]").match("d")
        self.assertIsNotNone(m)
        self.assertEqual(m.matched, "d")

    def test_negated_class_no_match(self):
        self.assertIsNone(RegexMatcher("^[^abc]$").match("a"))

    def test_digit_range(self):
        m = RegexMatcher("[0-9]+").match("abc123def")
        self.assertIsNotNone(m)
        self.assertEqual(m.matched, "123")

    def test_multiple_ranges(self):
        m = RegexMatcher("[a-zA-Z]+").match("Hello")
        self.assertIsNotNone(m)
        self.assertEqual(m.matched, "Hello")

    def test_class_with_quantifier(self):
        m = RegexMatcher("[abc]+").match("xxcabxx")
        self.assertIsNotNone(m)
        self.assertEqual(m.matched, "cab")


class TestGroups(unittest.TestCase):
    def test_simple_group(self):
        m = RegexMatcher("(abc)").match("abc")
        self.assertIsNotNone(m)
        self.assertEqual(m.matched, "abc")
        self.assertEqual(m.group(1), "abc")

    def test_group_with_quantifier(self):
        m = RegexMatcher("(ab)+").match("ababab")
        self.assertIsNotNone(m)
        self.assertEqual(m.matched, "ababab")

    def test_nested_groups(self):
        m = RegexMatcher("((a)(b))").match("ab")
        self.assertIsNotNone(m)
        self.assertEqual(m.group(1), "ab")
        self.assertEqual(m.group(2), "a")
        self.assertEqual(m.group(3), "b")

    def test_group_captures_last(self):
        m = RegexMatcher("(a)+").match("aaa")
        self.assertIsNotNone(m)
        self.assertEqual(m.matched, "aaa")
        self.assertEqual(m.group(1), "a")

    def test_group_in_pattern(self):
        m = RegexMatcher("a(bc)d").match("abcd")
        self.assertIsNotNone(m)
        self.assertEqual(m.matched, "abcd")
        self.assertEqual(m.group(1), "bc")

    def test_optional_group(self):
        m = RegexMatcher("a(bc)?d").match("ad")
        self.assertIsNotNone(m)
        self.assertEqual(m.matched, "ad")

    def test_group_star(self):
        m = RegexMatcher("(ab)*c").match("abababc")
        self.assertIsNotNone(m)
        self.assertEqual(m.matched, "abababc")


class TestEscape(unittest.TestCase):
    def test_escape_dot(self):
        m = RegexMatcher("a\\.b").match("a.b")
        self.assertIsNotNone(m)
        self.assertEqual(m.matched, "a.b")

    def test_escape_dot_no_match(self):
        self.assertIsNone(RegexMatcher("^a\\.b$").match("axb"))

    def test_escape_star(self):
        m = RegexMatcher("a\\*b").match("a*b")
        self.assertIsNotNone(m)
        self.assertEqual(m.matched, "a*b")


class TestComplex(unittest.TestCase):
    def test_email_like(self):
        m = RegexMatcher("[a-z]+@[a-z]+\\.[a-z]+").match("user@host.com")
        self.assertIsNotNone(m)
        self.assertEqual(m.matched, "user@host.com")

    def test_ip_like(self):
        m = RegexMatcher("[0-9]+\\.[0-9]+\\.[0-9]+\\.[0-9]+").match("192.168.1.1")
        self.assertIsNotNone(m)
        self.assertEqual(m.matched, "192.168.1.1")

    def test_complex_with_groups(self):
        m = RegexMatcher("^(a+)(b+)$").match("aaabbb")
        self.assertIsNotNone(m)
        self.assertEqual(m.group(1), "aaa")
        self.assertEqual(m.group(2), "bbb")

    def test_greedy_backtrack(self):
        m = RegexMatcher("^(.+)([0-9]+)$").match("abc123")
        self.assertIsNotNone(m)
        # Greedy .+ takes as much as possible, backtracks to leave at least 1 digit
        self.assertEqual(m.group(1), "abc12")
        self.assertEqual(m.group(2), "3")

    def test_no_match_complex(self):
        self.assertIsNone(RegexMatcher("^[A-Z][a-z]+$").match("hello"))

    def test_capitalized_word(self):
        m = RegexMatcher("^[A-Z][a-z]+$").match("Hello")
        self.assertIsNotNone(m)
        self.assertEqual(m.matched, "Hello")


class TestEdgeCases(unittest.TestCase):
    def test_star_at_start(self):
        m = RegexMatcher("a*b").match("b")
        self.assertIsNotNone(m)
        self.assertEqual(m.matched, "b")

    def test_match_position(self):
        m = RegexMatcher("world").match("hello world")
        self.assertIsNotNone(m)
        self.assertEqual(m.start, 6)
        self.assertEqual(m.end, 11)

    def test_single_char(self):
        m = RegexMatcher("a").match("a")
        self.assertIsNotNone(m)
        self.assertEqual(m.matched, "a")

    def test_no_match_empty_text(self):
        self.assertIsNone(RegexMatcher("a").match(""))

    def test_dot_star_matches_empty(self):
        m = RegexMatcher(".*").match("")
        self.assertIsNotNone(m)
        self.assertEqual(m.matched, "")


if __name__ == "__main__":
    # Run assertions first as a quick smoke test
    def assert_quick():
        # Literals
        assert RegexMatcher("abc").match("abc").matched == "abc"
        assert RegexMatcher("abc").match("xabcx").matched == "abc"
        assert RegexMatcher("xyz").match("abc") is None

        # Dot
        assert RegexMatcher("a.c").match("abc").matched == "abc"
        assert RegexMatcher("a.c").match("aXc").matched == "aXc"

        # Star
        assert RegexMatcher("ab*c").match("ac").matched == "ac"
        assert RegexMatcher("ab*c").match("abbc").matched == "abbc"

        # Plus
        assert RegexMatcher("ab+c").match("abc").matched == "abc"
        assert RegexMatcher("ab+c").match("ac") is None

        # Question
        assert RegexMatcher("colou?r").match("color").matched == "color"
        assert RegexMatcher("colou?r").match("colour").matched == "colour"

        # Anchors
        assert RegexMatcher("^abc").match("abcdef").matched == "abc"
        assert RegexMatcher("^abc").match("xabc") is None
        assert RegexMatcher("abc$").match("xabc").matched == "abc"
        assert RegexMatcher("abc$").match("abcx") is None

        # Char classes
        assert RegexMatcher("[abc]").match("b").matched == "b"
        assert RegexMatcher("[a-z]+").match("hello").matched == "hello"
        assert RegexMatcher("[^0-9]+").match("abc").matched == "abc"

        # Groups
        assert RegexMatcher("(abc)").match("abc").group(1) == "abc"
        assert RegexMatcher("(a+)(b+)").match("aaabbb").group(1) == "aaa"
        assert RegexMatcher("(a+)(b+)").match("aaabbb").group(2) == "bbb"

        # Complex
        assert RegexMatcher("[a-z]+@[a-z]+\\.[a-z]+").match("user@host.com").matched == "user@host.com"

        print("All assertions passed!")

    assert_quick()

    # Run full test suite
    unittest.main(verbosity=2)
