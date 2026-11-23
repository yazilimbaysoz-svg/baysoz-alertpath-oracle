"""UTF-8 strict Alertmanager matcher parsing and reasoning.

Baysöz Labs <baysozlabs@proton.me>
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Literal, Mapping, Sequence

Operator = Literal["=", "!=", "=~", "!~"]

_RESERVED = frozenset("{}!=~,\\\"'`")
_CLASSIC_LABEL = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")
_SIMPLE_ESCAPES = {
    "a": "\a",
    "b": "\b",
    "f": "\f",
    "n": "\n",
    "r": "\r",
    "t": "\t",
    "v": "\v",
    "\\": "\\",
    '"': '"',
}
_NEGATED: dict[Operator, Operator] = {
    "=": "!=",
    "!=": "=",
    "=~": "!~",
    "!~": "=~",
}


class MatcherError(ValueError):
    """Raised for an invalid or intentionally unsupported matcher."""


def _decode_quoted(text: str, start: int, path: str) -> tuple[str, int]:
    index = start + 1
    chars: list[str] = []
    while index < len(text):
        char = text[index]
        if char == '"':
            return "".join(chars), index + 1
        if char != "\\":
            chars.append(char)
            index += 1
            continue
        index += 1
        if index >= len(text):
            msg = f"{path}: dangling backslash in quoted token"
            raise MatcherError(msg)
        escape = text[index]
        if escape in _SIMPLE_ESCAPES:
            chars.append(_SIMPLE_ESCAPES[escape])
            index += 1
        elif escape in "xuU":
            width = {"x": 2, "u": 4, "U": 8}[escape]
            digits = text[index + 1 : index + 1 + width]
            if len(digits) != width or any(c not in "0123456789abcdefABCDEF" for c in digits):
                msg = f"{path}: malformed \\{escape} escape"
                raise MatcherError(msg)
            codepoint = int(digits, 16)
            if codepoint > 0x10FFFF:
                msg = f"{path}: escape exceeds Unicode range"
                raise MatcherError(msg)
            chars.append(chr(codepoint))
            index += width + 1
        elif escape in "01234567":
            digits = ""
            while len(digits) < 3 and index < len(text) and text[index] in "01234567":
                digits += text[index]
                index += 1
            codepoint = int(digits, 8)
            if codepoint > 0xFF:
                msg = f"{path}: octal escape exceeds byte range"
                raise MatcherError(msg)
            chars.append(chr(codepoint))
        else:
            msg = f"{path}: unsupported escape \\{escape}"
            raise MatcherError(msg)
    msg = f"{path}: unterminated quoted token"
    raise MatcherError(msg)


def _read_token(text: str, index: int, path: str) -> tuple[str, int, bool]:
    if index < len(text) and text[index] == '"':
        value, end = _decode_quoted(text, index, path)
        return value, end, True
    start = index
    while index < len(text) and not text[index].isspace() and text[index] not in _RESERVED:
        index += 1
    if index == start:
        msg = f"{path}: expected token at offset {index}"
        raise MatcherError(msg)
    return text[start:index], index, False


def _skip_space(text: str, index: int) -> int:
    while index < len(text) and text[index].isspace():
        index += 1
    return index


def _validate_regex(pattern: str, path: str) -> None:
    if not pattern:
        return
    if len(pattern) > 512:
        msg = f"{path}: regular expression exceeds 512 characters"
        raise MatcherError(msg)
    stack: list[int] = []
    in_class = False
    escaped = False
    for index, char in enumerate(pattern):
        if escaped:
            escaped = False
            continue
        if char == "\\":
            escaped = True
            continue
        if in_class:
            if char == "]":
                in_class = False
            continue
        if char == "[":
            in_class = True
            continue
        if char == "(":
            if pattern[index + 1 : index + 2] == "?":
                marker = pattern[index + 2 : index + 4]
                if marker.startswith(("=", "!", "<", "(")):
                    msg = f"{path}: lookaround and conditional groups are not RE2 compatible"
                    raise MatcherError(msg)
            stack.append(index)
            continue
        if char == ")" and stack:
            start = stack.pop()
            if index + 1 < len(pattern) and pattern[index + 1] in "*+?":
                body = pattern[start + 1 : index]
                if any(symbol in body for symbol in ("+", "*", "{")):
                    msg = f"{path}: nested quantifiers are rejected to prevent backtracking"
                    raise MatcherError(msg)
    if escaped or in_class:
        msg = f"{path}: malformed regular expression"
        raise MatcherError(msg)
    try:
        re.compile(pattern)
    except re.error as exc:
        msg = f"{path}: invalid regular expression: {exc}"
        raise MatcherError(msg) from exc


def split_composition(text: str, path: str) -> list[str]:
    """Split one matcher expression, with or without surrounding braces."""
    value = text.strip()
    opens = value.startswith("{")
    closes = value.endswith("}")
    if opens != closes:
        msg = f"{path}: braces must be both present or both absent"
        raise MatcherError(msg)
    if opens:
        value = value[1:-1]
    parts: list[str] = []
    current: list[str] = []
    in_quote = False
    escaped = False
    for char in value:
        if escaped:
            current.append(char)
            escaped = False
            continue
        if in_quote and char == "\\":
            current.append(char)
            escaped = True
            continue
        if char == '"':
            in_quote = not in_quote
            current.append(char)
            continue
        if char == "," and not in_quote:
            parts.append("".join(current))
            current = []
            continue
        current.append(char)
    if in_quote:
        msg = f"{path}: unterminated quote in matcher composition"
        raise MatcherError(msg)
    parts.append("".join(current))
    result: list[str] = []
    for index, part in enumerate(parts):
        piece = part.strip()
        if not piece:
            if index == len(parts) - 1:
                continue
            msg = f"{path}: empty matcher in composition"
            raise MatcherError(msg)
        result.append(piece)
    if not result:
        msg = f"{path}: empty matcher composition"
        raise MatcherError(msg)
    return result


@dataclass(frozen=True)
class Matcher:
    """A single Alertmanager label matcher."""

    label: str
    op: Operator
    value: str
    raw: str
    path: str
    compiled: re.Pattern[str] | None = field(default=None, init=False, compare=False, repr=False)

    def __post_init__(self) -> None:
        if not self.label:
            msg = f"{self.path}: empty label name"
            raise MatcherError(msg)
        if self.value == "" and self.op in ("=~", "!~"):
            return
        if self.op in ("=~", "!~"):
            _validate_regex(self.value, self.path)
            object.__setattr__(self, "compiled", re.compile(self.value))

    def matches(self, labels: Mapping[str, str]) -> bool:
        actual = labels.get(self.label, "")
        if self.op == "=":
            return actual == self.value
        if self.op == "!=":
            return actual != self.value
        if self.compiled is None:
            result = actual == ""
        else:
            result = self.compiled.fullmatch(actual) is not None
        return result if self.op == "=~" else not result

    def negated(self) -> Matcher:
        return Matcher(self.label, _NEGATED[self.op], self.value, self.raw, self.path)


def parse_single_matcher(text: str, path: str) -> Matcher:
    """Parse one matcher such as ``severity=~"crit|warn"``."""
    source = text.strip()
    if not source:
        msg = f"{path}: empty matcher"
        raise MatcherError(msg)
    label, index, label_quoted = _read_token(source, 0, path)
    if not label_quoted and _CLASSIC_LABEL.fullmatch(label) is None:
        msg = f"{path}: unquoted label name {label!r} is not a classic Prometheus label"
        raise MatcherError(msg)
    index = _skip_space(source, index)
    if source.startswith("=~", index) or source.startswith("!~", index):
        op: Operator = "=~" if source[index] == "=" else "!~"
        index += 2
    elif source.startswith("!=", index):
        op = "!="
        index += 2
    elif source.startswith("=", index):
        op = "="
        index += 1
    else:
        msg = f"{path}: expected one of =, !=, =~, !~"
        raise MatcherError(msg)
    index = _skip_space(source, index)
    if index >= len(source):
        msg = f'{path}: matcher has no value token; use "" for empty values'
        raise MatcherError(msg)
    value, index, _ = _read_token(source, index, path)
    index = _skip_space(source, index)
    if index != len(source):
        msg = f"{path}: unexpected trailing characters at offset {index}"
        raise MatcherError(msg)
    return Matcher(label, op, value, source, path)


def parse_matchers(value: object, path: str) -> list[Matcher]:
    """Parse matchers from a YAML scalar/list into a flat list."""
    if value is None:
        return []
    expressions: list[str] = []
    if isinstance(value, str):
        expressions = split_composition(value, path)
    elif isinstance(value, list):
        for index, item in enumerate(value):
            if not isinstance(item, str):
                msg = f"{path}[{index}]: matcher must be a string"
                raise MatcherError(msg)
            expressions.extend(split_composition(item, f"{path}[{index}]"))
    else:
        msg = f"{path}: matchers must be a string or list of strings"
        raise MatcherError(msg)
    return [
        parse_single_matcher(item, f"{path}[{index}]") for index, item in enumerate(expressions)
    ]


def _literal_pattern(pattern: str) -> str | None:
    if not pattern:
        return ""
    result: list[str] = []
    index = 0
    while index < len(pattern):
        char = pattern[index]
        if char in ".^$*+?[](){}|":
            return None
        if char == "\\":
            index += 1
            if index >= len(pattern):
                return None
            escape = pattern[index]
            if escape in _SIMPLE_ESCAPES:
                result.append(_SIMPLE_ESCAPES[escape])
            elif escape in ".^$*+?[](){}|\\":
                result.append(escape)
            else:
                return None
        else:
            result.append(char)
        index += 1
    return "".join(result)


def _fullmatches(pattern: str, value: str) -> bool:
    try:
        return re.fullmatch(pattern, value) is not None
    except re.error:
        return False


def _single_implies(left: Matcher, right: Matcher) -> bool:
    if left.label != right.label:
        return False
    if left.op == right.op:
        return left.value == right.value
    if left.op == "=":
        if right.op == "!=":
            return left.value != right.value
        if right.op == "=~":
            return _fullmatches(right.value, left.value)
        return not _fullmatches(right.value, left.value)
    if left.op == "!=":
        literal = _literal_pattern(right.value)
        if literal is None:
            return False
        return right.op == "!~" and left.value == literal
    if left.op == "=~":
        if right.op == "=":
            literal = _literal_pattern(left.value)
            return literal is not None and literal == right.value
        if right.op == "!=":
            return not _fullmatches(left.value, right.value)
        if right.op == "!~":
            literal = _literal_pattern(right.value)
            return literal is not None and not _fullmatches(left.value, literal)
        return False
    literal = _literal_pattern(right.value)
    if literal is None:
        return False
    if right.op == "=":
        return _fullmatches(left.value, literal)
    if right.op == "!=":
        return _fullmatches(left.value, literal)
    if right.op == "!~":
        return _fullmatches(left.value, literal)
    return False


def contradicts(left: Sequence[Matcher], right: Sequence[Matcher]) -> bool:
    """Return True when two matcher sets provably cannot match the same alert."""
    for first in left:
        for second in right:
            if first.label != second.label:
                continue
            if _single_implies(first, second.negated()) or _single_implies(second, first.negated()):
                return True
    return False


def implies_all(left: Sequence[Matcher], right: Sequence[Matcher]) -> bool:
    """Conservatively prove that every alert matching left also matches right."""
    if contradicts(left, left):
        return True
    for target in right:
        candidates = [source for source in left if source.label == target.label]
        if not candidates:
            return False
        if not any(_single_implies(source, target) for source in candidates):
            return False
    return True


def matches_all(matchers: Sequence[Matcher], labels: Mapping[str, str]) -> bool:
    return all(matcher.matches(labels) for matcher in matchers)
