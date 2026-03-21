#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
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
LOCALIZATION_PATTERN = re.compile(r'(?m)^\s*(STATE_[A-Z0-9_]+):\d?\s+"(.*)"\s*$')


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
class StateRecord:
    state_id: str
    display_name: str
    owners: list[OwnershipSlice]
    region_source: Path | None
    pop_source: Path | None
    ownership_source: Path | None
    arable_land: str = ""
    arable_resources: list[str] = field(default_factory=list)
    capped_resources: list[ResourceCountRow] = field(default_factory=list)
    discoverable_resources: list[DiscoverableResourceRow] = field(default_factory=list)
    pops_by_owner: dict[str, list[PopRow]] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    canada_focus: bool = False
    dirty: bool = False

    def owner_tags(self) -> list[str]:
        return [owner.tag for owner in self.owners]

    def all_owner_tags(self) -> list[str]:
        tags = self.owner_tags()
        seen = set(tags)
        for tag in self.pops_by_owner:
            if tag not in seen:
                tags.append(tag)
                seen.add(tag)
        return tags


@dataclass
class TopLevelEntry:
    key: str
    raw: str


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8-sig")


def detect_newline(path: Path) -> str:
    if not path.exists():
        return DEFAULT_NEWLINE
    data = path.read_bytes()
    if b"\r\n" in data:
        return "\r\n"
    if b"\n" in data:
        return "\n"
    return DEFAULT_NEWLINE


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


def parse_top_level_entries(block_text: str) -> list[TopLevelEntry]:
    open_index = block_text.find("{")
    close_index = block_text.rfind("}")
    if open_index == -1 or close_index == -1 or close_index <= open_index:
        return []
    entries: list[TopLevelEntry] = []
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
        entries.append(TopLevelEntry(key=key, raw=block_text[entry_start:entry_end].rstrip()))
        index = entry_end
    return entries


def detect_child_indent(block_text: str, default: str = "    ") -> str:
    for line in block_text.splitlines():
        stripped = line.lstrip()
        if stripped and stripped != "}":
            return line[: len(line) - len(stripped)]
    return default


def indent_unit(indent: str) -> str:
    return "\t" if "\t" in indent else "    "


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


def parse_ownership_block(block_text: str) -> list[OwnershipSlice]:
    owners: list[OwnershipSlice] = []
    for entry in parse_top_level_entries(block_text):
        if entry.key != "create_state":
            continue
        tag_match = re.search(r"country\s*=\s*c:([A-Z0-9_]+)", entry.raw)
        provinces_match = re.search(r"owned_provinces\s*=\s*\{([^}]*)\}", entry.raw, re.S)
        provinces = re.findall(r'"([^"]+)"', provinces_match.group(1)) if provinces_match else []
        if tag_match:
            owners.append(OwnershipSlice(tag_match.group(1), len(provinces)))
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


def render_state_region_block(state_id: str, original_block: str, record: StateRecord, newline: str) -> str:
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
        result_entries.append(entry.raw.rstrip())
    if not inserted:
        result_entries.extend(rendered_targets)

    rebuilt = header
    if result_entries:
        rebuilt += newline + newline.join(result_entries) + newline
    else:
        rebuilt += newline
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


def render_pop_state_block(record: StateRecord, newline: str) -> str:
    lines = [f"\ts:{record.state_id} = {{"]
    for owner_tag in record.all_owner_tags():
        lines.append(f"\t\tregion_state:{owner_tag} = {{")
        rows = normalize_pop_rows(record.pops_by_owner.get(owner_tag, []))
        for row in rows:
            lines.append("\t\t\tcreate_pop = {")
            lines.append(f"\t\t\t\tculture = {row.culture}")
            if row.religion.strip():
                lines.append(f"\t\t\t\treligion = {row.religion}")
            lines.append(f"\t\t\t\tsize = {row.size}")
            lines.append("\t\t\t}")
        lines.append("\t\t}")
    lines.append("\t}")
    return newline.join(lines)


def parse_int_string(value: str) -> int | None:
    stripped = value.strip()
    if not stripped:
        return None
    try:
        return int(stripped)
    except ValueError:
        return None


def owner_population_total(rows: list[PopRow]) -> int | None:
    total = 0
    for row in rows:
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

    cleaned_arable_resources: list[str] = []
    for resource in record.arable_resources:
        resource_id = resource.strip()
        if resource_id:
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
        if amount is None or amount < 0:
            raise ValueError(f"Discoverable resource '{resource_id}' needs a non-negative integer amount")
        if amount == 0:
            continue
        cleaned_discoverables.append(DiscoverableResourceRow(resource_id, str(amount), depleted_type))
    record.discoverable_resources = cleaned_discoverables

    normalized_pops: dict[str, list[PopRow]] = {}
    for owner_tag in record.all_owner_tags():
        normalized_pops[owner_tag] = normalize_pop_rows(record.pops_by_owner.get(owner_tag, []))
    record.pops_by_owner = normalized_pops


class ModRepository:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.state_regions_dir = root / "mod" / "map_data" / "state_regions"
        self.state_history_dir = root / "mod" / "common" / "history" / "states"
        self.pops_dir = root / "mod" / "common" / "history" / "pops"
        self.localization_file = root / "mod" / "localization" / "english" / "map_l_english.yml"
        self.culture_choices: list[str] = []
        self.religion_choices: list[str] = []
        self.resource_choices: list[str] = []
        self.state_records: dict[str, StateRecord] = {}
        self.global_warnings: list[str] = []

    def load(self) -> None:
        localizations = parse_localizations(self.localization_file)
        region_paths = sorted(self.state_regions_dir.glob("*.txt"), key=lambda path: path.name.lower())
        ownership_paths = sorted(self.state_history_dir.glob("*.txt"), key=lambda path: path.name.lower())
        pop_paths = sorted(self.pops_dir.glob("*.txt"), key=lambda path: path.name.lower())

        region_occurrences = build_effective_blocks(region_paths, STATE_REGION_PATTERN)
        ownership_occurrences = build_effective_blocks(ownership_paths, STATE_HISTORY_PATTERN)
        pop_occurrences = build_effective_blocks(pop_paths, STATE_HISTORY_PATTERN)

        culture_ids: set[str] = set()
        religion_ids: set[str] = set()
        resource_ids: set[str] = set()
        records: dict[str, StateRecord] = {}

        state_ids = sorted(
            set(region_occurrences)
            | {key.removeprefix("s:") for key in ownership_occurrences}
            | {key.removeprefix("s:") for key in pop_occurrences}
        )
        for state_id in state_ids:
            region_blocks = region_occurrences.get(state_id, [])
            ownership_blocks = ownership_occurrences.get(f"s:{state_id}", [])
            pop_blocks = pop_occurrences.get(f"s:{state_id}", [])

            region_source, region_block = region_blocks[-1] if region_blocks else (None, None)
            ownership_source, ownership_block = ownership_blocks[-1] if ownership_blocks else (None, None)
            pop_source, pop_block = pop_blocks[-1] if pop_blocks else (None, None)

            owners = parse_ownership_block(ownership_block) if ownership_block else []
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

            pops_by_owner: dict[str, list[PopRow]] = {}
            extra_pop_tags: list[str] = []
            if pop_block:
                owner_tags = {owner.tag for owner in owners}
                for entry in parse_top_level_entries(pop_block):
                    if not entry.key.startswith("region_state:"):
                        continue
                    owner_tag = entry.key.split(":", 1)[1]
                    pops = parse_pop_rows(entry.raw)
                    pops_by_owner[owner_tag] = pops
                    if owner_tag not in owner_tags:
                        extra_pop_tags.append(owner_tag)
                    for row in pops:
                        if row.culture:
                            culture_ids.add(row.culture)
                        if row.religion:
                            religion_ids.add(row.religion)

            warnings: list[str] = []
            if len(region_blocks) > 1:
                warnings.append("Multiple state-region definitions found; editing the last-loaded one.")
            if len(ownership_blocks) > 1:
                warnings.append("Multiple ownership blocks found; reading the last-loaded one.")
            if len(pop_blocks) > 1:
                warnings.append("Multiple pop blocks found; editing the last-loaded one.")
            if extra_pop_tags:
                warnings.append("Pop data contains owner tags not present in state history.")
            if pop_source is None:
                warnings.append("No pop block exists yet; save will create a new per-state pop file.")

            canada_focus = state_id in DEFAULT_CANADIAN_STATES

            records[state_id] = StateRecord(
                state_id=state_id,
                display_name=localizations.get(state_id, state_id.removeprefix("STATE_").replace("_", " ").title()),
                owners=owners,
                region_source=region_source,
                pop_source=pop_source,
                ownership_source=ownership_source,
                arable_land=arable_land,
                arable_resources=arable_resources,
                capped_resources=capped_resources,
                discoverable_resources=discoverables,
                pops_by_owner=pops_by_owner,
                warnings=warnings,
                canada_focus=canada_focus,
            )

        self.state_records = records
        self.culture_choices = sorted(culture_ids)
        self.religion_choices = sorted(religion_ids)
        self.resource_choices = sorted(resource_ids)

    def save_state(self, record: StateRecord) -> None:
        validate_record(record)
        self._save_state_region(record)
        self._save_pop_block(record)

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
        new_block = render_state_region_block(record.state_id, original_block, record, newline).replace("\n", newline)
        updated = replace_named_block(text, record.state_id, STATE_REGION_PATTERN, new_block)
        path.write_text(updated, encoding="utf-8", newline="")

    def _save_pop_block(self, record: StateRecord) -> None:
        source = record.pop_source or (self.pops_dir / f"99_manual_{record.state_id}.txt")
        newline = detect_newline(source)
        state_block = render_pop_state_block(record, newline)
        if source.exists():
            text = read_text(source)
            if find_named_block(text, f"s:{record.state_id}", STATE_HISTORY_PATTERN):
                updated = replace_named_block(text, f"s:{record.state_id}", STATE_HISTORY_PATTERN, state_block)
            else:
                updated = f"POPS = {{{newline}{newline}{state_block}{newline}}}{newline}"
        else:
            updated = f"POPS = {{{newline}{newline}{state_block}{newline}}}{newline}"
        source.write_text(updated, encoding="utf-8", newline="")


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
    ) -> None:
        super().__init__(master)
        self.columns = columns
        self.on_change = on_change
        self.row_widgets: list[tuple[ttk.Frame, dict[str, tk.StringVar]]] = []
        self._suspend_callbacks = False

        header = ttk.Frame(self)
        header.grid(row=0, column=0, sticky="ew")
        for column_index, column in enumerate(columns):
            ttk.Label(header, text=column.title).grid(row=0, column=column_index, sticky="w", padx=(0, 8))
        ttk.Label(header, text="").grid(row=0, column=len(columns), sticky="w")

        self.rows_frame = ttk.Frame(self)
        self.rows_frame.grid(row=1, column=0, sticky="ew")
        self.columnconfigure(0, weight=1)

        buttons = ttk.Frame(self)
        buttons.grid(row=2, column=0, sticky="w", pady=(6, 0))
        ttk.Button(buttons, text=add_label, command=self.add_blank_row).grid(row=0, column=0, sticky="w")

    def set_rows(self, rows: list[dict[str, str]]) -> None:
        self._suspend_callbacks = True
        try:
            for frame, _vars in self.row_widgets:
                frame.destroy()
            self.row_widgets.clear()
            if not rows:
                self.add_blank_row(trigger_change=False)
                return
            for row in rows:
                self._add_row_widgets(row, trigger_change=False)
        finally:
            self._suspend_callbacks = False

    def get_rows(self) -> list[dict[str, str]]:
        output: list[dict[str, str]] = []
        for _frame, variables in self.row_widgets:
            output.append({key: variables[key].get() for key in variables})
        return output

    def add_blank_row(self, trigger_change: bool = True) -> None:
        self._add_row_widgets({column.key: "" for column in self.columns}, trigger_change=trigger_change)

    def _add_row_widgets(self, row: dict[str, str], trigger_change: bool = True) -> None:
        frame = ttk.Frame(self.rows_frame)
        frame.grid(row=len(self.row_widgets), column=0, sticky="ew", pady=2)
        variables: dict[str, tk.StringVar] = {}
        for column_index, column in enumerate(self.columns):
            variable = tk.StringVar(value=row.get(column.key, ""))
            variable.trace_add("write", self._handle_change)
            variables[column.key] = variable
            if column.choices is not None:
                widget: ttk.Widget = ttk.Combobox(frame, textvariable=variable, values=column.choices, width=column.width)
            else:
                widget = ttk.Entry(frame, textvariable=variable, width=column.width)
            widget.grid(row=0, column=column_index, sticky="ew", padx=(0, 8))
        ttk.Button(frame, text="Remove", command=lambda: self._remove_row(frame)).grid(
            row=0, column=len(self.columns), sticky="w"
        )
        self.row_widgets.append((frame, variables))
        if trigger_change:
            self._handle_change()

    def _remove_row(self, frame: ttk.Frame) -> None:
        for index, (row_frame, _vars) in enumerate(self.row_widgets):
            if row_frame is frame:
                row_frame.destroy()
                self.row_widgets.pop(index)
                break
        for row_index, (row_frame, _vars) in enumerate(self.row_widgets):
            row_frame.grid_configure(row=row_index)
        if not self.row_widgets:
            self.add_blank_row(trigger_change=False)
        self._handle_change()

    def _handle_change(self, *_args: object) -> None:
        if not self._suspend_callbacks:
            self.on_change()


class Vic3StateEditorApp:
    def __init__(self, root: tk.Tk, repository: ModRepository) -> None:
        self.root = root
        self.repo = repository
        self.current_state_id: str | None = None
        self.filtered_state_ids: list[str] = []
        self.loading_ui = False

        root.title("Victoria 3 State Demographics Editor")
        root.geometry("1400x900")
        root.protocol("WM_DELETE_WINDOW", self.on_close)
        root.bind("<Control-s>", lambda _event: self.save_current())
        root.bind("<Control-S>", lambda _event: self.save_all())

        self.show_all_var = tk.BooleanVar(value=False)
        self.search_var = tk.StringVar()
        self.search_var.trace_add("write", lambda *_args: self.refresh_state_list())
        self.status_var = tk.StringVar(value="Ready")

        self.state_title_var = tk.StringVar(value="Select a state")
        self.source_var = tk.StringVar(value="")
        self.warning_var = tk.StringVar(value="")
        self.summary_var = tk.StringVar(value="")
        self.arable_land_var = tk.StringVar()
        self.arable_land_var.trace_add("write", lambda *_args: self._mark_dirty())

        self.owner_tables: dict[str, EditableTable] = {}
        self.owner_total_vars: dict[str, tk.StringVar] = {}
        self.owner_notebook: ttk.Notebook | None = None
        self.aggregate_text: tk.Text | None = None
        self.arable_table: EditableTable | None = None
        self.capped_table: EditableTable | None = None
        self.discoverable_table: EditableTable | None = None
        self.state_listbox: tk.Listbox | None = None

        self._build_ui()
        self.refresh_state_list()
        if self.filtered_state_ids:
            self.select_state(self.filtered_state_ids[0])

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
        self.state_listbox = tk.Listbox(left, exportselection=False)
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
        ttk.Button(button_bar, text="Reload From Disk", command=self.reload_repository).grid(row=0, column=2)
        header.columnconfigure(0, weight=1)

        ttk.Label(right, textvariable=self.source_var).grid(row=1, column=0, sticky="w", pady=(6, 0))
        ttk.Label(right, textvariable=self.warning_var, foreground="#9c5c00", wraplength=1000).grid(
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
        self.aggregate_text = tk.Text(population_tab, height=12, wrap="word")
        self.aggregate_text.grid(row=2, column=0, sticky="nsew")

        resources_tab = ttk.Frame(notebook, padding=8)
        notebook.add(resources_tab, text="Resources")
        ttk.Label(resources_tab, text="Arable land").grid(row=0, column=0, sticky="w")
        ttk.Entry(resources_tab, textvariable=self.arable_land_var, width=12).grid(row=0, column=1, sticky="w", padx=(8, 0))

        self.arable_table = EditableTable(
            resources_tab,
            columns=[ColumnSpec("resource", "Arable Resource", 28, self.repo.resource_choices)],
            on_change=self._mark_dirty,
            add_label="Add arable resource",
        )
        self.arable_table.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(12, 8))

        self.capped_table = EditableTable(
            resources_tab,
            columns=[
                ColumnSpec("resource", "Capped Resource", 28, self.repo.resource_choices),
                ColumnSpec("amount", "Max Level", 10),
            ],
            on_change=self._mark_dirty,
            add_label="Add capped resource",
        )
        self.capped_table.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(0, 8))

        self.discoverable_table = EditableTable(
            resources_tab,
            columns=[
                ColumnSpec("resource", "Discoverable Resource", 28, self.repo.resource_choices),
                ColumnSpec("amount", "Amount", 10),
                ColumnSpec("depleted_type", "Depleted Type", 28, self.repo.resource_choices),
            ],
            on_change=self._mark_dirty,
            add_label="Add discoverable resource",
        )
        self.discoverable_table.grid(row=3, column=0, columnspan=2, sticky="ew")
        resources_tab.columnconfigure(0, weight=1)

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
                        f"Pops: {record.pop_source.name if record.pop_source else 'new per-state file on save'}",
                        f"Ownership: {record.ownership_source.name if record.ownership_source else 'missing'}",
                    ]
                )
            )
            self.warning_var.set("Warnings: " + " ".join(record.warnings) if record.warnings else "")
            self.summary_var.set(self._build_owner_summary(record))
            self.arable_land_var.set(record.arable_land)
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
            self._rebuild_owner_tabs(record)
            self._refresh_aggregate_summary(record)
            self.status_var.set(f"Loaded {record.display_name}")
        finally:
            self.loading_ui = False

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

    def _rebuild_owner_tabs(self, record: StateRecord) -> None:
        assert self.owner_notebook is not None
        for child in self.owner_notebook.winfo_children():
            child.destroy()
        self.owner_tables.clear()
        self.owner_total_vars.clear()

        ownership_tags = {owner.tag for owner in record.owners}
        for owner_tag in record.all_owner_tags():
            frame = ttk.Frame(self.owner_notebook, padding=8)
            total_var = tk.StringVar()
            owner_label = owner_tag
            if owner_tag not in ownership_tags:
                owner_label += " (pop only)"
            ttk.Label(frame, textvariable=total_var).grid(row=0, column=0, sticky="w", pady=(0, 6))
            table = EditableTable(
                frame,
                columns=[
                    ColumnSpec("culture", "Culture", 24, self.repo.culture_choices),
                    ColumnSpec("religion", "Religion", 20, self.repo.religion_choices),
                    ColumnSpec("size", "Size", 12),
                ],
                on_change=self._mark_dirty,
                add_label="Add pop row",
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
        for owner_tag in record.all_owner_tags():
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
        for owner_tag, table in self.owner_tables.items():
            rows = [PopRow(row["culture"], row["religion"], row["size"]) for row in table.get_rows()]
            total = owner_population_total(rows)
            if total is None:
                text = f"{owner_tag} total: invalid size"
            else:
                text = f"{owner_tag} total: {total}"
            self.owner_total_vars[owner_tag].set(text)
        self.summary_var.set(self._build_owner_summary(record))

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


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Manual Victoria 3 state demographics/resource editor")
    parser.add_argument("--root", type=Path, default=default_repo_root(), help="Repository root")
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
        print(f"  Ownership source: {first.ownership_source}")
        print(f"  Owners: {', '.join(owner.tag for owner in first.owners) or '(none)'}")
    print(f"Known cultures: {len(repository.culture_choices)}")
    print(f"Known religions: {len(repository.religion_choices)}")
    print(f"Known resource/building ids: {len(repository.resource_choices)}")
    warning_count = sum(len(record.warnings) for record in repository.state_records.values())
    print(f"Per-state warnings: {warning_count}")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    repository = ModRepository(args.root.resolve())
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
