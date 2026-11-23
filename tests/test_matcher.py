"""Matcher semantics tests for Baysöz Labs <baysozlabs@proton.me>."""

from __future__ import annotations

import pytest

from baysoz_alertpath.matcher import (
    MatcherError,
    contradicts,
    implies_all,
    matches_all,
    parse_matchers,
    parse_single_matcher,
)


def test_parses_braced_composition_and_matches() -> None:
    matchers = parse_matchers('{severity="critical", service=~"postgres|mysql"}', "m")
    assert [matcher.label for matcher in matchers] == ["severity", "service"]
    assert matches_all(matchers, {"severity": "critical", "service": "mysql"})
    assert not matches_all(matchers, {"severity": "warning", "service": "mysql"})


def test_strict_escape_decoding() -> None:
    matcher = parse_single_matcher(r'message="line\nbreak"', "m")
    assert matcher.value == "line\nbreak"
    assert matcher.matches({"message": "line\nbreak"})


def test_empty_value_requires_quotes() -> None:
    with pytest.raises(MatcherError):
        parse_single_matcher("foo=", "m")
    assert parse_single_matcher('foo=""', "m").matches({"other": "x"})


def test_utf8_literal_and_quoted_comma() -> None:
    matcher = parse_single_matcher('"Προμηθεύς"="foo,bar"', "m")
    assert matcher.label == "Προμηθεύς"
    assert matcher.value == "foo,bar"
    assert matcher.matches({"Προμηθεύς": "foo,bar"})


def test_rejects_python_only_regex_features() -> None:
    with pytest.raises(MatcherError):
        parse_single_matcher('x=~"(?=foo)"', "m")
    with pytest.raises(MatcherError):
        parse_single_matcher(r'x=~"(a+)+"', "m")


def test_implication_and_contradiction_are_conservative() -> None:
    broad = parse_matchers('severity="critical"', "broad")
    narrow = parse_matchers('{severity="critical", service="postgres"}', "narrow")
    assert implies_all(narrow, broad)
    assert not implies_all(broad, narrow)
    other = parse_matchers('severity="warning"', "other")
    assert contradicts(broad, other)


def test_equality_implies_anchored_regex() -> None:
    equality = parse_matchers('severity="critical"', "eq")
    regex = parse_matchers('severity=~"critical|warning"', "rx")
    negated = parse_matchers('severity!~"critical|warning"', "nrx")
    assert implies_all(equality, regex)
    assert not implies_all(equality, negated)


def test_braces_must_be_balanced() -> None:
    with pytest.raises(MatcherError):
        parse_matchers('{severity="critical"', "m")
