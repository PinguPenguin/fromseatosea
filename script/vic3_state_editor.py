#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
import tkinter as tk
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from tkinter import messagebox, ttk
from typing import Callable


CANADA_RELEVANT_TAGS = {
    "ATB",
    "BLF",
    "GBR",
    "HBC",
    "IRC",
    "NBS",
    "NVS",
    "ONT",
    "ORG",
    "QUE",
}

DEFAULT_CANADIAN_STATES = {
    "STATE_ALBERTA",
    "STATE_ALGOMA",
    "STATE_ATHABASCA",
    "STATE_BC_INTERIOR",
    "STATE_BRITISH_COLUMBIA",
    "STATE_EDMONTON",
    "STATE_KEEWATIN",
    "STATE_LABRADOR",
    "STATE_MANITOBA",
    "STATE_NEW_BRUNSWICK",
    "STATE_NEWFOUNDLAND",
    "STATE_NORTHWEST_ONTARIO",
    "STATE_NORTHWEST_TERRITORIES",
    "STATE_NORTH_SASKATCHEWAN",
    "STATE_NOUVEAU_QUEBEC",
    "STATE_NOVA_SCOTIA",
    "STATE_NUNAVUT",
    "STATE_ONTARIO",
    "STATE_ONTARIO_PENINSULA",
    "STATE_QUEBEC",
    "STATE_QUEBEC_SAGUENAY",
    "STATE_SAINT_LAURENT",
    "STATE_SASKATCHEWAN",
    "STATE_UPPER_BC",
    "STATE_VANCOUVER_ISLAND",
    "STATE_YUKON_TERRITORY",
}

DEFAULT_NEWLINE = "\r\n"
STATE_REGION_PATTERN = re.compile(r"(?m)^([ \t]*)(STATE_[A-Z0-9_]+)\s*=\s*\{")
STATE_HISTORY_PATTERN = re.compile(r"(?m)^([ \t]*)(s:STATE_[A-Z0-9_]+)\s*=\s*\{")
POP_STATE_SECTION_PATTERN = re.compile(r"(?m)^([ \t]*)(s:STATE_[A-Z0-9_]+)\s*=\s*\{")
BUILDINGS_WRAPPER_PATTERN = re.compile(r"(?m)^([ \t]*)(BUILDINGS)\s*=\s*\{")
STATES_WRAPPER_PATTERN = re.compile(r"(?m)^([ \t]*)(STATES)\s*=\s*\{")
LOCALIZATION_PATTERN = re.compile(r'(?m)^\s*(STATE_[A-Z0-9_]+):\d?\s+"(.*)"\s*$')

C2C_HISTORY_STATES_FILENAME = "c2c_history_states_override.txt"
C2C_HISTORY_POPS_FILENAME = "c2c_history_pops.txt"
C2C_HISTORY_BUILDINGS_FILENAME = "c2c_history_buildings.txt"

DARK_BG = "#14181e"
DARK_PANEL = "#1b222c"
DARK_ELEVATED = "#222b36"
DARK_BORDER = "#344150"
DARK_FG = "#e8edf4"
DARK_MUTED = "#aab6c6"
ACCENT = "#3f8cff"
ACCENT_ACTIVE = "#66a6ff"
WARNING_FG = "#ffbe76"

BUILDING_OWNERSHIP_MODE_CHOICES = ["", "country", "building", "preserve"]
BUILDING_OWNER_KIND_NATIONAL = "National"
BUILDING_OWNER_KIND_LOCAL_WORKFORCE = "Local Workforce"
BUILDING_OWNER_KIND_FINANCIAL_DISTRICT = "Financial District"
BUILDING_OWNER_KIND_MANOR_HOUSE = "Manor House"
BUILDING_OWNER_KIND_PRESERVE = "Preserve"
BUILDING_OWNER_KIND_CHOICES = [
    BUILDING_OWNER_KIND_NATIONAL,
    BUILDING_OWNER_KIND_LOCAL_WORKFORCE,
    BUILDING_OWNER_KIND_FINANCIAL_DISTRICT,
    BUILDING_OWNER_KIND_MANOR_HOUSE,
    BUILDING_OWNER_KIND_PRESERVE,
]

ARABLE_RESOURCE_DEFAULTS = {
    "building_banana_plantation",
    "building_coffee_plantation",
    "building_cotton_plantation",
    "building_dye_plantation",
    "building_livestock_ranch",
    "building_maize_farm",
    "building_opium_plantation",
    "building_rice_farm",
    "building_sugar_plantation",
    "building_tea_plantation",
    "building_tobacco_plantation",
    "building_vineyard",
    "building_wheat_farm",
}

CAPPED_RESOURCE_DEFAULTS = {
    "building_coal_mine",
    "building_fishing_wharf",
    "building_iron_mine",
    "building_lead_mine",
    "building_logging_camp",
    "building_sulfur_mine",
    "building_whaling_station",
}

DISCOVERABLE_RESOURCE_DEFAULTS = {
    "building_gold_field",
    "building_oil_rig",
    "building_rubber_plantation",
}

DISCOVERABLE_DEPLETED_TYPE_DEFAULTS = {
    "building_gold_mine",
}


@dataclass
class OwnershipSlice:
    tag: str
    province_count: int


@dataclass
class PopRow:
    culture: str = ""
    religion: str = ""
    size: str = ""


@dataclass
class ResourceCountRow:
    resource: str = ""
    amount: str = ""


@dataclass
class DiscoverableResourceRow:
    resource: str = ""
    amount: str = ""
    depleted_type: str = ""


@dataclass
class BuildingRow:
    owner_tag: str = ""
    building: str = ""
    level: str = ""
    reserves: str = ""
    ownership_mode: str = ""
    ownership_country: str = ""
    ownership_levels: str = ""
    ownership_building_type: str = ""
    ownership_region: str = ""
    template_entries: list[TopLevelEntry] = field(default_factory=list)
    ownership_template_entries: list[TopLevelEntry] = field(default_factory=list)
    preserved_add_ownership_raw: str = ""


@dataclass
class StateRecord:
    state_id: str
    display_name: str
    owners: list[OwnershipSlice]
    region_source: Path | None
    pop_source: Path | None
    building_source: Path | None
    ownership_source: Path | None
    homelands: list[str] = field(default_factory=list)
    loaded_homelands: list[str] = field(default_factory=list)
    state_history_template_entries: list[TopLevelEntry] = field(default_factory=list)
    arable_land: str = ""
    arable_resources: list[str] = field(default_factory=list)
    capped_resources: list[ResourceCountRow] = field(default_factory=list)
    discoverable_resources: list[DiscoverableResourceRow] = field(default_factory=list)
    pops_by_owner: dict[str, list[PopRow]] = field(default_factory=dict)
    buildings: list[BuildingRow] = field(default_factory=list)
    building_owner_extras: dict[str, list[str]] = field(default_factory=dict)
    building_state_extras: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    canada_focus: bool = False
    wipe_vanilla_pops_on_save: bool = False
    dirty: bool = False

    def owner_tags(self) -> list[str]:
        return [owner.tag for owner in self.owners]

    def editable_owner_tags(self) -> list[str]:
        tags = self.owner_tags()
        return tags if tags else self.all_owner_tags()

    def all_owner_tags(self) -> list[str]:
        tags = self.owner_tags()
        seen = set(tags)
        for tag in self.pops_by_owner:
            if tag not in seen:
                tags.append(tag)
                seen.add(tag)
        for tag in self.building_owner_extras:
            if tag not in seen:
                tags.append(tag)
                seen.add(tag)
        for row in self.buildings:
            if row.owner_tag and row.owner_tag not in seen:
                tags.append(row.owner_tag)
                seen.add(row.owner_tag)
        return tags


@dataclass
class TopLevelEntry:
    key: str
    raw: str


@dataclass
class TopLevelEntrySpan:
    key: str
    raw: str
    start: int
    end: int


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8-sig")


def write_text(path: Path, text: str, newline: str) -> None:
    path.write_text(text, encoding="utf-8-sig", newline=newline)


def detect_newline(path: Path) -> str:
    if not path.exists():
        return DEFAULT_NEWLINE
    data = path.read_bytes()
    if b"\r\n" in data:
        return "\r\n"
    if b"\n" in data:
        return "\n"
    return DEFAULT_NEWLINE


def combine_history_paths(mod_dir: Path, vanilla_dir: Path | None) -> list[Path]:
    combined: dict[str, Path] = {}
    if vanilla_dir is not None and vanilla_dir.is_dir():
        for path in vanilla_dir.glob("*.txt"):
            combined[path.name.lower()] = path
    if mod_dir.is_dir():
        for path in mod_dir.glob("*.txt"):
            combined[path.name.lower()] = path
    return [combined[name] for name in sorted(combined)]


def find_matching_brace(text: str, brace_index: int) -> int:
    depth = 0
    for index in range(brace_index, len(text)):
        char = text[index]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return index
    raise ValueError("Unbalanced braces in text block")


def iter_named_blocks(text: str, pattern: re.Pattern[str]) -> list[tuple[str, int, int, str]]:
    blocks: list[tuple[str, int, int, str]] = []
    position = 0
    while True:
        match = pattern.search(text, position)
        if not match:
            break
        brace_index = text.find("{", match.end() - 1)
        close_index = find_matching_brace(text, brace_index)
        start = match.start()
        end = close_index + 1
        key = match.group(2)
        blocks.append((key, start, end, text[start:end]))
        position = end
    return blocks


def find_named_block(text: str, key: str, pattern: re.Pattern[str]) -> tuple[int, int, str] | None:
    for block_key, start, end, block_text in iter_named_blocks(text, pattern):
        if block_key == key:
            return start, end, block_text
    return None


def replace_named_block(text: str, key: str, pattern: re.Pattern[str], new_block: str) -> str:
    found = find_named_block(text, key, pattern)
    if found is None:
        raise KeyError(f"Could not find block {key}")
    start, end, _ = found
    return text[:start] + new_block + text[end:]


def parse_top_level_entry_spans(block_text: str) -> list[TopLevelEntrySpan]:
    open_index = block_text.find("{")
    close_index = block_text.rfind("}")
    if open_index == -1 or close_index == -1 or close_index <= open_index:
        return []
    entries: list[TopLevelEntrySpan] = []
    index = open_index + 1
    while index < close_index:
        while index < close_index and block_text[index].isspace():
            index += 1
        if index >= close_index:
            break
        entry_start = index
        equal_index = index
        depth = 0
        while equal_index < close_index:
            char = block_text[equal_index]
            if char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
            elif char == "=" and depth == 0:
                break
            equal_index += 1
        if equal_index >= close_index:
            break
        key = block_text[entry_start:equal_index].strip()
        value_start = equal_index + 1
        while value_start < close_index and block_text[value_start] in " \t":
            value_start += 1
        if value_start < close_index and block_text[value_start] == "{":
            entry_end = find_matching_brace(block_text, value_start) + 1
        else:
            entry_end = value_start
            while entry_end < close_index and block_text[entry_end] not in "\r\n":
                entry_end += 1
        while entry_end < close_index and block_text[entry_end] in "\r\n":
            entry_end += 1
        entries.append(TopLevelEntrySpan(key=key, raw=block_text[entry_start:entry_end].rstrip(), start=entry_start, end=entry_end))
        index = entry_end
    return entries


def parse_top_level_entries(block_text: str) -> list[TopLevelEntry]:
    return [TopLevelEntry(entry.key, entry.raw) for entry in parse_top_level_entry_spans(block_text)]


def find_top_level_entry_span(block_text: str, key: str) -> TopLevelEntrySpan | None:
    for entry in parse_top_level_entry_spans(block_text):
        if entry.key == key:
            return entry
    return None


def replace_top_level_entry(block_text: str, key: str, new_entry: str) -> str:
    found = find_top_level_entry_span(block_text, key)
    if found is None:
        raise KeyError(f"Could not find top-level entry {key}")
    line_start = found.start
    while line_start > 0 and block_text[line_start - 1] in " \t":
        line_start -= 1
    prefix = block_text[:line_start].rstrip("\r\n")
    suffix = block_text[found.end :].lstrip("\r\n")
    if not suffix:
        separator = "\n" if prefix.rstrip().endswith("{") else "\n\n"
        return prefix + separator + new_entry
    separator = "\n" if suffix.startswith("}") else "\n\n"
    return prefix + separator + new_entry + separator + suffix


def remove_top_level_entry(block_text: str, key: str) -> str:
    found = find_top_level_entry_span(block_text, key)
    if found is None:
        return block_text
    line_start = found.start
    while line_start > 0 and block_text[line_start - 1] in " \t":
        line_start -= 1
    prefix = block_text[:line_start].rstrip("\r\n")
    suffix = block_text[found.end :].lstrip("\r\n")
    if not suffix:
        return prefix
    if prefix.rstrip().endswith("{") or suffix.startswith("}"):
        separator = "\n"
    else:
        separator = "\n\n"
    return prefix + separator + suffix


def insert_top_level_entry(block_text: str, new_entry: str) -> str:
    close_index = block_text.rfind("}")
    if close_index == -1:
        raise ValueError("Block has no closing brace")
    prefix = block_text[:close_index].rstrip("\r\n")
    suffix = block_text[close_index:]
    joiner = "\n" if prefix.rstrip().endswith("{") else "\n\n"
    return f"{prefix}{joiner}{new_entry}\n{suffix}"


def detect_child_indent(block_text: str, default: str = "    ") -> str:
    for line in block_text.splitlines():
        stripped = line.lstrip()
        indent = line[: len(line) - len(stripped)]
        if stripped and stripped != "}" and indent:
            return indent
    return default


def indent_unit(indent: str) -> str:
    return "\t" if "\t" in indent else "    "


def normalize_entry_indentation(raw: str, child_indent: str) -> str:
    lines = raw.splitlines()
    non_empty_indents = []
    for line in lines:
        if not line.strip():
            continue
        stripped = line.lstrip()
        indent = line[: len(line) - len(stripped)]
        non_empty_indents.append(len(indent))
    base_indent = min(non_empty_indents) if non_empty_indents else 0

    normalized_lines = []
    for line in lines:
        if not line.strip():
            normalized_lines.append("")
            continue
        stripped_line = line[base_indent:] if len(line) >= base_indent else line.lstrip()
        normalized_lines.append(f"{child_indent}{stripped_line}")
    return "\n".join(normalized_lines)


def parse_quoted_list(raw: str) -> list[str]:
    return re.findall(r'"([^"]+)"', raw)


def parse_inline_building_amounts(raw: str) -> list[ResourceCountRow]:
    rows: list[ResourceCountRow] = []
    for match in re.finditer(r"(?m)^\s*([A-Za-z0-9_]+)\s*=\s*(-?\d+)\s*$", raw):
        rows.append(ResourceCountRow(match.group(1), match.group(2)))
    return rows


def parse_discoverable_resource(raw: str) -> DiscoverableResourceRow:
    resource_match = re.search(r'type\s*=\s*"([^"]+)"', raw)
    amount_match = re.search(r"undiscovered_amount\s*=\s*(-?\d+)", raw)
    depleted_match = re.search(r'depleted_type\s*=\s*"([^"]+)"', raw)
    return DiscoverableResourceRow(
        resource=resource_match.group(1) if resource_match else "",
        amount=amount_match.group(1) if amount_match else "",
        depleted_type=depleted_match.group(1) if depleted_match else "",
    )


def parse_pop_rows(owner_block_text: str) -> list[PopRow]:
    rows: list[PopRow] = []
    for entry in parse_top_level_entries(owner_block_text):
        if entry.key != "create_pop":
            continue
        culture_match = re.search(r"(?m)^\s*culture\s*=\s*([A-Za-z0-9_]+)\s*$", entry.raw)
        religion_match = re.search(r"(?m)^\s*religion\s*=\s*([A-Za-z0-9_]+)\s*$", entry.raw)
        size_match = re.search(r"(?m)^\s*size\s*=\s*(-?\d+)\s*$", entry.raw)
        rows.append(
            PopRow(
                culture=culture_match.group(1) if culture_match else "",
                religion=religion_match.group(1) if religion_match else "",
                size=size_match.group(1) if size_match else "",
            )
        )
    return rows


def normalize_culture_id(value: str) -> str:
    return value.strip().strip('"').removeprefix("cu:")


def parse_homeland_culture(raw: str) -> str:
    value = parse_assignment_value(raw, "add_homeland")
    return normalize_culture_id(value) if value is not None else ""


def parse_homeland_effect_culture(raw: str, key: str) -> str:
    value = parse_assignment_value(raw, key)
    return normalize_culture_id(value) if value is not None else ""


def parse_state_history_block(block_text: str) -> tuple[list[OwnershipSlice], list[str], list[TopLevelEntry]]:
    owners: list[OwnershipSlice] = []
    homelands: list[str] = []
    entries = parse_top_level_entries(block_text)
    for entry in entries:
        if entry.key != "create_state":
            if entry.key == "add_homeland":
                culture = parse_homeland_culture(entry.raw)
                if culture:
                    homelands.append(culture)
            continue
        tag_match = re.search(r"country\s*=\s*c:([A-Z0-9_]+)", entry.raw)
        provinces_match = re.search(r"owned_provinces\s*=\s*\{([^}]*)\}", entry.raw, re.S)
        provinces = re.findall(r'"([^"]+)"', provinces_match.group(1)) if provinces_match else []
        if tag_match:
            owners.append(OwnershipSlice(tag_match.group(1), len(provinces)))
    return owners, homelands, entries


def apply_state_history_blocks(blocks: list[tuple[Path, str]]) -> tuple[list[OwnershipSlice], list[str]]:
    owners: list[OwnershipSlice] = []
    homelands: list[str] = []
    homeland_set: set[str] = set()

    for _path, block_text in blocks:
        block_owners = parse_ownership_block(block_text)
        if block_owners:
            owners = block_owners
        for entry in parse_top_level_entries(block_text):
            if entry.key == "remove_homeland":
                culture = parse_homeland_effect_culture(entry.raw, "remove_homeland")
                if culture and culture in homeland_set:
                    homelands = [existing for existing in homelands if existing != culture]
                    homeland_set.remove(culture)
            elif entry.key == "add_homeland":
                culture = parse_homeland_effect_culture(entry.raw, "add_homeland")
                if culture and culture not in homeland_set:
                    homelands.append(culture)
                    homeland_set.add(culture)

    return owners, homelands


def parse_ownership_block(block_text: str) -> list[OwnershipSlice]:
    owners, _homelands, _entries = parse_state_history_block(block_text)
    return owners


def parse_localizations(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    text = read_text(path)
    result: dict[str, str] = {}
    for key, value in LOCALIZATION_PATTERN.findall(text):
        result[key] = value
    return result


def parse_state_region_block(block_text: str) -> tuple[str, list[str], list[ResourceCountRow], list[DiscoverableResourceRow]]:
    arable_land_match = re.search(r"(?m)^\s*arable_land\s*=\s*(-?\d+)\s*$", block_text)
    arable_land = arable_land_match.group(1) if arable_land_match else ""
    arable_resources: list[str] = []
    capped_resources: list[ResourceCountRow] = []
    discoverables: list[DiscoverableResourceRow] = []
    for entry in parse_top_level_entries(block_text):
        if entry.key == "arable_resources":
            arable_resources = parse_quoted_list(entry.raw)
        elif entry.key == "capped_resources":
            capped_resources = parse_inline_building_amounts(entry.raw)
        elif entry.key == "resource":
            discoverables.append(parse_discoverable_resource(entry.raw))
    return arable_land, arable_resources, capped_resources, discoverables


def build_effective_blocks(paths: list[Path], pattern: re.Pattern[str]) -> dict[str, list[tuple[Path, str]]]:
    occurrences: dict[str, list[tuple[Path, str]]] = defaultdict(list)
    for path in sorted(paths, key=lambda item: item.name.lower()):
        text = read_text(path)
        for key, _start, _end, block_text in iter_named_blocks(text, pattern):
            occurrences[key].append((path, block_text))
    return occurrences


def find_last_wrapper_close(text: str) -> int:
    matches = list(re.finditer(r"(?m)^[ \t]*}\s*$", text))
    if matches:
        return matches[-1].start()
    return len(text)


def iter_pop_state_sections(text: str) -> list[tuple[str, int, int, str]]:
    matches = list(POP_STATE_SECTION_PATTERN.finditer(text))
    if not matches:
        return []
    wrapper_close = find_last_wrapper_close(text)
    sections: list[tuple[str, int, int, str]] = []
    for index, match in enumerate(matches):
        key = match.group(2)
        start = match.start()
        end = matches[index + 1].start() if index + 1 < len(matches) else wrapper_close
        section_text = text[start:end].rstrip("\r\n")
        sections.append((key, start, end, section_text))
    return sections


def find_pop_state_section(text: str, key: str) -> tuple[int, int, str] | None:
    for section_key, start, end, section_text in iter_pop_state_sections(text):
        if section_key == key:
            return start, end, section_text
    return None


def replace_pop_state_section(text: str, key: str, new_section: str) -> str:
    found = find_pop_state_section(text, key)
    if found is None:
        wrapper_close = find_last_wrapper_close(text)
        prefix = text[:wrapper_close].rstrip("\r\n")
        suffix = text[wrapper_close:]
        joiner = "\n\n" if prefix else ""
        return f"{prefix}{joiner}{new_section}\n{suffix.lstrip(chr(10)).lstrip(chr(13))}"
    start, end, _old = found
    prefix = text[:start].rstrip("\r\n")
    suffix = text[end:].lstrip("\r\n")
    if not suffix:
        separator = "\n" if prefix.rstrip().endswith("{") else "\n\n"
        return prefix + separator + new_section
    separator = "\n" if suffix.startswith("}") else "\n\n"
    return prefix + separator + new_section + separator + suffix


def remove_pop_state_section(text: str, key: str) -> str:
    found = find_pop_state_section(text, key)
    if found is None:
        return text
    start, end, _old = found
    prefix = text[:start].rstrip("\r\n")
    suffix = text[end:].lstrip("\r\n")
    if not suffix:
        return prefix
    if prefix.rstrip().endswith("{") or suffix.startswith("}"):
        separator = "\n"
    else:
        separator = "\n\n"
    return prefix + separator + suffix


def parse_pops_by_owner_tolerant(section_text: str) -> dict[str, list[PopRow]]:
    owner_matches = [(match.start(), match.group(1)) for match in re.finditer(r"(?m)^\s*region_state:([A-Z0-9_]+)\s*=\s*\{", section_text)]
    if not owner_matches:
        return {}

    pops_by_owner: dict[str, list[PopRow]] = defaultdict(list)
    seen_keys: dict[str, set[tuple[str, str, str]]] = defaultdict(set)
    owner_index = 0
    current_owner = owner_matches[0][1]

    for match in re.finditer(r"(?m)^\s*create_pop\s*=\s*\{", section_text):
        while owner_index + 1 < len(owner_matches) and owner_matches[owner_index + 1][0] <= match.start():
            owner_index += 1
            current_owner = owner_matches[owner_index][1]

        brace_index = section_text.find("{", match.end() - 1)
        if brace_index == -1:
            continue
        try:
            close_index = find_matching_brace(section_text, brace_index)
        except ValueError:
            continue
        block = section_text[match.start(): close_index + 1]
        culture_match = re.search(r"(?m)^\s*culture\s*=\s*([A-Za-z0-9_]+)\s*$", block)
        religion_match = re.search(r"(?m)^\s*religion\s*=\s*([A-Za-z0-9_]+)\s*$", block)
        size_match = re.search(r"(?m)^\s*size\s*=\s*(-?\d+)\s*$", block)
        if not culture_match or not size_match:
            continue
        row = PopRow(
            culture=culture_match.group(1),
            religion=religion_match.group(1) if religion_match else "",
            size=size_match.group(1),
        )
        dedupe_key = (row.culture, row.religion, row.size)
        if dedupe_key in seen_keys[current_owner]:
            continue
        seen_keys[current_owner].add(dedupe_key)
        pops_by_owner[current_owner].append(row)

    return dict(pops_by_owner)


def normalize_religion_id(value: str) -> str:
    return value.strip().strip('"').removeprefix("rel:")


def parse_create_pop_entry(raw: str) -> PopRow | None:
    culture_match = re.search(r"(?m)^\s*culture\s*=\s*([A-Za-z0-9_:]+)\s*$", raw)
    size_match = re.search(r"(?m)^\s*size\s*=\s*(-?\d+)\s*$", raw)
    if not culture_match or not size_match:
        return None
    religion_match = re.search(r"(?m)^\s*religion\s*=\s*([A-Za-z0-9_:]+)\s*$", raw)
    return PopRow(
        culture=normalize_culture_id(culture_match.group(1)),
        religion=normalize_religion_id(religion_match.group(1)) if religion_match else "",
        size=size_match.group(1),
    )


def apply_pop_kill_effect(
    owner_rows: dict[str, dict[tuple[str, str], int]],
    percent: float,
    owner_tag: str | None = None,
    culture: str | None = None,
    religion: str | None = None,
) -> None:
    remaining_ratio = max(0.0, 1.0 - percent)
    owner_tags = [owner_tag] if owner_tag is not None else list(owner_rows)
    for current_owner in owner_tags:
        bucket = owner_rows.get(current_owner)
        if not bucket:
            continue
        for key in list(bucket):
            current_culture, current_religion = key
            if culture and current_culture != culture:
                continue
            if religion and current_religion != religion:
                continue
            remaining = int(round(bucket[key] * remaining_ratio))
            if remaining <= 0:
                del bucket[key]
            else:
                bucket[key] = remaining


def apply_pop_effect_blocks(blocks: list[tuple[Path, str]]) -> tuple[dict[str, list[PopRow]], int]:
    owner_rows: dict[str, dict[tuple[str, str], int]] = {}
    unsupported_effects = 0

    def ensure_owner(owner_tag: str) -> dict[tuple[str, str], int]:
        return owner_rows.setdefault(owner_tag, {})

    for _path, block_text in blocks:
        for entry in parse_top_level_entries(block_text):
            if entry.key == "kill_population_percent_in_state":
                if re.search(r"(?m)^\s*pop_type\s*=", entry.raw):
                    unsupported_effects += 1
                    continue
                percent = parse_assignment_float(entry.raw, "percent")
                if percent is None:
                    unsupported_effects += 1
                    continue
                culture_value = parse_assignment_value(entry.raw, "culture")
                religion_value = parse_assignment_value(entry.raw, "religion")
                apply_pop_kill_effect(
                    owner_rows,
                    percent,
                    culture=normalize_culture_id(culture_value) if culture_value else None,
                    religion=normalize_religion_id(religion_value) if religion_value else None,
                )
                continue
            if not entry.key.startswith("region_state:"):
                continue

            owner_tag = entry.key.partition(":")[2]
            bucket = ensure_owner(owner_tag)
            for owner_entry in parse_top_level_entries(entry.raw):
                if owner_entry.key == "create_pop":
                    row = parse_create_pop_entry(owner_entry.raw)
                    if row is None:
                        continue
                    size = parse_int_string(row.size)
                    if size is None or size <= 0:
                        continue
                    key = (row.culture, row.religion)
                    bucket[key] = bucket.get(key, 0) + size
                elif owner_entry.key == "kill_population_percent_in_state":
                    if re.search(r"(?m)^\s*pop_type\s*=", owner_entry.raw):
                        unsupported_effects += 1
                        continue
                    percent = parse_assignment_float(owner_entry.raw, "percent")
                    if percent is None:
                        unsupported_effects += 1
                        continue
                    culture_value = parse_assignment_value(owner_entry.raw, "culture")
                    religion_value = parse_assignment_value(owner_entry.raw, "religion")
                    apply_pop_kill_effect(
                        owner_rows,
                        percent,
                        owner_tag=owner_tag,
                        culture=normalize_culture_id(culture_value) if culture_value else None,
                        religion=normalize_religion_id(religion_value) if religion_value else None,
                    )

    pops_by_owner: dict[str, list[PopRow]] = {}
    for owner_tag, bucket in owner_rows.items():
        rows = [PopRow(culture, religion, str(size)) for (culture, religion), size in bucket.items() if size > 0]
        if rows:
            pops_by_owner[owner_tag] = rows
    return pops_by_owner, unsupported_effects


def parse_assignment_value(raw: str, key: str) -> str | None:
    match = re.search(rf'(?<![A-Za-z0-9_]){re.escape(key)}\s*=\s*(?:"([^"]+)"|([^\s{{}}]+))', raw)
    if not match:
        return None
    return match.group(1) or match.group(2)


def parse_assignment_int(raw: str, key: str) -> str | None:
    match = re.search(rf"(?<![A-Za-z0-9_]){re.escape(key)}\s*=\s*(-?\d+)", raw)
    return match.group(1) if match else None


def parse_assignment_float(raw: str, key: str) -> float | None:
    match = re.search(rf"(?<![A-Za-z0-9_]){re.escape(key)}\s*=\s*(-?\d+(?:\.\d+)?)", raw)
    return float(match.group(1)) if match else None


def normalize_country_tag(value: str) -> str:
    return value.strip().strip('"').removeprefix("c:")


def parse_country_tag(raw: str, key: str = "country") -> str:
    value = parse_assignment_value(raw, key)
    return normalize_country_tag(value) if value is not None else ""


def parse_building_ownership(raw: str, row: BuildingRow) -> bool:
    ownership_entries = parse_top_level_entries(raw)
    if len(ownership_entries) != 1 or ownership_entries[0].key not in {"country", "building"}:
        row.ownership_mode = "preserve" if raw.strip() else ""
        row.preserved_add_ownership_raw = raw
        return bool(raw.strip())

    ownership_entry = ownership_entries[0]
    row.ownership_mode = ownership_entry.key
    row.ownership_template_entries = parse_top_level_entries(ownership_entry.raw)
    if ownership_entry.key == "country":
        row.ownership_country = parse_country_tag(ownership_entry.raw)
        row.ownership_levels = parse_assignment_int(ownership_entry.raw, "levels") or ""
    else:
        row.ownership_building_type = parse_assignment_value(ownership_entry.raw, "type") or ""
        row.ownership_country = parse_country_tag(ownership_entry.raw)
        row.ownership_levels = parse_assignment_int(ownership_entry.raw, "levels") or ""
        row.ownership_region = parse_assignment_value(ownership_entry.raw, "region") or ""
    return False


def parse_building_row(owner_tag: str, raw: str) -> tuple[BuildingRow, bool]:
    row = BuildingRow(owner_tag=owner_tag, template_entries=parse_top_level_entries(raw))
    unsupported_ownership = False
    for entry in row.template_entries:
        if entry.key == "building":
            row.building = parse_assignment_value(entry.raw, "building") or ""
        elif entry.key == "level":
            row.level = parse_assignment_int(entry.raw, "level") or ""
        elif entry.key == "reserves":
            row.reserves = parse_assignment_int(entry.raw, "reserves") or ""
        elif entry.key == "add_ownership":
            unsupported_ownership = parse_building_ownership(entry.raw, row)
    return row, unsupported_ownership


def parse_building_state_block(
    block_text: str,
) -> tuple[list[BuildingRow], dict[str, list[str]], list[str], list[str], int]:
    rows: list[BuildingRow] = []
    owner_extras: dict[str, list[str]] = {}
    state_extras: list[str] = []
    owner_tags: list[str] = []
    unsupported_ownership_rows = 0

    for entry in parse_top_level_entries(block_text):
        if not entry.key.startswith("region_state:"):
            state_extras.append(entry.raw)
            continue
        owner_tag = entry.key.partition(":")[2]
        owner_tags.append(owner_tag)
        owner_extra_entries: list[str] = []
        for owner_entry in parse_top_level_entries(entry.raw):
            if owner_entry.key != "create_building":
                owner_extra_entries.append(owner_entry.raw)
                continue
            row, unsupported = parse_building_row(owner_tag, owner_entry.raw)
            rows.append(row)
            if unsupported:
                unsupported_ownership_rows += 1
        owner_extras[owner_tag] = owner_extra_entries

    return rows, owner_extras, state_extras, owner_tags, unsupported_ownership_rows


def render_inline_list(values: list[str], quote: bool = True) -> str:
    if not values:
        return "{ }"
    if quote:
        body = " ".join(f'"{value}"' for value in values)
    else:
        body = " ".join(values)
    return f"{{ {body} }}"


def render_capped_resources(rows: list[ResourceCountRow], child_indent: str, nested_indent: str) -> str:
    lines = [f"{child_indent}capped_resources = {{"]
    for row in rows:
        lines.append(f"{nested_indent}{row.resource} = {row.amount}")
    lines.append(f"{child_indent}}}")
    return "\n".join(lines)


def render_discoverable_resource(row: DiscoverableResourceRow, child_indent: str, nested_indent: str) -> str:
    lines = [f"{child_indent}resource = {{", f'{nested_indent}type = "{row.resource}"']
    if row.depleted_type.strip():
        lines.append(f'{nested_indent}depleted_type = "{row.depleted_type.strip()}"')
    lines.append(f"{nested_indent}undiscovered_amount = {row.amount}")
    lines.append(f"{child_indent}}}")
    return "\n".join(lines)


def render_state_region_block(state_id: str, original_block: str, record: StateRecord) -> str:
    entries = parse_top_level_entries(original_block)
    child_indent = detect_child_indent(original_block)
    nested_indent = child_indent + indent_unit(child_indent)
    open_index = original_block.find("{")
    header = original_block[: open_index + 1].rstrip()

    target_keys = {"arable_land", "arable_resources", "capped_resources", "resource"}
    rendered_targets = [
        f"{child_indent}arable_land = {record.arable_land.strip()}",
        f"{child_indent}arable_resources = {render_inline_list(record.arable_resources)}",
        render_capped_resources(record.capped_resources, child_indent, nested_indent),
    ]
    rendered_targets.extend(
        render_discoverable_resource(row, child_indent, nested_indent) for row in record.discoverable_resources
    )

    result_entries: list[str] = []
    inserted = False
    for entry in entries:
        if entry.key in target_keys:
            if not inserted:
                result_entries.extend(rendered_targets)
                inserted = True
            continue
        result_entries.append(normalize_entry_indentation(entry.raw.rstrip(), child_indent))
    if not inserted:
        result_entries.extend(rendered_targets)

    rebuilt = header
    if result_entries:
        rebuilt += "\n" + "\n".join(result_entries) + "\n"
    else:
        rebuilt += "\n"
    rebuilt += "}"
    return rebuilt


def normalize_pop_rows(rows: list[PopRow]) -> list[PopRow]:
    merged: Counter[tuple[str, str]] = Counter()
    order: list[tuple[str, str]] = []
    for row in rows:
        culture = row.culture.strip()
        religion = row.religion.strip()
        size = parse_int_string(row.size)
        if not culture and not religion and row.size.strip() == "":
            continue
        if not culture:
            raise ValueError("Every population row must include a culture")
        if size is None or size < 0:
            raise ValueError("Population row sizes must be non-negative integers")
        if size == 0:
            continue
        key = (culture, religion)
        if key not in merged:
            order.append(key)
        merged[key] += size
    return [PopRow(culture, religion, str(merged[(culture, religion)])) for culture, religion in order]


def render_pop_state_block(record: StateRecord) -> str:
    lines = [f"\ts:{record.state_id} = {{"]
    owner_tags = record.editable_owner_tags()
    if record.wipe_vanilla_pops_on_save and not owner_tags:
        lines.append("\t\tkill_population_percent_in_state = {")
        lines.append("\t\t\tpercent = 1")
        lines.append("\t\t}")
    for owner_tag in owner_tags:
        rows = normalize_pop_rows(record.pops_by_owner.get(owner_tag, []))
        if not rows and not record.wipe_vanilla_pops_on_save:
            continue
        lines.append(f"\t\tregion_state:{owner_tag} = {{")
        if record.wipe_vanilla_pops_on_save:
            lines.append("\t\t\tkill_population_percent_in_state = {")
            lines.append("\t\t\t\tpercent = 1")
            lines.append("\t\t\t}")
        for row in rows:
            lines.append("\t\t\tcreate_pop = {")
            lines.append(f"\t\t\t\tculture = {row.culture}")
            if row.religion.strip():
                lines.append(f"\t\t\t\treligion = {row.religion}")
            lines.append(f"\t\t\t\tsize = {row.size}")
            lines.append("\t\t\t}")
        lines.append("\t\t}")
    lines.append("\t}")
    return "\n".join(lines)


def render_state_history_block(record: StateRecord, original_block: str) -> str:
    entries = record.state_history_template_entries or parse_top_level_entries(original_block)
    child_indent = detect_child_indent(original_block, default="\t")
    open_index = original_block.find("{")
    header = original_block[: open_index + 1].rstrip()
    homeland_entries = [f"{child_indent}add_homeland = cu:{culture}" for culture in record.homelands if culture.strip()]

    result_entries: list[str] = []
    inserted = False
    for entry in entries:
        if entry.key == "add_homeland":
            if not inserted:
                result_entries.extend(homeland_entries)
                inserted = True
            continue
        result_entries.append(normalize_entry_indentation(entry.raw.rstrip(), child_indent))
    if not inserted:
        result_entries.extend(homeland_entries)

    rebuilt = header
    if result_entries:
        rebuilt += "\n" + "\n".join(result_entries) + "\n"
    else:
        rebuilt += "\n"
    rebuilt += "}"
    return rebuilt


def render_state_history_effect_block(record: StateRecord, baseline_homelands: list[str]) -> str | None:
    baseline = [normalize_culture_id(culture) for culture in baseline_homelands if normalize_culture_id(culture)]
    desired = [normalize_culture_id(culture) for culture in record.homelands if normalize_culture_id(culture)]

    remove_order = [culture for culture in baseline if culture not in desired]
    add_order = [culture for culture in desired if culture not in baseline]
    if not remove_order and not add_order:
        return None

    lines = [f"\ts:{record.state_id} = {{"]
    for culture in remove_order:
        lines.append(f"\t\tremove_homeland = cu:{culture}")
    for culture in add_order:
        lines.append(f"\t\tadd_homeland = cu:{culture}")
    lines.append("\t}")
    return "\n".join(lines)


def render_ordered_entries(
    template_entries: list[TopLevelEntry],
    renderers: dict[str, Callable[[], str | None]],
    child_indent: str,
    preferred_order: list[str],
    ignored_keys: set[str] | None = None,
) -> list[str]:
    lines: list[str] = []
    rendered_keys: set[str] = set()
    ignored = ignored_keys or set()
    for entry in template_entries:
        if entry.key in ignored:
            continue
        if entry.key in renderers:
            if entry.key in rendered_keys:
                continue
            rendered = renderers[entry.key]()
            if rendered:
                lines.append(rendered)
            rendered_keys.add(entry.key)
            continue
        lines.append(normalize_entry_indentation(entry.raw.rstrip(), child_indent))

    for key in preferred_order:
        if key in rendered_keys:
            continue
        rendered = renderers[key]()
        if rendered:
            lines.append(rendered)
    return lines


def render_building_add_ownership(
    row: BuildingRow,
    child_indent: str,
    nested_indent: str,
    deep_indent: str,
) -> str | None:
    mode = row.ownership_mode.strip()
    if mode == "":
        return None
    if mode == "preserve":
        if not row.preserved_add_ownership_raw.strip():
            return None
        return normalize_entry_indentation(row.preserved_add_ownership_raw.rstrip(), child_indent)
    if mode not in {"country", "building"}:
        raise ValueError(f"Unsupported ownership mode '{mode}'")

    if mode == "country":
        inner_renderers = {
            "country": lambda: f'{deep_indent}country = "c:{row.ownership_country.strip()}"'
            if row.ownership_country.strip()
            else None,
            "levels": lambda: f"{deep_indent}levels = {row.ownership_levels.strip()}"
            if row.ownership_levels.strip()
            else None,
        }
        inner_entries = render_ordered_entries(
            row.ownership_template_entries,
            inner_renderers,
            deep_indent,
            ["country", "levels"],
            ignored_keys={"type", "region"},
        )
    else:
        inner_renderers = {
            "type": lambda: f'{deep_indent}type = "{row.ownership_building_type.strip()}"'
            if row.ownership_building_type.strip()
            else None,
            "country": lambda: f'{deep_indent}country = "c:{row.ownership_country.strip()}"'
            if row.ownership_country.strip()
            else None,
            "levels": lambda: f"{deep_indent}levels = {row.ownership_levels.strip()}"
            if row.ownership_levels.strip()
            else None,
            "region": lambda: f'{deep_indent}region = "{row.ownership_region.strip()}"'
            if row.ownership_region.strip()
            else None,
        }
        inner_entries = render_ordered_entries(
            row.ownership_template_entries,
            inner_renderers,
            deep_indent,
            ["type", "country", "levels", "region"],
        )

    lines = [f"{child_indent}add_ownership = {{", f"{nested_indent}{mode} = {{"]
    lines.extend(inner_entries)
    lines.append(f"{nested_indent}}}")
    lines.append(f"{child_indent}}}")
    return "\n".join(lines)


def render_building_row(
    row: BuildingRow,
    create_indent: str,
    child_indent: str,
    nested_indent: str,
    deep_indent: str,
) -> str:
    renderers = {
        "building": lambda: f'{child_indent}building = "{row.building.strip()}"'
        if row.building.strip()
        else None,
        "level": lambda: f"{child_indent}level = {row.level.strip()}" if row.level.strip() else None,
        "reserves": lambda: f"{child_indent}reserves = {row.reserves.strip()}" if row.reserves.strip() else None,
        "add_ownership": lambda: render_building_add_ownership(row, child_indent, nested_indent, deep_indent),
    }
    entries = render_ordered_entries(
        row.template_entries,
        renderers,
        child_indent,
        ["building", "level", "reserves", "add_ownership"],
    )
    lines = [f"{create_indent}create_building = {{"]
    lines.extend(entries)
    lines.append(f"{create_indent}}}")
    return "\n".join(lines)


def render_building_state_block(record: StateRecord, wrapper_block: str | None = None) -> str:
    state_indent = detect_child_indent(wrapper_block, default="\t") if wrapper_block else "\t"
    owner_indent = state_indent + indent_unit(state_indent)
    create_indent = owner_indent + indent_unit(owner_indent)
    child_indent = create_indent + indent_unit(create_indent)
    nested_indent = child_indent + indent_unit(child_indent)
    deep_indent = nested_indent + indent_unit(nested_indent)

    rows_by_owner: dict[str, list[BuildingRow]] = defaultdict(list)
    for row in record.buildings:
        rows_by_owner[row.owner_tag].append(row)

    lines = [f"{state_indent}s:{record.state_id} = {{"]
    for owner_tag in record.editable_owner_tags():
        lines.append(f"{owner_indent}region_state:{owner_tag} = {{")
        for row in rows_by_owner.get(owner_tag, []):
            lines.append(render_building_row(row, create_indent, child_indent, nested_indent, deep_indent))
        for raw_extra in record.building_owner_extras.get(owner_tag, []):
            lines.append(normalize_entry_indentation(raw_extra.rstrip(), create_indent))
        lines.append(f"{owner_indent}}}")
    for raw_extra in record.building_state_extras:
        lines.append(normalize_entry_indentation(raw_extra.rstrip(), owner_indent))
    lines.append(f"{state_indent}}}")
    return "\n".join(lines)


def normalize_rendered_text(raw: str) -> str:
    return re.sub(r"\s+", "", raw)


def apply_building_effect_blocks(blocks: list[tuple[Path, str]]) -> tuple[list[BuildingRow], list[str], int]:
    rows_by_owner: dict[str, dict[str, BuildingRow]] = {}
    owner_order: list[str] = []
    unsupported_entries = 0

    for _path, block_text in blocks:
        for entry in parse_top_level_entries(block_text):
            if not entry.key.startswith("region_state:"):
                if entry.key.strip():
                    unsupported_entries += 1
                continue

            owner_tag = entry.key.partition(":")[2]
            if owner_tag not in rows_by_owner:
                rows_by_owner[owner_tag] = {}
                owner_order.append(owner_tag)
            owner_bucket = rows_by_owner[owner_tag]

            for owner_entry in parse_top_level_entries(entry.raw):
                if owner_entry.key == "create_building":
                    row, unsupported_ownership = parse_building_row(owner_tag, owner_entry.raw)
                    if row.building.strip():
                        owner_bucket[row.building.strip()] = row
                    if unsupported_ownership:
                        unsupported_entries += 1
                elif owner_entry.key == "remove_building":
                    building_id = parse_assignment_value(owner_entry.raw, "remove_building") or ""
                    if building_id:
                        owner_bucket.pop(building_id, None)
                else:
                    unsupported_entries += 1

    rows: list[BuildingRow] = []
    for owner_tag in owner_order:
        rows.extend(rows_by_owner.get(owner_tag, {}).values())
    return rows, owner_order, unsupported_entries


def render_building_effect_state_block(record: StateRecord, baseline_rows: list[BuildingRow]) -> str | None:
    def group_rows(rows: list[BuildingRow]) -> tuple[dict[str, dict[str, BuildingRow]], list[str]]:
        grouped: dict[str, dict[str, BuildingRow]] = {}
        owner_order: list[str] = []
        for row in rows:
            owner_tag = row.owner_tag.strip()
            building_id = row.building.strip()
            if not owner_tag or not building_id:
                continue
            if owner_tag not in grouped:
                grouped[owner_tag] = {}
                owner_order.append(owner_tag)
            grouped[owner_tag][building_id] = row
        return grouped, owner_order

    desired_grouped, desired_owner_order = group_rows(record.buildings)
    baseline_grouped, baseline_owner_order = group_rows(baseline_rows)

    owner_order: list[str] = []
    for owner_tag in record.editable_owner_tags():
        if owner_tag not in owner_order:
            owner_order.append(owner_tag)
    for owner_tag in desired_owner_order + baseline_owner_order:
        if owner_tag not in owner_order:
            owner_order.append(owner_tag)

    create_indent = "\t\t\t"
    child_indent = create_indent + "\t"
    nested_indent = child_indent + "\t"
    deep_indent = nested_indent + "\t"

    lines = [f"\ts:{record.state_id} = {{"]
    has_ops = False
    for owner_tag in owner_order:
        desired_bucket = desired_grouped.get(owner_tag, {})
        baseline_bucket = baseline_grouped.get(owner_tag, {})
        building_order: list[str] = []
        for building_id in list(desired_bucket) + list(baseline_bucket):
            if building_id not in building_order:
                building_order.append(building_id)

        owner_lines: list[str] = []
        for building_id in building_order:
            desired_row = desired_bucket.get(building_id)
            baseline_row = baseline_bucket.get(building_id)
            if baseline_row is None and desired_row is not None:
                owner_lines.append(render_building_row(desired_row, create_indent, child_indent, nested_indent, deep_indent))
            elif baseline_row is not None and desired_row is None:
                owner_lines.append(f"{create_indent}remove_building = {building_id}")
            elif baseline_row is not None and desired_row is not None:
                baseline_text = normalize_rendered_text(
                    render_building_row(baseline_row, create_indent, child_indent, nested_indent, deep_indent)
                )
                desired_text = normalize_rendered_text(
                    render_building_row(desired_row, create_indent, child_indent, nested_indent, deep_indent)
                )
                if baseline_text != desired_text:
                    owner_lines.append(f"{create_indent}remove_building = {building_id}")
                    owner_lines.append(render_building_row(desired_row, create_indent, child_indent, nested_indent, deep_indent))

        if owner_lines:
            has_ops = True
            lines.append(f"\t\tregion_state:{owner_tag} = {{")
            lines.extend(owner_lines)
            lines.append("\t\t}")

    lines.append("\t}")
    return "\n".join(lines) if has_ops else None


def building_total_levels(row: BuildingRow) -> str:
    if row.level.strip():
        return row.level.strip()
    return row.ownership_levels.strip()


def infer_building_owner_kind(state_id: str, row: BuildingRow) -> str:
    mode = row.ownership_mode.strip()
    if mode == "preserve":
        return BUILDING_OWNER_KIND_PRESERVE
    if mode == "country":
        return BUILDING_OWNER_KIND_NATIONAL if row.ownership_country.strip() == row.owner_tag.strip() else BUILDING_OWNER_KIND_PRESERVE
    if mode == "building":
        if row.ownership_country.strip() != row.owner_tag.strip():
            return BUILDING_OWNER_KIND_PRESERVE
        building_type = row.ownership_building_type.strip()
        ownership_region = row.ownership_region.strip()
        if building_type == row.building.strip() and ownership_region == state_id:
            return BUILDING_OWNER_KIND_LOCAL_WORKFORCE
        if building_type == "building_financial_district" and ownership_region:
            return BUILDING_OWNER_KIND_FINANCIAL_DISTRICT
        if building_type == "building_manor_house" and ownership_region:
            return BUILDING_OWNER_KIND_MANOR_HOUSE
        return BUILDING_OWNER_KIND_PRESERVE
    if mode == "":
        if row.level.strip() and row.reserves.strip():
            return BUILDING_OWNER_KIND_NATIONAL
        return BUILDING_OWNER_KIND_PRESERVE
    return BUILDING_OWNER_KIND_PRESERVE


def parse_int_string(value: str) -> int | None:
    stripped = value.strip()
    if not stripped:
        return None
    try:
        return int(stripped)
    except ValueError:
        return None


def is_arable_resource_id(resource_id: str) -> bool:
    if resource_id in {"building_rubber_plantation", "building_subsistence_farm"}:
        return False
    return (
        resource_id.endswith("_farm")
        or resource_id.endswith("_ranch")
        or resource_id.endswith("_plantation")
        or resource_id == "building_vineyard"
    )


def is_capped_resource_id(resource_id: str) -> bool:
    if resource_id in {"building_gold_mine", "building_oil_rig"}:
        return False
    return resource_id.endswith("_mine") or resource_id in {
        "building_fishing_wharf",
        "building_logging_camp",
        "building_whaling_station",
    }


def is_discoverable_resource_id(resource_id: str) -> bool:
    return resource_id in DISCOVERABLE_RESOURCE_DEFAULTS


def is_discoverable_depleted_type_id(resource_id: str) -> bool:
    return resource_id in DISCOVERABLE_DEPLETED_TYPE_DEFAULTS


def build_resource_choice_lists(resource_ids: set[str]) -> tuple[list[str], list[str], list[str], list[str]]:
    all_ids = set(resource_ids)
    arable_choices = sorted(
        resource_id for resource_id in all_ids | ARABLE_RESOURCE_DEFAULTS if is_arable_resource_id(resource_id)
    )
    capped_choices = sorted(
        resource_id for resource_id in all_ids | CAPPED_RESOURCE_DEFAULTS if is_capped_resource_id(resource_id)
    )
    discoverable_choices = sorted(
        resource_id
        for resource_id in all_ids | DISCOVERABLE_RESOURCE_DEFAULTS
        if is_discoverable_resource_id(resource_id)
    )
    depleted_choices = [""] + sorted(
        resource_id
        for resource_id in all_ids | DISCOVERABLE_DEPLETED_TYPE_DEFAULTS
        if is_discoverable_depleted_type_id(resource_id)
    )
    return arable_choices, capped_choices, discoverable_choices, depleted_choices


def is_blank_pop_row(row: PopRow) -> bool:
    return not row.culture.strip() and not row.religion.strip() and not row.size.strip()


def is_blank_building_row(row: BuildingRow) -> bool:
    return (
        not row.owner_tag.strip()
        and not row.building.strip()
        and not row.level.strip()
        and not row.reserves.strip()
        and not row.ownership_mode.strip()
        and not row.ownership_country.strip()
        and not row.ownership_levels.strip()
        and not row.ownership_building_type.strip()
        and not row.ownership_region.strip()
    )


def allocate_proportional(total: int, weights: list[int]) -> list[int]:
    if total <= 0 or not weights:
        return [0 for _ in weights]
    if sum(weights) <= 0:
        weights = [1 for _ in weights]
    total_weight = sum(weights)
    base_values: list[int] = []
    remainders: list[tuple[float, int]] = []
    used = 0
    for index, weight in enumerate(weights):
        exact = total * weight / total_weight
        base = int(exact)
        base_values.append(base)
        remainders.append((exact - base, index))
        used += base
    remainders.sort(key=lambda item: (-item[0], item[1]))
    for offset in range(total - used):
        base_values[remainders[offset][1]] += 1
    return base_values


def owner_population_total(rows: list[PopRow]) -> int | None:
    total = 0
    for row in rows:
        if is_blank_pop_row(row):
            continue
        if not row.culture.strip():
            return None
        value = parse_int_string(row.size)
        if value is None:
            return None
        total += value
    return total


def validate_record(record: StateRecord) -> None:
    arable_land = parse_int_string(record.arable_land)
    if arable_land is None or arable_land < 0:
        raise ValueError("Arable land must be a non-negative integer")
    record.arable_land = str(arable_land)

    cleaned_homelands: list[str] = []
    for culture in record.homelands:
        culture_id = normalize_culture_id(culture)
        if not culture_id:
            continue
        cleaned_homelands.append(culture_id)
    record.homelands = cleaned_homelands

    cleaned_arable_resources: list[str] = []
    for resource in record.arable_resources:
        resource_id = resource.strip()
        if not resource_id:
            continue
        if not is_arable_resource_id(resource_id):
            raise ValueError(
                f"Arable resource '{resource_id}' must be a farm, ranch, or non-rubber plantation"
            )
        cleaned_arable_resources.append(resource_id)
    record.arable_resources = cleaned_arable_resources

    cleaned_capped: list[ResourceCountRow] = []
    for row in record.capped_resources:
        resource_id = row.resource.strip()
        amount = parse_int_string(row.amount)
        if not resource_id and row.amount.strip() == "":
            continue
        if not resource_id:
            raise ValueError("Each capped resource row needs a building id")
        if not is_capped_resource_id(resource_id):
            raise ValueError(
                f"Capped resource '{resource_id}' must be a mine, logging camp, fishing wharf, or whaling station"
            )
        if amount is None or amount < 0:
            raise ValueError(f"Capped resource '{resource_id}' needs a non-negative integer amount")
        if amount == 0:
            continue
        cleaned_capped.append(ResourceCountRow(resource_id, str(amount)))
    record.capped_resources = cleaned_capped

    cleaned_discoverables: list[DiscoverableResourceRow] = []
    for row in record.discoverable_resources:
        resource_id = row.resource.strip()
        amount = parse_int_string(row.amount)
        depleted_type = row.depleted_type.strip()
        if not resource_id and row.amount.strip() == "" and not depleted_type:
            continue
        if not resource_id:
            raise ValueError("Each discoverable resource row needs a type")
        if not is_discoverable_resource_id(resource_id):
            raise ValueError(
                f"Discoverable resource '{resource_id}' must be an oil rig, gold field, or rubber plantation"
            )
        if depleted_type and not is_discoverable_depleted_type_id(depleted_type):
            raise ValueError(f"Discoverable resource depleted type '{depleted_type}' is not supported")
        if depleted_type and resource_id != "building_gold_field":
            raise ValueError("Only gold fields can use a depleted type")
        if amount is None or amount < 0:
            raise ValueError(f"Discoverable resource '{resource_id}' needs a non-negative integer amount")
        if amount == 0:
            continue
        cleaned_discoverables.append(DiscoverableResourceRow(resource_id, str(amount), depleted_type))
    record.discoverable_resources = cleaned_discoverables

    normalized_pops: dict[str, list[PopRow]] = {}
    for owner_tag in record.editable_owner_tags():
        normalized_pops[owner_tag] = normalize_pop_rows(record.pops_by_owner.get(owner_tag, []))
    record.pops_by_owner = normalized_pops

    editable_owner_tags = set(record.editable_owner_tags())
    cleaned_buildings: list[BuildingRow] = []
    for row in record.buildings:
        if is_blank_building_row(row):
            continue

        owner_tag = row.owner_tag.strip()
        building_id = row.building.strip()
        level = parse_int_string(row.level)
        reserves = parse_int_string(row.reserves)
        ownership_mode = row.ownership_mode.strip()
        ownership_country = normalize_country_tag(row.ownership_country)
        ownership_levels = parse_int_string(row.ownership_levels)
        ownership_building_type = row.ownership_building_type.strip()
        ownership_region = row.ownership_region.strip().strip('"')

        if not owner_tag:
            raise ValueError("Every building row must include an owner tag")
        if editable_owner_tags and owner_tag not in editable_owner_tags:
            raise ValueError(f"Building owner tag '{owner_tag}' is not present in state history")
        if not building_id:
            raise ValueError("Every building row must include a building id")
        if level is not None and level < 0:
            raise ValueError(f"Building '{building_id}' level must be a non-negative integer")
        if reserves is not None and reserves < 0:
            raise ValueError(f"Building '{building_id}' reserves must be a non-negative integer")

        if ownership_mode == "":
            ownership_country = ""
            ownership_levels = None
            ownership_building_type = ""
            ownership_region = ""
        elif ownership_mode == "preserve":
            if not row.preserved_add_ownership_raw.strip():
                raise ValueError(
                    f"Building '{building_id}' is set to preserve ownership, but no raw ownership block exists"
                )
            ownership_country = ""
            ownership_levels = None
            ownership_building_type = ""
            ownership_region = ""
        elif ownership_mode == "country":
            if not ownership_country:
                raise ValueError(f"Building '{building_id}' country ownership requires a country tag")
            if ownership_levels is None or ownership_levels < 0:
                raise ValueError(f"Building '{building_id}' country ownership requires non-negative levels")
            ownership_building_type = ""
            ownership_region = ""
        elif ownership_mode == "building":
            if not ownership_building_type:
                raise ValueError(f"Building '{building_id}' building ownership requires a building type")
            if not ownership_country:
                raise ValueError(f"Building '{building_id}' building ownership requires a country tag")
            if ownership_levels is None or ownership_levels < 0:
                raise ValueError(f"Building '{building_id}' building ownership requires non-negative levels")
            if not ownership_region:
                raise ValueError(f"Building '{building_id}' building ownership requires a region state id")
        else:
            raise ValueError(f"Building '{building_id}' has unsupported ownership mode '{ownership_mode}'")

        if ownership_mode and level is not None:
            raise ValueError(
                f"Building '{building_id}' cannot define both Level and ownership. "
                "Victoria 3 create_building requires using either Level or Owned Levels/Owner fields, not both."
            )

        cleaned_buildings.append(
            BuildingRow(
                owner_tag=owner_tag,
                building=building_id,
                level="" if level is None else str(level),
                reserves="" if reserves is None else str(reserves),
                ownership_mode=ownership_mode,
                ownership_country=ownership_country,
                ownership_levels="" if ownership_levels is None else str(ownership_levels),
                ownership_building_type=ownership_building_type,
                ownership_region=ownership_region,
                template_entries=list(row.template_entries),
                ownership_template_entries=list(row.ownership_template_entries),
                preserved_add_ownership_raw=row.preserved_add_ownership_raw,
            )
        )
    record.buildings = cleaned_buildings


class ModRepository:
    def __init__(self, root: Path, game_root: Path | None = None) -> None:
        self.root = root
        self.game_root = game_root
        self.state_regions_dir = root / "mod" / "map_data" / "state_regions"
        self.state_history_dir = root / "mod" / "common" / "history" / "states"
        self.pops_dir = root / "mod" / "common" / "history" / "pops"
        self.buildings_dir = root / "mod" / "common" / "history" / "buildings"
        self.localization_file = root / "mod" / "localization" / "english" / "map_l_english.yml"
        self.vanilla_state_history_dir = game_root / "common" / "history" / "states" if game_root else None
        self.vanilla_pops_dir = game_root / "common" / "history" / "pops" if game_root else None
        self.vanilla_buildings_dir = game_root / "common" / "history" / "buildings" if game_root else None
        self.state_history_output_path = self.state_history_dir / C2C_HISTORY_STATES_FILENAME
        self.pop_output_path = self.pops_dir / C2C_HISTORY_POPS_FILENAME
        self.building_output_path = self.buildings_dir / C2C_HISTORY_BUILDINGS_FILENAME
        self.culture_choices: list[str] = []
        self.religion_choices: list[str] = []
        self.resource_choices: list[str] = []
        self.arable_resource_choices: list[str] = []
        self.capped_resource_choices: list[str] = []
        self.discoverable_resource_choices: list[str] = []
        self.discoverable_depleted_type_choices: list[str] = []
        self.building_choices: list[str] = []
        self.ownership_building_type_choices: list[str] = []
        self.state_records: dict[str, StateRecord] = {}
        self.global_warnings: list[str] = []

    def _combined_state_history_paths(self) -> list[Path]:
        return combine_history_paths(self.state_history_dir, self.vanilla_state_history_dir)

    def _combined_pop_paths(self) -> list[Path]:
        return combine_history_paths(self.pops_dir, self.vanilla_pops_dir)

    def _combined_building_paths(self) -> list[Path]:
        return combine_history_paths(self.buildings_dir, self.vanilla_buildings_dir)

    def _load_state_history_occurrences(self, skip_state_id: str | None = None) -> dict[str, list[tuple[Path, str]]]:
        occurrences: dict[str, list[tuple[Path, str]]] = defaultdict(list)
        target_key = f"s:{skip_state_id}" if skip_state_id else None
        for path in self._combined_state_history_paths():
            text = read_text(path)
            for key, _start, _end, block_text in iter_named_blocks(text, STATE_HISTORY_PATTERN):
                if path == self.state_history_output_path and target_key is not None and key == target_key:
                    continue
                occurrences[key].append((path, block_text))
        return occurrences

    def _load_pop_occurrences(self, skip_state_id: str | None = None) -> dict[str, list[tuple[Path, str]]]:
        occurrences: dict[str, list[tuple[Path, str]]] = defaultdict(list)
        target_key = f"s:{skip_state_id}" if skip_state_id else None
        for path in self._combined_pop_paths():
            text = read_text(path)
            for key, _start, _end, section_text in iter_pop_state_sections(text):
                if path == self.pop_output_path and target_key is not None and key == target_key:
                    continue
                occurrences[key].append((path, section_text))
        return occurrences

    def _load_building_occurrences(self, skip_state_id: str | None = None) -> dict[str, list[tuple[Path, str]]]:
        occurrences: dict[str, list[tuple[Path, str]]] = defaultdict(list)
        target_key = f"s:{skip_state_id}" if skip_state_id else None
        for path in self._combined_building_paths():
            text = read_text(path)
            wrapper = find_named_block(text, "BUILDINGS", BUILDINGS_WRAPPER_PATTERN)
            if wrapper is None:
                continue
            _start, _end, wrapper_block = wrapper
            for entry in parse_top_level_entries(wrapper_block):
                if not entry.key.startswith("s:STATE_"):
                    continue
                if path == self.building_output_path and target_key is not None and entry.key == target_key:
                    continue
                occurrences[entry.key].append((path, entry.raw))
        return occurrences

    def load(self) -> None:
        localizations = parse_localizations(self.localization_file)
        region_paths = sorted(self.state_regions_dir.glob("*.txt"), key=lambda path: path.name.lower())
        region_occurrences = build_effective_blocks(region_paths, STATE_REGION_PATTERN)
        ownership_occurrences = self._load_state_history_occurrences()
        pop_occurrences = self._load_pop_occurrences()
        building_occurrences = self._load_building_occurrences()
        vanilla_pop_keys: set[str] = set()
        if self.vanilla_pops_dir is not None and self.vanilla_pops_dir.is_dir():
            for path in sorted(self.vanilla_pops_dir.glob("*.txt"), key=lambda item: item.name.lower()):
                for key, _start, _end, _section_text in iter_pop_state_sections(read_text(path)):
                    vanilla_pop_keys.add(key.removeprefix("s:"))

        culture_ids: set[str] = set()
        religion_ids: set[str] = set()
        resource_ids: set[str] = set()
        building_ids: set[str] = set()
        ownership_building_type_ids: set[str] = set()
        records: dict[str, StateRecord] = {}

        state_ids = sorted(
            set(region_occurrences)
            | {key.removeprefix("s:") for key in ownership_occurrences}
            | {key.removeprefix("s:") for key in pop_occurrences}
            | {key.removeprefix("s:") for key in building_occurrences}
        )
        for state_id in state_ids:
            region_blocks = region_occurrences.get(state_id, [])
            ownership_blocks = ownership_occurrences.get(f"s:{state_id}", [])
            pop_blocks = pop_occurrences.get(f"s:{state_id}", [])
            building_blocks = building_occurrences.get(f"s:{state_id}", [])

            region_source, region_block = region_blocks[-1] if region_blocks else (None, None)
            owners, homelands = apply_state_history_blocks(ownership_blocks)
            culture_ids.update(culture for culture in homelands if culture)

            arable_land = ""
            arable_resources: list[str] = []
            capped_resources: list[ResourceCountRow] = []
            discoverables: list[DiscoverableResourceRow] = []
            if region_block:
                arable_land, arable_resources, capped_resources, discoverables = parse_state_region_block(region_block)
                resource_ids.update(arable_resources)
                resource_ids.update(row.resource for row in capped_resources if row.resource)
                for row in discoverables:
                    if row.resource:
                        resource_ids.add(row.resource)
                    if row.depleted_type:
                        resource_ids.add(row.depleted_type)

            pops_by_owner, unsupported_pop_effects = apply_pop_effect_blocks(pop_blocks)
            owner_tags = {owner.tag for owner in owners}
            extra_pop_tags = [owner_tag for owner_tag in pops_by_owner if owner_tag not in owner_tags]
            for pops in pops_by_owner.values():
                for row in pops:
                    if row.culture:
                        culture_ids.add(row.culture)
                    if row.religion:
                        religion_ids.add(row.religion)

            buildings, building_owner_tags, unsupported_building_entries = apply_building_effect_blocks(building_blocks)
            for row in buildings:
                if row.building:
                    building_ids.add(row.building)
                if row.ownership_building_type:
                    ownership_building_type_ids.add(row.ownership_building_type)

            warnings: list[str] = []
            if len(region_blocks) > 1:
                warnings.append("Multiple state-region definitions found; editing the last-loaded one.")
            if len(ownership_blocks) > 1:
                warnings.append("Multiple ownership history effects found; showing the combined result.")
            if len(pop_blocks) > 1:
                warnings.append("Multiple pop history effects found; showing the combined result.")
            if len(building_blocks) > 1:
                warnings.append("Multiple building history effects found; showing the combined result.")
            if extra_pop_tags:
                warnings.append(
                    "Pop data contains owner tags not present in state history: "
                    + ", ".join(sorted(extra_pop_tags))
                    + "."
                )
            extra_building_tags = [tag for tag in building_owner_tags if tag not in {owner.tag for owner in owners}]
            if extra_building_tags:
                warnings.append(
                    "Building data contains owner tags not present in state history: "
                    + ", ".join(sorted(extra_building_tags))
                    + "."
                )
            if unsupported_pop_effects:
                warnings.append(
                    f"{unsupported_pop_effects} pop history effect(s) use filters the editor does not model; displayed totals may be approximate."
                )
            if unsupported_building_entries:
                warnings.append(
                    f"{unsupported_building_entries} building history entr{'' if unsupported_building_entries == 1 else 'ies'} use patterns the editor does not model; saving this state will rewrite only remove/create_building changes."
                )
            if not ownership_blocks:
                warnings.append(f"No homeland history effect exists yet; save will write to {self.state_history_output_path.name}.")
            if not pop_blocks:
                warnings.append(f"No pop history effect exists yet; save will write to {self.pop_output_path.name}.")
            if not building_blocks:
                warnings.append(f"No building history effect exists yet; save will write to {self.building_output_path.name}.")

            canada_focus = state_id in DEFAULT_CANADIAN_STATES

            records[state_id] = StateRecord(
                state_id=state_id,
                display_name=localizations.get(state_id, state_id.removeprefix("STATE_").replace("_", " ").title()),
                owners=owners,
                region_source=region_source,
                pop_source=self.pop_output_path,
                building_source=self.building_output_path,
                ownership_source=self.state_history_output_path,
                homelands=homelands,
                loaded_homelands=list(homelands),
                state_history_template_entries=[],
                arable_land=arable_land,
                arable_resources=arable_resources,
                capped_resources=capped_resources,
                discoverable_resources=discoverables,
                pops_by_owner=pops_by_owner,
                buildings=buildings,
                building_owner_extras={},
                building_state_extras=[],
                warnings=warnings,
                canada_focus=canada_focus,
                wipe_vanilla_pops_on_save=state_id in vanilla_pop_keys,
            )

        self.state_records = records
        self.culture_choices = sorted(culture_ids)
        self.religion_choices = sorted(religion_ids)
        self.resource_choices = sorted(resource_ids)
        self.building_choices = sorted(building_ids)
        self.ownership_building_type_choices = sorted(ownership_building_type_ids)
        (
            self.arable_resource_choices,
            self.capped_resource_choices,
            self.discoverable_resource_choices,
            self.discoverable_depleted_type_choices,
        ) = build_resource_choice_lists(resource_ids)

    def save_state(self, record: StateRecord) -> None:
        validate_record(record)
        self._save_state_history_block(record)
        self._save_state_region(record)
        self._save_pop_block(record)
        self._save_building_block(record)

    def _save_state_history_block(self, record: StateRecord) -> None:
        baseline_blocks = self._load_state_history_occurrences(skip_state_id=record.state_id).get(f"s:{record.state_id}", [])
        _baseline_owners, baseline_homelands = apply_state_history_blocks(baseline_blocks)
        state_block = render_state_history_effect_block(record, baseline_homelands)
        source = self.state_history_output_path
        newline = detect_newline(source)
        state_key = f"s:{record.state_id}"
        original_text = read_text(source) if source.exists() else None

        if original_text is None:
            if state_block is None:
                record.loaded_homelands = list(record.homelands)
                record.ownership_source = source
                return
            updated = f"STATES = {{\n\n{state_block}\n}}\n"
        else:
            wrapper = find_named_block(original_text, "STATES", STATES_WRAPPER_PATTERN)
            if wrapper is None:
                if state_block is None:
                    updated = original_text
                else:
                    updated = f"STATES = {{\n\n{state_block}\n}}\n"
            else:
                wrapper_start, wrapper_end, wrapper_block = wrapper
                if state_block is None:
                    updated_wrapper = remove_top_level_entry(wrapper_block, state_key)
                elif find_top_level_entry_span(wrapper_block, state_key) is not None:
                    updated_wrapper = replace_top_level_entry(wrapper_block, state_key, state_block)
                else:
                    updated_wrapper = insert_top_level_entry(wrapper_block, state_block)
                updated = original_text[:wrapper_start] + updated_wrapper + original_text[wrapper_end:]

        if original_text is None or updated != original_text:
            write_text(source, updated, newline)
        record.loaded_homelands = list(record.homelands)
        record.ownership_source = source

    def _save_state_region(self, record: StateRecord) -> None:
        if record.region_source is None:
            raise ValueError(f"{record.state_id} has no state-region source file")
        path = record.region_source
        text = read_text(path)
        found = find_named_block(text, record.state_id, STATE_REGION_PATTERN)
        if found is None:
            raise KeyError(f"Could not find state-region block for {record.state_id}")
        _start, _end, original_block = found
        newline = detect_newline(path)
        new_block = render_state_region_block(record.state_id, original_block, record)
        updated = replace_named_block(text, record.state_id, STATE_REGION_PATTERN, new_block)
        write_text(path, updated, newline)

    def _save_pop_block(self, record: StateRecord) -> None:
        source = self.pop_output_path
        newline = detect_newline(source)
        state_key = f"s:{record.state_id}"
        state_block = render_pop_state_block(record)
        original_text = read_text(source) if source.exists() else None

        if original_text is None:
            updated = f"POPS = {{\n\n{state_block}\n}}\n"
        else:
            updated = replace_pop_state_section(original_text, state_key, state_block)

        if original_text is None or updated != original_text:
            write_text(source, updated, newline)
        record.pop_source = source

    def _save_building_block(self, record: StateRecord) -> None:
        source = self.building_output_path
        newline = detect_newline(source)
        state_key = f"s:{record.state_id}"
        baseline_blocks = self._load_building_occurrences(skip_state_id=record.state_id).get(state_key, [])
        baseline_rows, _baseline_owner_tags, _unsupported_entries = apply_building_effect_blocks(baseline_blocks)
        state_block = render_building_effect_state_block(record, baseline_rows)
        original_text = read_text(source) if source.exists() else None

        if original_text is None:
            if state_block is None:
                record.building_source = source
                return
            updated = f"BUILDINGS = {{\n\n{state_block}\n}}\n"
        else:
            wrapper = find_named_block(original_text, "BUILDINGS", BUILDINGS_WRAPPER_PATTERN)
            if wrapper is None:
                if state_block is None:
                    updated = original_text
                else:
                    updated = f"BUILDINGS = {{\n\n{state_block}\n}}\n"
            else:
                wrapper_start, wrapper_end, wrapper_block = wrapper
                if state_block is None:
                    updated_wrapper = remove_top_level_entry(wrapper_block, state_key)
                elif find_top_level_entry_span(wrapper_block, state_key) is not None:
                    updated_wrapper = replace_top_level_entry(wrapper_block, state_key, state_block)
                else:
                    updated_wrapper = insert_top_level_entry(wrapper_block, state_block)
                updated = original_text[:wrapper_start] + updated_wrapper + original_text[wrapper_end:]

        if original_text is None or updated != original_text:
            write_text(source, updated, newline)
        record.building_source = source


@dataclass
class ColumnSpec:
    key: str
    title: str
    width: int = 18
    choices: list[str] | None = None


class EditableTable(ttk.Frame):
    def __init__(
        self,
        master: tk.Misc,
        columns: list[ColumnSpec],
        on_change: Callable[[], None],
        add_label: str,
        canvas_height: int = 320,
        row_setup: Callable[[dict[str, tk.StringVar], dict[str, ttk.Widget], object | None], None] | None = None,
    ) -> None:
        super().__init__(master)
        self.columns = columns
        self.on_change = on_change
        self.row_setup = row_setup
        self.row_widgets: list[dict[str, object]] = []
        self._suspend_callbacks = False

        header = ttk.Frame(self)
        header.grid(row=0, column=0, sticky="ew")
        for column_index, column in enumerate(columns):
            ttk.Label(header, text=column.title).grid(row=0, column=column_index, sticky="w", padx=(0, 8))
            header.columnconfigure(column_index, minsize=self._column_pixel_width(column))
        ttk.Label(header, text="").grid(row=0, column=len(columns), sticky="w")
        header.columnconfigure(len(columns), minsize=80)

        scroll_frame = ttk.Frame(self)
        scroll_frame.grid(row=1, column=0, sticky="nsew")
        scroll_frame.columnconfigure(0, weight=1)
        scroll_frame.rowconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)
        self.columnconfigure(0, weight=1)

        self.rows_canvas = tk.Canvas(
            scroll_frame,
            bg=DARK_ELEVATED,
            highlightthickness=1,
            highlightbackground=DARK_BORDER,
            highlightcolor=ACCENT,
            relief="flat",
            borderwidth=0,
            height=canvas_height,
        )
        self.rows_canvas.grid(row=0, column=0, sticky="nsew")
        self.rows_scrollbar = ttk.Scrollbar(scroll_frame, orient="vertical", command=self.rows_canvas.yview)
        self.rows_scrollbar.grid(row=0, column=1, sticky="ns", padx=(8, 0))
        self.rows_canvas.configure(yscrollcommand=self.rows_scrollbar.set)

        self.rows_frame = ttk.Frame(self.rows_canvas)
        self._rows_window = self.rows_canvas.create_window((0, 0), window=self.rows_frame, anchor="nw")
        self.rows_frame.bind("<Configure>", self._sync_scroll_region)
        self.rows_canvas.bind("<Configure>", self._resize_canvas_window)
        self.rows_canvas.bind("<Enter>", self._bind_mousewheel)
        self.rows_canvas.bind("<Leave>", self._unbind_mousewheel)
        self.rows_frame.bind("<Enter>", self._bind_mousewheel)
        self.rows_frame.bind("<Leave>", self._unbind_mousewheel)

        buttons = ttk.Frame(self)
        buttons.grid(row=2, column=0, sticky="w", pady=(6, 0))
        ttk.Button(buttons, text=add_label, command=self.add_blank_row).grid(row=0, column=0, sticky="w")

    def set_rows(self, rows: list[dict[str, str]], row_metadata: list[object | None] | None = None) -> None:
        self._suspend_callbacks = True
        try:
            for row_info in self.row_widgets:
                frame: ttk.Frame = row_info["frame"]
                frame.destroy()
            self.row_widgets.clear()
            if not rows:
                self.add_blank_row(trigger_change=False, metadata=None)
                self._refresh_scroll_region()
                return
            metadata_items = row_metadata or [None for _ in rows]
            if len(metadata_items) != len(rows):
                raise ValueError("Row metadata length must match row data length")
            for row, metadata in zip(rows, metadata_items):
                self._add_row_widgets(row, trigger_change=False, metadata=metadata)
            self._refresh_scroll_region()
        finally:
            self._suspend_callbacks = False

    def get_rows(self) -> list[dict[str, str]]:
        output: list[dict[str, str]] = []
        for row_info in self.row_widgets:
            variables: dict[str, tk.StringVar] = row_info["variables"]
            output.append({key: variables[key].get() for key in variables})
        return output

    def get_rows_with_metadata(self) -> list[tuple[dict[str, str], object | None]]:
        output: list[tuple[dict[str, str], object | None]] = []
        for row_info in self.row_widgets:
            variables: dict[str, tk.StringVar] = row_info["variables"]
            metadata = row_info.get("metadata")
            output.append(({key: variables[key].get() for key in variables}, metadata))
        return output

    def set_column_choices(self, key: str, choices: list[str] | None) -> None:
        for column in self.columns:
            if column.key == key:
                column.choices = choices
                break
        for row_info in self.row_widgets:
            widgets: dict[str, ttk.Widget] = row_info["widgets"]
            widget = widgets.get(key)
            if isinstance(widget, ttk.Combobox):
                widget.configure(values=choices or [])

    def add_blank_row(self, trigger_change: bool = True, metadata: object | None = None) -> None:
        self._add_row_widgets({column.key: "" for column in self.columns}, trigger_change=trigger_change, metadata=metadata)

    def _add_row_widgets(self, row: dict[str, str], trigger_change: bool = True, metadata: object | None = None) -> None:
        frame = ttk.Frame(self.rows_frame)
        frame.grid(row=len(self.row_widgets), column=0, sticky="ew", pady=2)
        variables: dict[str, tk.StringVar] = {}
        widgets: dict[str, ttk.Widget] = {}
        for column_index, column in enumerate(self.columns):
            frame.columnconfigure(column_index, minsize=self._column_pixel_width(column))
            variable = tk.StringVar(value=row.get(column.key, ""))
            variable.trace_add("write", self._handle_change)
            variables[column.key] = variable
            if column.choices is not None:
                widget: ttk.Widget = ttk.Combobox(frame, textvariable=variable, values=column.choices, width=column.width)
            else:
                widget = ttk.Entry(frame, textvariable=variable, width=column.width)
            widget.grid(row=0, column=column_index, sticky="ew", padx=(0, 8))
            widgets[column.key] = widget
        ttk.Button(frame, text="Remove", command=lambda: self._remove_row(frame)).grid(
            row=0, column=len(self.columns), sticky="w"
        )
        frame.columnconfigure(len(self.columns), minsize=80)
        self.row_widgets.append(
            {
                "frame": frame,
                "variables": variables,
                "widgets": widgets,
                "metadata": metadata,
            }
        )
        if self.row_setup is not None:
            previous_suspend = self._suspend_callbacks
            self._suspend_callbacks = True
            try:
                self.row_setup(variables, widgets, metadata)
            finally:
                self._suspend_callbacks = previous_suspend
        self._refresh_scroll_region()
        if trigger_change:
            self._handle_change()

    def _remove_row(self, frame: ttk.Frame) -> None:
        for index, row_info in enumerate(self.row_widgets):
            row_frame: ttk.Frame = row_info["frame"]
            if row_frame is frame:
                row_frame.destroy()
                self.row_widgets.pop(index)
                break
        for row_index, row_info in enumerate(self.row_widgets):
            row_frame = row_info["frame"]
            row_frame.grid_configure(row=row_index)
        if not self.row_widgets:
            self.add_blank_row(trigger_change=False, metadata=None)
        self._refresh_scroll_region()
        self._handle_change()

    def _handle_change(self, *_args: object) -> None:
        if not self._suspend_callbacks:
            self.on_change()

    def _sync_scroll_region(self, _event: object | None = None) -> None:
        self.rows_canvas.configure(scrollregion=self.rows_canvas.bbox("all"))

    def _resize_canvas_window(self, event: tk.Event[tk.Misc]) -> None:
        self.rows_canvas.itemconfigure(self._rows_window, width=event.width)
        self._sync_scroll_region()

    def _refresh_scroll_region(self) -> None:
        self.after_idle(self._sync_scroll_region)

    def _bind_mousewheel(self, _event: object | None = None) -> None:
        self.rows_canvas.bind_all("<MouseWheel>", self._on_mousewheel)

    def _unbind_mousewheel(self, _event: object | None = None) -> None:
        self.rows_canvas.unbind_all("<MouseWheel>")

    def _on_mousewheel(self, event: tk.Event[tk.Misc]) -> None:
        if event.delta == 0:
            return
        self.rows_canvas.yview_scroll(int(-event.delta / 120), "units")

    def _column_pixel_width(self, column: ColumnSpec) -> int:
        pixels = max(88, column.width * 7)
        if column.choices is not None:
            pixels += 18
        return pixels


class PopTable(ttk.Frame):
    def __init__(
        self,
        master: tk.Misc,
        owner_tag: str,
        culture_choices: list[str],
        religion_choices: list[str],
        on_change: Callable[[], None],
        on_slider: Callable[[str, int, float], None],
    ) -> None:
        super().__init__(master)
        self.owner_tag = owner_tag
        self.culture_choices = culture_choices
        self.religion_choices = religion_choices
        self.on_change = on_change
        self.on_slider = on_slider
        self._suspend_callbacks = False
        self.row_widgets: list[dict[str, object]] = []

        header = ttk.Frame(self)
        header.grid(row=0, column=0, sticky="ew")
        headings = ["Culture", "Religion", "Size", "Share", "Adjust", ""]
        for column_index, title in enumerate(headings):
            ttk.Label(header, text=title).grid(row=0, column=column_index, sticky="w", padx=(0, 8))

        scroll_frame = ttk.Frame(self)
        scroll_frame.grid(row=1, column=0, sticky="nsew")
        scroll_frame.columnconfigure(0, weight=1)
        scroll_frame.rowconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)
        self.columnconfigure(0, weight=1)

        self.rows_canvas = tk.Canvas(
            scroll_frame,
            bg=DARK_ELEVATED,
            highlightthickness=1,
            highlightbackground=DARK_BORDER,
            highlightcolor=ACCENT,
            relief="flat",
            borderwidth=0,
            height=360,
        )
        self.rows_canvas.grid(row=0, column=0, sticky="nsew")
        self.rows_scrollbar = ttk.Scrollbar(scroll_frame, orient="vertical", command=self.rows_canvas.yview)
        self.rows_scrollbar.grid(row=0, column=1, sticky="ns", padx=(8, 0))
        self.rows_canvas.configure(yscrollcommand=self.rows_scrollbar.set)

        self.rows_frame = ttk.Frame(self.rows_canvas)
        self._rows_window = self.rows_canvas.create_window((0, 0), window=self.rows_frame, anchor="nw")
        self.rows_frame.bind("<Configure>", self._sync_scroll_region)
        self.rows_canvas.bind("<Configure>", self._resize_canvas_window)
        self.rows_canvas.bind("<Enter>", self._bind_mousewheel)
        self.rows_canvas.bind("<Leave>", self._unbind_mousewheel)
        self.rows_frame.bind("<Enter>", self._bind_mousewheel)
        self.rows_frame.bind("<Leave>", self._unbind_mousewheel)

        buttons = ttk.Frame(self)
        buttons.grid(row=2, column=0, sticky="w", pady=(6, 0))
        ttk.Button(buttons, text="Add pop row", command=self.add_blank_row).grid(row=0, column=0, sticky="w")

    def set_rows(self, rows: list[dict[str, str]]) -> None:
        self._suspend_callbacks = True
        try:
            for row_info in self.row_widgets:
                row_info["frame"].destroy()
            self.row_widgets.clear()
            if not rows:
                self.add_blank_row(trigger_change=False)
                self._refresh_scroll_region()
                return
            for row in rows:
                self._add_row_widgets(row, trigger_change=False)
            self._refresh_scroll_region()
        finally:
            self._suspend_callbacks = False

    def get_rows(self) -> list[dict[str, str]]:
        result: list[dict[str, str]] = []
        for row_info in self.row_widgets:
            variables = row_info["variables"]
            result.append({key: variables[key].get() for key in ("culture", "religion", "size")})
        return result

    def add_blank_row(self, trigger_change: bool = True) -> None:
        self._add_row_widgets({"culture": "", "religion": "", "size": ""}, trigger_change=trigger_change)

    def set_row_sizes(self, sizes_by_index: dict[int, int]) -> None:
        self._suspend_callbacks = True
        try:
            for index, row_info in enumerate(self.row_widgets):
                if index in sizes_by_index:
                    row_info["variables"]["size"].set(str(sizes_by_index[index]))
        finally:
            self._suspend_callbacks = False

    def update_share_display(self, total_population: int) -> None:
        self._suspend_callbacks = True
        try:
            for row_info in self.row_widgets:
                variables = row_info["variables"]
                share_var: tk.StringVar = row_info["share_var"]
                slider_var: tk.DoubleVar = row_info["slider_var"]
                slider: ttk.Scale = row_info["slider"]
                row = PopRow(
                    culture=variables["culture"].get(),
                    religion=variables["religion"].get(),
                    size=variables["size"].get(),
                )
                if is_blank_pop_row(row):
                    share_var.set("")
                    slider_var.set(0.0)
                    slider.state(["disabled"])
                    continue
                size = parse_int_string(row.size)
                if not row.culture.strip() or size is None or size < 0 or total_population <= 0:
                    share_var.set("invalid")
                    slider_var.set(0.0)
                    slider.state(["disabled"])
                    continue
                share = (size / total_population) * 100
                share_var.set(f"{share:.2f}%")
                slider_var.set(share)
                slider.state(["!disabled"])
        finally:
            self._suspend_callbacks = False

    def _add_row_widgets(self, row: dict[str, str], trigger_change: bool = True) -> None:
        frame = ttk.Frame(self.rows_frame)
        frame.grid(row=len(self.row_widgets), column=0, sticky="ew", pady=2)
        variables = {
            "culture": tk.StringVar(value=row.get("culture", "")),
            "religion": tk.StringVar(value=row.get("religion", "")),
            "size": tk.StringVar(value=row.get("size", "")),
        }
        for variable in variables.values():
            variable.trace_add("write", self._handle_change)

        culture_box = ttk.Combobox(frame, textvariable=variables["culture"], values=self.culture_choices, width=24)
        culture_box.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        religion_box = ttk.Combobox(frame, textvariable=variables["religion"], values=self.religion_choices, width=20)
        religion_box.grid(row=0, column=1, sticky="ew", padx=(0, 8))
        size_entry = ttk.Entry(frame, textvariable=variables["size"], width=12)
        size_entry.grid(row=0, column=2, sticky="ew", padx=(0, 8))

        share_var = tk.StringVar(value="")
        ttk.Label(frame, textvariable=share_var, width=10).grid(row=0, column=3, sticky="w", padx=(0, 8))

        slider_var = tk.DoubleVar(value=0.0)
        slider = ttk.Scale(
            frame,
            from_=0.0,
            to=100.0,
            orient=tk.HORIZONTAL,
            variable=slider_var,
            command=lambda _value, row_frame=frame: self._handle_slider(row_frame),
        )
        slider.grid(row=0, column=4, sticky="ew", padx=(0, 8))
        frame.columnconfigure(4, weight=1)

        ttk.Button(frame, text="Remove", command=lambda: self._remove_row(frame)).grid(row=0, column=5, sticky="w")
        self.row_widgets.append(
            {
                "frame": frame,
                "variables": variables,
                "share_var": share_var,
                "slider_var": slider_var,
                "slider": slider,
            }
        )
        self._refresh_scroll_region()
        if trigger_change:
            self._handle_change()

    def _remove_row(self, frame: ttk.Frame) -> None:
        for index, row_info in enumerate(self.row_widgets):
            if row_info["frame"] is frame:
                row_info["frame"].destroy()
                self.row_widgets.pop(index)
                break
        for row_index, row_info in enumerate(self.row_widgets):
            row_info["frame"].grid_configure(row=row_index)
        if not self.row_widgets:
            self.add_blank_row(trigger_change=False)
        self._refresh_scroll_region()
        self._handle_change()

    def _handle_change(self, *_args: object) -> None:
        if not self._suspend_callbacks:
            self.on_change()

    def _handle_slider(self, frame: ttk.Frame) -> None:
        if self._suspend_callbacks:
            return
        for index, row_info in enumerate(self.row_widgets):
            if row_info["frame"] is frame:
                slider_var: tk.DoubleVar = row_info["slider_var"]
                self.on_slider(self.owner_tag, index, slider_var.get())
                return

    def _sync_scroll_region(self, _event: object | None = None) -> None:
        self.rows_canvas.configure(scrollregion=self.rows_canvas.bbox("all"))

    def _resize_canvas_window(self, event: tk.Event[tk.Misc]) -> None:
        self.rows_canvas.itemconfigure(self._rows_window, width=event.width)
        self._sync_scroll_region()

    def _refresh_scroll_region(self) -> None:
        self.after_idle(self._sync_scroll_region)

    def _bind_mousewheel(self, _event: object | None = None) -> None:
        self.rows_canvas.bind_all("<MouseWheel>", self._on_mousewheel)

    def _unbind_mousewheel(self, _event: object | None = None) -> None:
        self.rows_canvas.unbind_all("<MouseWheel>")

    def _on_mousewheel(self, event: tk.Event[tk.Misc]) -> None:
        if event.delta == 0:
            return
        self.rows_canvas.yview_scroll(int(-event.delta / 120), "units")


class Vic3StateEditorApp:
    def __init__(self, root: tk.Tk, repository: ModRepository) -> None:
        self.root = root
        self.repo = repository
        self.current_state_id: str | None = None
        self.filtered_state_ids: list[str] = []
        self.loading_ui = False

        root.title("Victoria 3 State Editor")
        root.geometry("1400x900")
        root.protocol("WM_DELETE_WINDOW", self.on_close)
        root.bind("<Control-s>", lambda _event: self.save_current())
        root.bind("<Control-S>", lambda _event: self.save_all())
        self._apply_dark_theme()

        self.show_all_var = tk.BooleanVar(value=False)
        self.search_var = tk.StringVar()
        self.search_var.trace_add("write", lambda *_args: self.refresh_state_list())
        self.status_var = tk.StringVar(value="Ready")
        self.slider_adjusting = False

        self.state_title_var = tk.StringVar(value="Select a state")
        self.source_var = tk.StringVar(value="")
        self.warning_var = tk.StringVar(value="")
        self.summary_var = tk.StringVar(value="")
        self.arable_land_var = tk.StringVar()
        self.arable_land_var.trace_add("write", lambda *_args: self._mark_dirty())

        self.owner_tables: dict[str, PopTable] = {}
        self.owner_total_vars: dict[str, tk.StringVar] = {}
        self.owner_notebook: ttk.Notebook | None = None
        self.aggregate_text: tk.Text | None = None
        self.homelands_table: EditableTable | None = None
        self.arable_table: EditableTable | None = None
        self.capped_table: EditableTable | None = None
        self.discoverable_table: EditableTable | None = None
        self.buildings_table: EditableTable | None = None
        self.resources_canvas: tk.Canvas | None = None
        self.resources_content: ttk.Frame | None = None
        self._resources_window: int | None = None
        self.state_listbox: tk.Listbox | None = None

        self._build_ui()
        self.refresh_state_list()
        if self.filtered_state_ids:
            self.select_state(self.filtered_state_ids[0])

    def _apply_dark_theme(self) -> None:
        style = ttk.Style(self.root)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass

        self.root.configure(bg=DARK_BG)
        self.root.option_add("*TCombobox*Listbox*Background", DARK_ELEVATED)
        self.root.option_add("*TCombobox*Listbox*Foreground", DARK_FG)
        self.root.option_add("*TCombobox*Listbox*selectBackground", ACCENT)
        self.root.option_add("*TCombobox*Listbox*selectForeground", DARK_FG)

        style.configure(".", background=DARK_PANEL, foreground=DARK_FG)
        style.configure("TFrame", background=DARK_BG)
        style.configure("TLabel", background=DARK_BG, foreground=DARK_FG)
        style.configure("TCheckbutton", background=DARK_BG, foreground=DARK_FG)
        style.map("TCheckbutton", background=[("active", DARK_BG)], foreground=[("disabled", DARK_MUTED)])
        style.configure(
            "TButton",
            background=DARK_PANEL,
            foreground=DARK_FG,
            bordercolor=DARK_BORDER,
            lightcolor=DARK_BORDER,
            darkcolor=DARK_BORDER,
            focusthickness=1,
            focuscolor=ACCENT,
            padding=(10, 6),
        )
        style.map(
            "TButton",
            background=[("active", DARK_ELEVATED), ("pressed", ACCENT)],
            foreground=[("disabled", DARK_MUTED)],
        )
        style.configure(
            "TEntry",
            fieldbackground=DARK_ELEVATED,
            foreground=DARK_FG,
            bordercolor=DARK_BORDER,
            lightcolor=DARK_BORDER,
            darkcolor=DARK_BORDER,
            insertcolor=DARK_FG,
        )
        style.configure(
            "TCombobox",
            fieldbackground=DARK_ELEVATED,
            background=DARK_PANEL,
            foreground=DARK_FG,
            arrowcolor=DARK_FG,
            bordercolor=DARK_BORDER,
            lightcolor=DARK_BORDER,
            darkcolor=DARK_BORDER,
            insertcolor=DARK_FG,
        )
        style.map(
            "TCombobox",
            fieldbackground=[("readonly", DARK_ELEVATED)],
            background=[("active", DARK_PANEL)],
            foreground=[("readonly", DARK_FG)],
            arrowcolor=[("active", ACCENT_ACTIVE)],
        )
        style.configure("TPanedwindow", background=DARK_BG)
        style.configure("TNotebook", background=DARK_BG, borderwidth=0)
        style.configure(
            "TNotebook.Tab",
            background=DARK_PANEL,
            foreground=DARK_FG,
            bordercolor=DARK_BORDER,
            lightcolor=DARK_BORDER,
            darkcolor=DARK_BORDER,
            padding=(12, 6),
        )
        style.map(
            "TNotebook.Tab",
            background=[("selected", ACCENT), ("active", DARK_ELEVATED)],
            foreground=[("selected", DARK_FG)],
        )

    def _build_ui(self) -> None:
        outer = ttk.Panedwindow(self.root, orient=tk.HORIZONTAL)
        outer.pack(fill=tk.BOTH, expand=True)

        left = ttk.Frame(outer, padding=12)
        outer.add(left, weight=1)

        ttk.Label(left, text="States").grid(row=0, column=0, sticky="w")
        ttk.Entry(left, textvariable=self.search_var).grid(row=1, column=0, sticky="ew", pady=(4, 8))
        ttk.Checkbutton(left, text="Show all loaded states", variable=self.show_all_var, command=self.refresh_state_list).grid(
            row=2, column=0, sticky="w", pady=(0, 8)
        )
        self.state_listbox = tk.Listbox(
            left,
            exportselection=False,
            bg=DARK_ELEVATED,
            fg=DARK_FG,
            selectbackground=ACCENT,
            selectforeground=DARK_FG,
            highlightthickness=1,
            highlightbackground=DARK_BORDER,
            highlightcolor=ACCENT,
            relief="flat",
            activestyle="none",
        )
        self.state_listbox.grid(row=3, column=0, sticky="nsew")
        self.state_listbox.bind("<<ListboxSelect>>", self._on_state_list_select)
        left.columnconfigure(0, weight=1)
        left.rowconfigure(3, weight=1)

        right = ttk.Frame(outer, padding=12)
        outer.add(right, weight=4)

        header = ttk.Frame(right)
        header.grid(row=0, column=0, sticky="ew")
        ttk.Label(header, textvariable=self.state_title_var, font=("", 16, "bold")).grid(row=0, column=0, sticky="w")
        button_bar = ttk.Frame(header)
        button_bar.grid(row=0, column=1, sticky="e")
        ttk.Button(button_bar, text="Save Current", command=self.save_current).grid(row=0, column=0, padx=(0, 8))
        ttk.Button(button_bar, text="Save All Dirty", command=self.save_all).grid(row=0, column=1, padx=(0, 8))
        ttk.Button(button_bar, text="Open Pop File", command=self._open_pop_file).grid(row=0, column=2, padx=(0, 8))
        ttk.Button(button_bar, text="Reload From Disk", command=self.reload_repository).grid(row=0, column=3)
        header.columnconfigure(0, weight=1)

        ttk.Label(right, textvariable=self.source_var).grid(row=1, column=0, sticky="w", pady=(6, 0))
        ttk.Label(right, textvariable=self.warning_var, foreground=WARNING_FG, wraplength=1000).grid(
            row=2, column=0, sticky="w", pady=(4, 8)
        )

        notebook = ttk.Notebook(right)
        notebook.grid(row=3, column=0, sticky="nsew")
        right.columnconfigure(0, weight=1)
        right.rowconfigure(3, weight=1)

        population_tab = ttk.Frame(notebook, padding=8)
        notebook.add(population_tab, text="Population")
        self.owner_notebook = ttk.Notebook(population_tab)
        self.owner_notebook.grid(row=0, column=0, sticky="nsew")
        population_tab.columnconfigure(0, weight=1)
        population_tab.rowconfigure(0, weight=1)
        ttk.Label(population_tab, text="Aggregate summary").grid(row=1, column=0, sticky="w", pady=(12, 4))
        self.aggregate_text = tk.Text(
            population_tab,
            height=12,
            wrap="word",
            bg=DARK_ELEVATED,
            fg=DARK_FG,
            insertbackground=DARK_FG,
            selectbackground=ACCENT,
            selectforeground=DARK_FG,
            highlightthickness=1,
            highlightbackground=DARK_BORDER,
            highlightcolor=ACCENT,
            relief="flat",
        )
        self.aggregate_text.grid(row=2, column=0, sticky="nsew")

        homelands_tab = ttk.Frame(notebook, padding=8)
        notebook.add(homelands_tab, text="Homelands")
        homelands_tab.columnconfigure(0, weight=1)
        homelands_tab.rowconfigure(1, weight=1)
        ttk.Label(
            homelands_tab,
            text=(
                "One row per add_homeland line in the state-history block. "
                "Choose the cultures that should treat this state as a homeland."
            ),
            wraplength=1080,
        ).grid(row=0, column=0, sticky="w", pady=(0, 8))
        self.homelands_table = EditableTable(
            homelands_tab,
            columns=[ColumnSpec("culture", "Culture", 28, self.repo.culture_choices)],
            on_change=self._mark_dirty,
            add_label="Add homeland",
            canvas_height=220,
        )
        self.homelands_table.grid(row=1, column=0, sticky="nsew")

        resources_tab = ttk.Frame(notebook, padding=8)
        notebook.add(resources_tab, text="Resources")
        resources_tab.columnconfigure(0, weight=1)
        resources_tab.rowconfigure(0, weight=1)

        resources_scroll = ttk.Frame(resources_tab)
        resources_scroll.grid(row=0, column=0, sticky="nsew")
        resources_scroll.columnconfigure(0, weight=1)
        resources_scroll.rowconfigure(0, weight=1)

        self.resources_canvas = tk.Canvas(
            resources_scroll,
            bg=DARK_BG,
            highlightthickness=0,
            borderwidth=0,
            relief="flat",
        )
        self.resources_canvas.grid(row=0, column=0, sticky="nsew")
        resources_scrollbar = ttk.Scrollbar(resources_scroll, orient="vertical", command=self.resources_canvas.yview)
        resources_scrollbar.grid(row=0, column=1, sticky="ns", padx=(8, 0))
        self.resources_canvas.configure(yscrollcommand=resources_scrollbar.set)

        self.resources_content = ttk.Frame(self.resources_canvas)
        self._resources_window = self.resources_canvas.create_window((0, 0), window=self.resources_content, anchor="nw")
        self.resources_content.bind("<Configure>", self._sync_resources_scroll_region)
        self.resources_canvas.bind("<Configure>", self._resize_resources_canvas_window)

        arable_section = ttk.LabelFrame(self.resources_content, text="Arable Resources", padding=10)
        arable_section.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        arable_section.columnconfigure(0, weight=1)
        land_row = ttk.Frame(arable_section)
        land_row.grid(row=0, column=0, sticky="w", pady=(0, 10))
        ttk.Label(land_row, text="Arable land").grid(row=0, column=0, sticky="w")
        ttk.Entry(land_row, textvariable=self.arable_land_var, width=12).grid(row=0, column=1, sticky="w", padx=(8, 0))

        self.arable_table = EditableTable(
            arable_section,
            columns=[ColumnSpec("resource", "Arable Resource", 28, self.repo.arable_resource_choices)],
            on_change=self._mark_dirty,
            add_label="Add arable resource",
            canvas_height=120,
        )
        self.arable_table.grid(row=1, column=0, sticky="ew")

        capped_section = ttk.LabelFrame(self.resources_content, text="Capped Resources", padding=10)
        capped_section.grid(row=1, column=0, sticky="ew", pady=(0, 10))
        capped_section.columnconfigure(0, weight=1)
        self.capped_table = EditableTable(
            capped_section,
            columns=[
                ColumnSpec("resource", "Capped Resource", 28, self.repo.capped_resource_choices),
                ColumnSpec("amount", "Max Level", 10),
            ],
            on_change=self._mark_dirty,
            add_label="Add capped resource",
            canvas_height=150,
        )
        self.capped_table.grid(row=0, column=0, sticky="ew")

        discoverable_section = ttk.LabelFrame(self.resources_content, text="Discoverable Resources", padding=10)
        discoverable_section.grid(row=2, column=0, sticky="ew")
        discoverable_section.columnconfigure(0, weight=1)
        self.discoverable_table = EditableTable(
            discoverable_section,
            columns=[
                ColumnSpec("resource", "Discoverable Resource", 28, self.repo.discoverable_resource_choices),
                ColumnSpec("amount", "Amount", 10),
                ColumnSpec("depleted_type", "Depleted Type", 28, self.repo.discoverable_depleted_type_choices),
            ],
            on_change=self._mark_dirty,
            add_label="Add discoverable resource",
            canvas_height=170,
        )
        self.discoverable_table.grid(row=0, column=0, sticky="ew")
        self.resources_content.columnconfigure(0, weight=1)

        buildings_tab = ttk.Frame(notebook, padding=8)
        notebook.add(buildings_tab, text="Buildings")
        buildings_tab.columnconfigure(0, weight=1)
        buildings_tab.rowconfigure(1, weight=1)
        ttk.Label(
            buildings_tab,
            text=(
                "One row per create_building block. State Owner chooses the region_state slice. "
                "Levels is the total building level count. Owner Type chooses how those levels are owned. "
                "Owner Location is only used for Financial District and Manor House ownership, and defaults to the current state. "
                "Unsupported rows stay available as Preserve."
            ),
            wraplength=1080,
        ).grid(row=0, column=0, sticky="w", pady=(0, 8))
        self.buildings_table = EditableTable(
            buildings_tab,
            columns=[
                ColumnSpec("owner_tag", "State Owner", 10, []),
                ColumnSpec("building", "Building", 26, self.repo.building_choices),
                ColumnSpec("levels", "Levels", 8),
                ColumnSpec("owner_kind", "Owner Type", 20, BUILDING_OWNER_KIND_CHOICES),
                ColumnSpec("owner_location", "Owner Location", 22, sorted(self.repo.state_records)),
            ],
            on_change=self._mark_dirty,
            add_label="Add building",
            canvas_height=420,
            row_setup=self._configure_building_table_row,
        )
        self.buildings_table.grid(row=1, column=0, sticky="nsew")

        ttk.Label(right, textvariable=self.summary_var, wraplength=1000).grid(row=4, column=0, sticky="w", pady=(10, 0))
        ttk.Label(right, textvariable=self.status_var).grid(row=5, column=0, sticky="w", pady=(8, 0))

    def refresh_state_list(self) -> None:
        if self.state_listbox is None:
            return
        previous = self.current_state_id
        self.state_listbox.delete(0, tk.END)
        query = self.search_var.get().strip().lower()
        records = sorted(self.repo.state_records.values(), key=lambda record: (record.display_name.lower(), record.state_id))
        filtered: list[str] = []
        for record in records:
            if not self.show_all_var.get() and not record.canada_focus:
                continue
            haystack = f"{record.display_name} {record.state_id}".lower()
            if query and query not in haystack:
                continue
            filtered.append(record.state_id)
            marker = "*" if record.dirty else ""
            label = f"{record.display_name} [{record.state_id}]{marker}"
            self.state_listbox.insert(tk.END, label)
        self.filtered_state_ids = filtered
        if previous in filtered:
            index = filtered.index(previous)
            self.state_listbox.selection_set(index)
            self.state_listbox.see(index)
        elif filtered:
            self.select_state(filtered[0])

    def _on_state_list_select(self, _event: object) -> None:
        if self.state_listbox is None:
            return
        selection = self.state_listbox.curselection()
        if not selection:
            return
        state_id = self.filtered_state_ids[selection[0]]
        self.select_state(state_id)

    def select_state(self, state_id: str) -> None:
        self._stash_current_state()
        self.current_state_id = state_id
        record = self.repo.state_records[state_id]
        self._show_state(record)
        if self.state_listbox is not None and state_id in self.filtered_state_ids:
            index = self.filtered_state_ids.index(state_id)
            self.state_listbox.selection_clear(0, tk.END)
            self.state_listbox.selection_set(index)
            self.state_listbox.see(index)

    def _show_state(self, record: StateRecord) -> None:
        self.loading_ui = True
        try:
            self.state_title_var.set(f"{record.display_name} ({record.state_id})")
            self.source_var.set(
                " | ".join(
                    [
                        f"State regions: {record.region_source.name if record.region_source else 'missing'}",
                        f"Pops: {record.pop_source.name if record.pop_source else C2C_HISTORY_POPS_FILENAME}",
                        f"Buildings: {record.building_source.name if record.building_source else C2C_HISTORY_BUILDINGS_FILENAME}",
                        f"Ownership: {record.ownership_source.name if record.ownership_source else C2C_HISTORY_STATES_FILENAME}",
                    ]
                )
            )
            self.warning_var.set("Warnings: " + " ".join(record.warnings) if record.warnings else "")
            self.summary_var.set(self._build_owner_summary(record))
            self.arable_land_var.set(record.arable_land)
            if self.homelands_table is not None:
                self.homelands_table.set_rows(
                    [{"culture": culture} for culture in record.homelands] or [{"culture": ""}]
                )
            if self.arable_table is not None:
                self.arable_table.set_rows([{"resource": value} for value in record.arable_resources] or [{"resource": ""}])
            if self.capped_table is not None:
                self.capped_table.set_rows(
                    [{"resource": row.resource, "amount": row.amount} for row in record.capped_resources]
                    or [{"resource": "", "amount": ""}]
                )
            if self.discoverable_table is not None:
                self.discoverable_table.set_rows(
                    [
                        {
                            "resource": row.resource,
                            "amount": row.amount,
                            "depleted_type": row.depleted_type,
                        }
                        for row in record.discoverable_resources
                    ]
                    or [{"resource": "", "amount": "", "depleted_type": ""}]
                )
            if self.buildings_table is not None:
                self.buildings_table.set_column_choices("owner_tag", record.editable_owner_tags())
                self.buildings_table.set_rows(
                    [self._building_row_to_table_dict(record, row) for row in record.buildings]
                    or [self._blank_building_row_data(record)],
                    row_metadata=list(record.buildings) or [None],
                )
            self._rebuild_owner_tabs(record)
            self._refresh_aggregate_summary(record)
            self.status_var.set(f"Loaded {record.display_name}")
        finally:
            self.loading_ui = False

    def _blank_building_row_data(self, record: StateRecord) -> dict[str, str]:
        owner_tags = record.editable_owner_tags()
        default_owner = owner_tags[0] if len(owner_tags) == 1 else ""
        return {
            "owner_tag": default_owner,
            "building": "",
            "levels": "",
            "owner_kind": BUILDING_OWNER_KIND_NATIONAL,
            "owner_location": "",
        }

    def _building_row_to_table_dict(self, record: StateRecord, row: BuildingRow) -> dict[str, str]:
        owner_kind = infer_building_owner_kind(record.state_id, row)
        owner_location = row.ownership_region if owner_kind in {
            BUILDING_OWNER_KIND_FINANCIAL_DISTRICT,
            BUILDING_OWNER_KIND_MANOR_HOUSE,
        } else ""
        return {
            "owner_tag": row.owner_tag,
            "building": row.building,
            "levels": building_total_levels(row),
            "owner_kind": owner_kind,
            "owner_location": owner_location,
        }

    def _building_owner_kind_uses_location(self, owner_kind: str) -> bool:
        return owner_kind in {
            BUILDING_OWNER_KIND_FINANCIAL_DISTRICT,
            BUILDING_OWNER_KIND_MANOR_HOUSE,
        }

    def _default_building_owner_location(self, variables: dict[str, tk.StringVar]) -> None:
        if not self.current_state_id:
            return
        owner_kind = variables["owner_kind"].get().strip()
        owner_location = variables["owner_location"].get().strip()
        if self._building_owner_kind_uses_location(owner_kind) and not owner_location:
            variables["owner_location"].set(self.current_state_id)

    def _configure_building_table_row(
        self,
        variables: dict[str, tk.StringVar],
        _widgets: dict[str, ttk.Widget],
        _metadata: object | None,
    ) -> None:
        def sync_owner_location(*_args: object) -> None:
            self._default_building_owner_location(variables)

        variables["owner_kind"].trace_add("write", sync_owner_location)
        self._default_building_owner_location(variables)

    def _building_row_from_table(
        self,
        record: StateRecord,
        row: dict[str, str],
        metadata: object | None,
    ) -> BuildingRow:
        template = metadata if isinstance(metadata, BuildingRow) else BuildingRow()
        owner_tag = row.get("owner_tag", "").strip()
        building_id = row.get("building", "").strip()
        total_levels = row.get("levels", "").strip()
        owner_kind = row.get("owner_kind", "").strip()
        owner_location = row.get("owner_location", "").strip().strip('"')
        if self._building_owner_kind_uses_location(owner_kind) and not owner_location:
            owner_location = record.state_id

        if not building_id and not total_levels and not owner_location:
            return BuildingRow()

        if owner_kind == BUILDING_OWNER_KIND_PRESERVE and isinstance(metadata, BuildingRow):
            return BuildingRow(
                owner_tag=template.owner_tag,
                building=template.building,
                level=template.level,
                reserves=template.reserves,
                ownership_mode=template.ownership_mode,
                ownership_country=template.ownership_country,
                ownership_levels=template.ownership_levels,
                ownership_building_type=template.ownership_building_type,
                ownership_region=template.ownership_region,
                template_entries=list(template.template_entries),
                ownership_template_entries=list(template.ownership_template_entries),
                preserved_add_ownership_raw=template.preserved_add_ownership_raw,
            )

        converted = BuildingRow(
            owner_tag=owner_tag,
            building=building_id,
            level="",
            reserves=template.reserves.strip() or "1",
            ownership_mode="",
            ownership_country="",
            ownership_levels="",
            ownership_building_type="",
            ownership_region="",
            template_entries=list(template.template_entries),
            ownership_template_entries=list(template.ownership_template_entries),
            preserved_add_ownership_raw=template.preserved_add_ownership_raw,
        )

        if owner_kind == BUILDING_OWNER_KIND_NATIONAL:
            if template.ownership_mode == "" and template.level.strip() and template.reserves.strip():
                converted.level = total_levels
            else:
                converted.ownership_mode = "country"
                converted.ownership_country = owner_tag
                converted.ownership_levels = total_levels
        elif owner_kind == BUILDING_OWNER_KIND_LOCAL_WORKFORCE:
            converted.ownership_mode = "building"
            converted.ownership_country = owner_tag
            converted.ownership_levels = total_levels
            converted.ownership_building_type = building_id
            converted.ownership_region = record.state_id
        elif owner_kind == BUILDING_OWNER_KIND_FINANCIAL_DISTRICT:
            converted.ownership_mode = "building"
            converted.ownership_country = owner_tag
            converted.ownership_levels = total_levels
            converted.ownership_building_type = "building_financial_district"
            converted.ownership_region = owner_location
        elif owner_kind == BUILDING_OWNER_KIND_MANOR_HOUSE:
            converted.ownership_mode = "building"
            converted.ownership_country = owner_tag
            converted.ownership_levels = total_levels
            converted.ownership_building_type = "building_manor_house"
            converted.ownership_region = owner_location
        else:
            converted.ownership_mode = "preserve"

        return converted

    def _build_owner_summary(self, record: StateRecord) -> str:
        parts = []
        ownership_tags = {owner.tag for owner in record.owners}
        for owner in record.owners:
            total = owner_population_total(record.pops_by_owner.get(owner.tag, []))
            total_text = str(total) if total is not None else "invalid"
            parts.append(f"{owner.tag}: {owner.province_count} provinces, {total_text} pops")
        for owner_tag in record.pops_by_owner:
            if owner_tag not in ownership_tags:
                total = owner_population_total(record.pops_by_owner.get(owner_tag, []))
                total_text = str(total) if total is not None else "invalid"
                parts.append(f"{owner_tag}: pop-only owner, {total_text} pops")
        return "Owners: " + " | ".join(parts) if parts else "No ownership slices found."

    def _sync_resources_scroll_region(self, _event: object | None = None) -> None:
        if self.resources_canvas is None:
            return
        self.resources_canvas.configure(scrollregion=self.resources_canvas.bbox("all"))

    def _resize_resources_canvas_window(self, event: tk.Event[tk.Misc]) -> None:
        if self.resources_canvas is None or self._resources_window is None:
            return
        self.resources_canvas.itemconfigure(self._resources_window, width=event.width)
        self._sync_resources_scroll_region()

    def _rebuild_owner_tabs(self, record: StateRecord) -> None:
        assert self.owner_notebook is not None
        for child in self.owner_notebook.winfo_children():
            child.destroy()
        self.owner_tables.clear()
        self.owner_total_vars.clear()

        ownership_tags = {owner.tag for owner in record.owners}
        for owner_tag in record.editable_owner_tags():
            frame = ttk.Frame(self.owner_notebook, padding=8)
            total_var = tk.StringVar()
            owner_label = owner_tag
            if owner_tag not in ownership_tags:
                owner_label += " (pop only)"
            ttk.Label(frame, textvariable=total_var).grid(row=0, column=0, sticky="w", pady=(0, 6))
            table = PopTable(
                frame,
                owner_tag=owner_tag,
                culture_choices=self.repo.culture_choices,
                religion_choices=self.repo.religion_choices,
                on_change=self._mark_dirty,
                on_slider=self._on_pop_slider,
            )
            table.grid(row=1, column=0, sticky="nsew")
            frame.columnconfigure(0, weight=1)
            frame.rowconfigure(1, weight=1)
            table.set_rows(
                [
                    {"culture": row.culture, "religion": row.religion, "size": row.size}
                    for row in record.pops_by_owner.get(owner_tag, [])
                ]
                or [{"culture": "", "religion": "", "size": ""}]
            )
            self.owner_notebook.add(frame, text=owner_label)
            self.owner_tables[owner_tag] = table
            self.owner_total_vars[owner_tag] = total_var
        self._update_owner_totals()

    def _refresh_aggregate_summary(self, record: StateRecord) -> None:
        if self.aggregate_text is None:
            return
        summary = self._build_aggregate_summary(record)
        self.aggregate_text.configure(state="normal")
        self.aggregate_text.delete("1.0", tk.END)
        self.aggregate_text.insert("1.0", summary)
        self.aggregate_text.configure(state="disabled")

    def _build_aggregate_summary(self, record: StateRecord) -> str:
        culture_totals: Counter[str] = Counter()
        religion_totals: Counter[str] = Counter()
        total_population = 0
        invalid_rows = False
        for owner_tag in record.editable_owner_tags():
            rows = record.pops_by_owner.get(owner_tag, [])
            for row in rows:
                culture = row.culture.strip()
                religion = row.religion.strip() or "(blank)"
                size = parse_int_string(row.size)
                if not culture and row.size.strip() == "" and row.religion.strip() == "":
                    continue
                if size is None:
                    invalid_rows = True
                    continue
                total_population += size
                if culture:
                    culture_totals[culture] += size
                religion_totals[religion] += size
        lines = [f"Total population: {total_population}"]
        if invalid_rows:
            lines.append("Invalid size values are present in one or more owner tabs.")
        lines.append("")
        lines.append("Culture totals:")
        for culture, value in culture_totals.most_common():
            lines.append(f"  {culture}: {value}")
        lines.append("")
        lines.append("Religion totals:")
        for religion, value in religion_totals.most_common():
            lines.append(f"  {religion}: {value}")
        return "\n".join(lines)

    def _stash_current_state(self) -> None:
        if self.current_state_id is None or self.loading_ui:
            return
        record = self.repo.state_records[self.current_state_id]
        record.arable_land = self.arable_land_var.get()
        if self.homelands_table is not None:
            record.homelands = [row["culture"] for row in self.homelands_table.get_rows()]
        if self.arable_table is not None:
            record.arable_resources = [row["resource"] for row in self.arable_table.get_rows()]
        if self.capped_table is not None:
            record.capped_resources = [
                ResourceCountRow(row["resource"], row["amount"]) for row in self.capped_table.get_rows()
            ]
        if self.discoverable_table is not None:
            record.discoverable_resources = [
                DiscoverableResourceRow(row["resource"], row["amount"], row["depleted_type"])
                for row in self.discoverable_table.get_rows()
            ]
        for owner_tag, table in self.owner_tables.items():
            record.pops_by_owner[owner_tag] = [
                PopRow(row["culture"], row["religion"], row["size"]) for row in table.get_rows()
            ]
        if self.buildings_table is not None:
            record.buildings = [
                self._building_row_from_table(record, row, metadata)
                for row, metadata in self.buildings_table.get_rows_with_metadata()
            ]
        self.summary_var.set(self._build_owner_summary(record))
        self._refresh_aggregate_summary(record)
        self._update_owner_totals()

    def _mark_dirty(self) -> None:
        if self.loading_ui or self.current_state_id is None:
            return
        self._stash_current_state()
        record = self.repo.state_records[self.current_state_id]
        record.dirty = True
        self.refresh_state_list()
        self.status_var.set(f"Edited {record.display_name}")

    def _update_owner_totals(self) -> None:
        if self.current_state_id is None:
            return
        record = self.repo.state_records[self.current_state_id]
        state_total = 0
        for owner_tag, table in self.owner_tables.items():
            rows = [PopRow(row["culture"], row["religion"], row["size"]) for row in table.get_rows()]
            total = owner_population_total(rows)
            if total is None:
                text = f"{owner_tag} total: invalid size"
            else:
                text = f"{owner_tag} total: {total}"
                state_total += total
            self.owner_total_vars[owner_tag].set(text)
        for table in self.owner_tables.values():
            table.update_share_display(state_total)
        self.summary_var.set(self._build_owner_summary(record))

    def _current_record(self) -> StateRecord | None:
        if self.current_state_id is None:
            return None
        return self.repo.state_records[self.current_state_id]

    def _on_pop_slider(self, owner_tag: str, row_index: int, target_percent: float) -> None:
        if self.loading_ui or self.slider_adjusting:
            return
        record = self._current_record()
        if record is None:
            return

        row_refs: list[tuple[str, int, PopRow, int]] = []
        target_ref: tuple[str, int, PopRow, int] | None = None
        for current_owner, table in self.owner_tables.items():
            for current_index, row_data in enumerate(table.get_rows()):
                row = PopRow(row_data["culture"], row_data["religion"], row_data["size"])
                if is_blank_pop_row(row):
                    continue
                size = parse_int_string(row.size)
                if not row.culture.strip() or size is None or size < 0:
                    self.status_var.set("Fill in valid culture/size values before using pop share sliders")
                    return
                ref = (current_owner, current_index, row, size)
                row_refs.append(ref)
                if current_owner == owner_tag and current_index == row_index:
                    target_ref = ref

        if target_ref is None:
            return

        total_population = sum(ref[3] for ref in row_refs)
        if total_population <= 0:
            return

        target_size = max(0, min(total_population, int(round(total_population * target_percent / 100.0))))
        other_refs = [ref for ref in row_refs if ref is not target_ref]
        new_sizes: dict[str, dict[int, int]] = defaultdict(dict)
        new_sizes[owner_tag][row_index] = target_size

        if other_refs:
            remainder = total_population - target_size
            weights = [ref[3] for ref in other_refs]
            allocations = allocate_proportional(remainder, weights)
            for allocation, ref in zip(allocations, other_refs):
                new_sizes[ref[0]][ref[1]] = allocation
        else:
            new_sizes[owner_tag][row_index] = total_population

        self.slider_adjusting = True
        try:
            for current_owner, table in self.owner_tables.items():
                table.set_row_sizes(new_sizes.get(current_owner, {}))
        finally:
            self.slider_adjusting = False

        self._mark_dirty()
        row_label = target_ref[2].culture
        if target_ref[2].religion.strip():
            row_label += f" / {target_ref[2].religion}"
        self.status_var.set(f"Adjusted {row_label} to {target_percent:.2f}% of {record.display_name}")

    def _open_pop_file(self) -> None:
        record = self._current_record()
        if record is None:
            return
        if record.pop_source is None or not record.pop_source.exists():
            messagebox.showinfo("No pop file yet", "This state does not have an existing population file yet.")
            return

        notepad_plus_plus = self._find_notepad_plus_plus()
        try:
            if notepad_plus_plus is not None:
                subprocess.Popen([str(notepad_plus_plus), str(record.pop_source)])
            elif hasattr(os, "startfile"):
                os.startfile(str(record.pop_source))
            else:
                subprocess.Popen(["xdg-open", str(record.pop_source)])
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("Open failed", str(exc))

    def _find_notepad_plus_plus(self) -> Path | None:
        candidates = [
            shutil.which("notepad++"),
            r"C:\Program Files\Notepad++\notepad++.exe",
            r"C:\Program Files (x86)\Notepad++\notepad++.exe",
            str(Path.home() / "AppData" / "Local" / "Programs" / "Notepad++" / "notepad++.exe"),
        ]
        for candidate in candidates:
            if not candidate:
                continue
            path = Path(candidate)
            if path.exists():
                return path
        return None

    def save_current(self) -> None:
        if self.current_state_id is None:
            return
        self._stash_current_state()
        record = self.repo.state_records[self.current_state_id]
        try:
            self.repo.save_state(record)
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("Save failed", str(exc))
            self.status_var.set(f"Save failed for {record.display_name}")
            return
        record.dirty = False
        self._show_state(record)
        self.refresh_state_list()
        self.status_var.set(f"Saved {record.display_name}")

    def save_all(self) -> None:
        self._stash_current_state()
        dirty_records = [record for record in self.repo.state_records.values() if record.dirty]
        if not dirty_records:
            self.status_var.set("No dirty states to save")
            return
        try:
            for record in dirty_records:
                self.repo.save_state(record)
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("Save failed", str(exc))
            self.status_var.set("Save all failed")
            return
        for record in dirty_records:
            record.dirty = False
        if self.current_state_id is not None:
            self._show_state(self.repo.state_records[self.current_state_id])
        self.refresh_state_list()
        self.status_var.set(f"Saved {len(dirty_records)} states")

    def reload_repository(self, reselect_state: str | None = None, announce: bool = True) -> None:
        dirty_records = [record.display_name for record in self.repo.state_records.values() if record.dirty]
        if announce and dirty_records:
            proceed = messagebox.askyesno(
                "Discard unsaved edits?",
                "Reloading from disk will discard unsaved changes in the current session. Continue?",
            )
            if not proceed:
                return
        self.repo.load()
        self.status_var.set("Reloaded from disk")
        self.refresh_state_list()
        target = reselect_state or self.current_state_id
        if target and target in self.repo.state_records:
            self.select_state(target)

    def on_close(self) -> None:
        self._stash_current_state()
        dirty_count = sum(1 for record in self.repo.state_records.values() if record.dirty)
        if dirty_count:
            proceed = messagebox.askyesno(
                "Unsaved changes",
                f"There are unsaved edits in {dirty_count} state(s). Close anyway?",
            )
            if not proceed:
                return
        self.root.destroy()


def default_repo_root() -> Path:
    script_dir = Path(__file__).resolve().parent
    for candidate in [Path.cwd(), script_dir.parent]:
        if (candidate / "mod").is_dir() and (candidate / "script").is_dir():
            return candidate
    return script_dir.parent


def resolve_game_root(candidate: Path | None) -> Path | None:
    if candidate is None:
        return None
    candidate = candidate.expanduser()
    if (candidate / "common").is_dir() and (candidate / "map_data").is_dir():
        return candidate.resolve()
    if (candidate / "game" / "common").is_dir() and (candidate / "game" / "map_data").is_dir():
        return (candidate / "game").resolve()
    return None


def default_game_root() -> Path | None:
    env_candidates = [
        os.environ.get("VIC3_GAME_DIR"),
        os.environ.get("VICTORIA3_GAME_DIR"),
    ]
    path_candidates = [
        Path(r"C:\Program Files (x86)\Steam\steamapps\common\Victoria 3\game"),
        Path(r"C:\Program Files\Steam\steamapps\common\Victoria 3\game"),
        Path.home() / "Games" / "Victoria 3" / "game",
    ]
    for raw in env_candidates:
        if not raw:
            continue
        resolved = resolve_game_root(Path(raw))
        if resolved is not None:
            return resolved
    for candidate in path_candidates:
        resolved = resolve_game_root(candidate)
        if resolved is not None:
            return resolved
    return None


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Manual Victoria 3 state demographics/resource/building editor")
    parser.add_argument("--root", type=Path, default=default_repo_root(), help="Repository root")
    parser.add_argument(
        "--game-root",
        type=Path,
        default=default_game_root(),
        help="Victoria 3 game directory (the folder containing common/ and map_data/).",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Load the repository, report what the editor sees, then exit without launching the GUI.",
    )
    return parser.parse_args(argv)


def run_check(repository: ModRepository) -> int:
    repository.load()
    canada_states = [record for record in repository.state_records.values() if record.canada_focus]
    print(f"Loaded {len(repository.state_records)} total states")
    print(f"Canada-focused default view contains {len(canada_states)} states")
    if canada_states:
        first = sorted(canada_states, key=lambda record: record.display_name)[0]
        print(f"Example state: {first.display_name} ({first.state_id})")
        print(f"  Region source: {first.region_source}")
        print(f"  Pop source: {first.pop_source}")
        print(f"  Building source: {first.building_source}")
        print(f"  Ownership source: {first.ownership_source}")
        print(f"  Owners: {', '.join(owner.tag for owner in first.owners) or '(none)'}")
        print(f"  Homelands: {', '.join(first.homelands) or '(none)'}")
    print(f"Known cultures: {len(repository.culture_choices)}")
    print(f"Known religions: {len(repository.religion_choices)}")
    print(f"Known resource/building ids: {len(repository.resource_choices)}")
    print(f"Known starting building ids: {len(repository.building_choices)}")
    print(f"Known ownership building types: {len(repository.ownership_building_type_choices)}")
    warning_count = sum(len(record.warnings) for record in repository.state_records.values())
    print(f"Per-state warnings: {warning_count}")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    repository = ModRepository(args.root.resolve(), resolve_game_root(args.game_root))
    try:
        repository.load()
    except Exception as exc:  # noqa: BLE001
        print(f"Failed to load repository: {exc}", file=sys.stderr)
        return 1

    if args.check:
        return run_check(repository)

    root = tk.Tk()
    Vic3StateEditorApp(root, repository)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
