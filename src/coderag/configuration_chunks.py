"""Source-preserving YAML/JSON structure without constructing YAML objects."""

from __future__ import annotations

import json
import re
from bisect import bisect_right
from dataclasses import dataclass, field

import yaml

CONFIGURATION_CHUNKING_VERSION = 2
MAX_DEPTH = 100
MAX_EVENTS = 150_000
MAX_NODES = 50_000


@dataclass
class Node:
    kind: str
    start: int
    end: int
    value: str | None = None
    children: list[tuple[str, int, Node]] = field(default_factory=list)


def reject_constant(value):
    raise ValueError(f'Non-standard JSON constant: {value}')


def unique_object(pairs):
    keys = set()
    for key, _ in pairs:
        if key in keys:
            raise ValueError(f'Duplicate JSON key: {key!r}')
        keys.add(key)
    return dict(pairs)


class JsonStructure:
    def __init__(self, source):
        self.source = source
        self.offset = 0
        self.nodes = 0
        self.decoder = json.JSONDecoder()

    def whitespace(self):
        while self.offset < len(self.source) and self.source[self.offset] in ' \t\r\n':
            self.offset += 1

    def node(self, depth=0):
        self.nodes += 1
        if self.nodes > MAX_NODES:
            raise ValueError('Configuration node limit exceeded')
        if depth > MAX_DEPTH:
            raise ValueError('Configuration nesting exceeds the supported depth')
        self.whitespace()
        start = self.offset
        opening = self.source[start]
        if opening not in '{[':
            value, self.offset = self.decoder.raw_decode(self.source, start)
            return Node('scalar', start, self.offset, value if isinstance(value, str) else None)
        mapping = opening == '{'
        node = Node('mapping' if mapping else 'sequence', start, start)
        closing = '}' if mapping else ']'
        self.offset += 1
        self.whitespace()
        while self.source[self.offset] != closing:
            key_start = self.offset
            if mapping:
                label, self.offset = self.decoder.raw_decode(self.source, self.offset)
                self.whitespace()
                self.offset += 1  # Colon; full JSON syntax is validated before this pass.
            else:
                label = str(len(node.children))
            child = self.node(depth + 1)
            node.children.append((label, key_start, child))
            self.whitespace()
            if self.source[self.offset] == ',':
                self.offset += 1
                self.whitespace()
            else:
                break
        self.offset += 1
        node.end = self.offset
        return node


class YamlStructure:
    def __init__(self, source):
        self.events = []
        # Events preserve alias occurrence locations and do not execute YAML constructors.
        for event in yaml.parse(source, Loader=yaml.SafeLoader):
            if len(self.events) >= MAX_EVENTS:
                raise ValueError('YAML event limit exceeded')
            self.events.append(event)
        self.offset = 0
        self.nodes = 0

    def node(self, depth=0):
        self.nodes += 1
        if self.nodes > MAX_NODES:
            raise ValueError('Configuration node limit exceeded')
        if depth > MAX_DEPTH:
            raise ValueError('Configuration nesting exceeds the supported depth')
        event = self.events[self.offset]
        self.offset += 1
        if isinstance(event, (yaml.ScalarEvent, yaml.AliasEvent)):
            value = event.value if isinstance(event, yaml.ScalarEvent) else None
            return Node('scalar', event.start_mark.index, event.end_mark.index, value)
        mapping = isinstance(event, yaml.MappingStartEvent)
        ending = yaml.MappingEndEvent if mapping else yaml.SequenceEndEvent
        node = Node('mapping' if mapping else 'sequence', event.start_mark.index, 0)
        seen = set()
        while not isinstance(self.events[self.offset], ending):
            if mapping:
                key = self.node(depth + 1)
                if key.kind != 'scalar' or key.value is None:
                    raise ValueError('Complex YAML mapping keys have no supported structural path')
                label, start = key.value, key.start
                if label in seen:
                    raise ValueError(f'Duplicate YAML key: {label!r}')
                seen.add(label)
            else:
                label, start = str(len(node.children)), self.events[self.offset].start_mark.index
            child = self.node(depth + 1)
            node.children.append((label, start, child))
        node.end = self.events[self.offset].end_mark.index
        self.offset += 1
        return node

    def documents(self):
        nodes = []
        self.offset += 1  # StreamStartEvent.
        while not isinstance(self.events[self.offset], yaml.StreamEndEvent):
            self.offset += 1  # DocumentStartEvent.
            nodes.append(self.node())
            self.offset += 1  # DocumentEndEvent.
        return nodes


def parse_configuration(source, language):
    """Parse indexed configuration snapshots without resolving YAML aliases or tags."""
    try:
        if language == 'json':
            json.loads(source, object_pairs_hook=unique_object, parse_constant=reject_constant)
            roots = [JsonStructure(source).node()]
        else:
            roots = YamlStructure(source).documents()
    except (yaml.YAMLError, RecursionError) as exc:
        raise ValueError(f'Invalid {language.upper()} structure: {exc}') from exc
    return roots


def configuration_units(source, language):
    """Return line-based units; keep list entries together and compact objects intact."""
    roots = parse_configuration(source, language)
    line_starts = [0, *(match.end() for match in re.finditer('\n', source))]

    def span(start, end):
        while end > start and source[end - 1].isspace():
            end -= 1
        return bisect_right(line_starts, start), bisect_right(line_starts, max(start, end - 1))

    units = []

    def emit(node, symbol, start=None, list_entry=False):
        start = node.start if start is None else start
        first, last = span(start, node.end)
        if start >= len(source):
            return
        units.append((first, last, symbol, f'{language}_structure'))
        if list_entry:
            return
        children = [
            (label, key_start, child, span(key_start, child.end))
            for label, key_start, child in node.children
        ]
        for index, (label, key_start, child, (begin, end)) in enumerate(children):
            # Physical lines are indivisible citation units. Shared-line siblings stay
            # in their enclosing container instead of arbitrarily selecting one key.
            if index and children[index - 1][3][1] >= begin:
                continue
            if index + 1 < len(children) and children[index + 1][3][0] <= end:
                continue
            escaped = label.replace('~', '~0').replace('/', '~1')
            emit(child, f'{symbol}/{escaped}', key_start, node.kind == 'sequence')

    for number, node in enumerate(roots):
        emit(node, '$' if len(roots) == 1 else f'$doc/{number}')
    # When a single child occupies exactly its parent's lines, keep the more
    # specific path. Shared-line siblings were deliberately kept in their parent.
    return list({(unit[0], unit[1]): unit for unit in units}.values())
