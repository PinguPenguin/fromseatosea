#!/usr/bin/env python3
from __future__ import annotations

import argparse
import colorsys
import math
import re
import sys
import tkinter as tk
from collections import OrderedDict, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from tkinter import messagebox, ttk

try:
    import numpy as np
    from PIL import Image, ImageTk

    PIL_AVAILABLE = True
except Exception:
    np = None
    Image = None
    ImageTk = None
    PIL_AVAILABLE = False

import vic3_state_editor as vse


DEFAULT_GAME_ROOT = Path(r"C:\Program Files (x86)\Steam\steamapps\common\Victoria 3")
DEFAULT_USFP_ROOT = Path(r"C:\Users\jubju\Documents\VicModding\Hail, Columbia!")

C2C_STATE_HISTORY = Path("common/history/states/zz_c2c_history_states.txt")
C2C_POP_HISTORY = Path("common/history/pops/zz_c2c_history_pops.txt")
C2C_BUILDING_HISTORY = Path("common/history/buildings/c2c_history_buildings.txt")

STATE_KEY_RE = re.compile(r"(?m)^([ \t]*)(STATE_[A-Za-z0-9_]+)\s*=\s*\{")
COUNTRY_KEY_RE = re.compile(r"(?m)^([ \t]*)([A-Za-z0-9_]+)\s*=\s*\{")
STRATEGIC_REGION_RE = re.compile(r"(?m)^([ \t]*)(?:INJECT:)?(region_[A-Za-z0-9_]+)\s*=\s*\{")
GENERIC_BLOCK_RE = re.compile(r"(?m)^([ \t]*)([A-Za-z0-9_:.]+)\s*=\s*\{")
RGB_PROVINCE_RE = re.compile(r'"?(x[0-9A-Fa-f]{6})"?')
STATE_OWNERSHIP_KEYS = {"create_state", "set_owner_of_provinces"}

CANADA_US_STRATEGIC_REGIONS = {
    "region_canada",
    "region_new_england",
    "region_pacific_coast",
    "region_great_plains",
    "region_the_midwest",
    "region_dixie",
}

DARK_BG = "#14181e"
DARK_PANEL = "#1b222c"
DARK_ELEVATED = "#222b36"
DARK_BORDER = "#344150"
DARK_FG = "#e8edf4"
DARK_MUTED = "#aab6c6"
ACCENT = "#4d9cff"
SELECTION = "#f7d154"
WARNING = "#ffbe76"
MIN_SCALE = 0.08
MAX_SCALE = 1.50
ZOOM_FACTOR = 1.35
RENDER_MARGIN = 320


@dataclass
class DataSource:
    name: str
    root: Path
    content_root: Path
    enabled: bool = True


@dataclass
class StateRegion:
    state_id: str
    provinces: list[str]
    source_name: str
    source_path: Path


@dataclass
class SaveResult:
    changed_files: set[Path] = field(default_factory=set)
    warnings: list[str] = field(default_factory=list)

    def add(self, other: "SaveResult") -> None:
        self.changed_files.update(other.changed_files)
        self.warnings.extend(other.warnings)


def repo_root_from_script() -> Path:
    return Path(__file__).resolve().parents[1]


def normalize_province(value: str) -> str:
    value = value.strip().strip('"').lower()
    if not value.startswith("x"):
        value = "x" + value
    return value


def province_to_packed(value: str) -> int:
    clean = normalize_province(value)[1:]
    return int(clean, 16)


def packed_to_province(value: int) -> str:
    return f"x{int(value):06x}"


def path_key(path: Path) -> str:
    try:
        return str(path.resolve()).lower()
    except OSError:
        return str(path.absolute()).lower()


def strip_line_comments(text: str) -> str:
    return "\n".join(line.split("#", 1)[0] for line in text.splitlines())


def extract_province_lists(raw: str, key: str) -> list[str]:
    provinces: list[str] = []
    for match in re.finditer(rf"(?<![A-Za-z0-9_]){re.escape(key)}\s*=\s*\{{", raw):
        brace_index = raw.find("{", match.end() - 1)
        if brace_index == -1:
            continue
        try:
            close_index = vse.find_matching_brace(raw, brace_index)
        except ValueError:
            continue
        inner = raw[brace_index + 1 : close_index]
        provinces.extend(normalize_province(item) for item in RGB_PROVINCE_RE.findall(inner))
    return provinces


def parse_country_tag(raw: str) -> str:
    for entry in vse.parse_top_level_entries(raw):
        if entry.key != "country":
            continue
        value = entry.raw.split("=", 1)[1].strip().strip('"')
        return strip_country_scope(value)
    match = re.search(r'(?m)^\s*country\s*=\s*(?:"?c:)?([A-Za-z0-9_]+)"?\s*$', raw)
    return match.group(1).strip() if match else ""


def parse_scope_tag(raw: str, key: str) -> str:
    match = re.search(rf'(?m)^\s*{re.escape(key)}\s*=\s*(?:"?c:)?([A-Za-z0-9_]+)"?\s*$', raw)
    return match.group(1).strip() if match else ""


def strip_country_scope(value: str) -> str:
    return re.sub(r"(?i)^c:", "", value.strip().strip('"')).strip()


def chunked(values: list[str], size: int) -> list[list[str]]:
    return [values[index : index + size] for index in range(0, len(values), size)]


def render_province_block(
    key: str,
    provinces: list[str],
    base_indent: str,
    quote: bool,
    per_line: int = 10,
) -> list[str]:
    if not provinces:
        return [f"{base_indent}{key} = {{ }}"]
    lines = [f"{base_indent}{key} = {{"]
    for chunk in chunked(provinces, per_line):
        if quote:
            rendered = " ".join(f'"{province}"' for province in chunk)
        else:
            rendered = " ".join(province for province in chunk)
        lines.append(f"{base_indent}\t{rendered}")
    lines.append(f"{base_indent}}}")
    return lines


def stable_tag_color(tag: str) -> tuple[int, int, int]:
    clean = tag.upper()
    seed = sum((index + 1) * ord(char) for index, char in enumerate(clean))
    hue = (seed % 360) / 360.0
    red, green, blue = colorsys.hsv_to_rgb(hue, 0.57, 0.82)
    return int(red * 255), int(green * 255), int(blue * 255)


def parse_color(raw: str) -> tuple[int, int, int] | None:
    hsv_match = re.search(r"color\s*=\s*hsv\s*\{\s*([0-9.]+)\s+([0-9.]+)\s+([0-9.]+)\s*\}", raw)
    if hsv_match:
        hue, sat, val = (float(hsv_match.group(index)) for index in range(1, 4))
        red, green, blue = colorsys.hsv_to_rgb(hue, sat, val)
        return int(red * 255), int(green * 255), int(blue * 255)

    rgb_match = re.search(r"color\s*=\s*\{\s*(\d+)\s+(\d+)\s+(\d+)\s*\}", raw)
    if rgb_match:
        return tuple(max(0, min(255, int(rgb_match.group(index)))) for index in range(1, 4))  # type: ignore[return-value]
    return None


def format_owner_summary(groups: OrderedDict[str, list[str]]) -> str:
    parts = [f"{tag}:{len(provinces)}" for tag, provinces in groups.items()]
    return "  ".join(parts) if parts else "No owner tags"


class C2CTagRepository:
    def __init__(self, root: Path, game_root: Path | None, upstream_mod: Path | None) -> None:
        self.root = root
        self.mod_root = root / "mod"
        self.game_root = game_root
        self.upstream_mod = upstream_mod if upstream_mod and upstream_mod.exists() else None

        self.state_history_path = self.mod_root / C2C_STATE_HISTORY
        self.pop_path = self.mod_root / C2C_POP_HISTORY
        self.building_path = self.mod_root / C2C_BUILDING_HISTORY

        self.sources: list[DataSource] = []
        if game_root and game_root.exists():
            self.sources.append(DataSource("Vanilla", game_root, game_root / "game"))
        if self.upstream_mod:
            self.sources.append(DataSource("USFP", self.upstream_mod, self.upstream_mod))
        self.sources.append(DataSource("c2c", self.mod_root, self.mod_root))

        self.state_regions: dict[str, StateRegion] = {}
        self.relevant_state_ids: set[str] = set()
        self.vanilla_state_ids: set[str] = set()
        self.province_to_state: dict[str, str] = {}
        self.history_ownership: dict[str, str] = {}
        self.ownership: dict[str, str] = {}
        self.country_colors: dict[str, tuple[int, int, int]] = {}
        self.country_tag_by_key: dict[str, str] = {}
        self.custom_state_ids: set[str] = set()
        self.province_image_path: Path | None = None
        self.province_image = None
        self.province_rgb = None
        self.visible_map_bounds: tuple[int, int, int, int] | None = None

    def load(self, load_image: bool = True) -> None:
        self.relevant_state_ids = self.load_relevant_state_ids()
        self.state_regions = self.load_state_regions()
        self.province_to_state = {}
        for state_id, region in self.state_regions.items():
            for province in region.provinces:
                self.province_to_state[province] = state_id
        self.custom_state_ids = self.scan_custom_state_ids()
        self.country_colors = self.scan_country_colors()
        self.country_tag_by_key = {tag.casefold(): tag for tag in self.country_colors}
        self.history_ownership = self.load_effective_ownership(apply_startup_effects=False)
        self.ownership = dict(self.history_ownership)
        self.apply_startup_ownership_effects(self.ownership)
        if load_image:
            self.load_province_image()

    def source_dirs(self, source: DataSource, *parts: str) -> list[Path]:
        return [
            source.content_root.joinpath(*parts),
            source.content_root.joinpath(*parts).parent / parts[-1].replace("map_data", "map/data"),
        ]

    def state_region_dirs(self, source: DataSource) -> list[Path]:
        return [
            source.content_root / "map_data" / "state_regions",
            source.content_root / "map" / "data" / "state_regions",
        ]

    def history_dir(self, source: DataSource, folder: str) -> Path:
        return source.content_root / "common" / "history" / folder

    def country_definition_dirs(self, source: DataSource) -> list[Path]:
        return [source.content_root / "common" / "country_definitions"]

    def strategic_region_dirs(self, source: DataSource) -> list[Path]:
        return [source.content_root / "common" / "strategic_regions"]

    def load_relevant_state_ids(self) -> set[str]:
        state_ids: set[str] = set()
        for source in self.sources:
            for directory in self.strategic_region_dirs(source):
                if not directory.is_dir():
                    continue
                for path in sorted(directory.glob("*.txt"), key=lambda item: item.name.lower()):
                    text = vse.read_text(path)
                    for region_id, _start, _end, block in vse.iter_named_blocks(text, STRATEGIC_REGION_RE):
                        if region_id not in CANADA_US_STRATEGIC_REGIONS:
                            continue
                        state_ids.update(re.findall(r"\bSTATE_[A-Za-z0-9_]+\b", block))
        return state_ids

    def load_state_regions(self) -> dict[str, StateRegion]:
        regions: dict[str, StateRegion] = {}
        vanilla_ids: set[str] = set()
        for source in self.sources:
            for directory in self.state_region_dirs(source):
                if not directory.is_dir():
                    continue
                for path in sorted(directory.glob("*.txt"), key=lambda item: item.name.lower()):
                    text = vse.read_text(path)
                    for state_id, _start, _end, block in vse.iter_named_blocks(text, STATE_KEY_RE):
                        if self.relevant_state_ids and state_id not in self.relevant_state_ids:
                            continue
                        provinces = extract_province_lists(block, "provinces")
                        if not provinces:
                            continue
                        regions[state_id] = StateRegion(state_id, provinces, source.name, path)
                        if source.name == "Vanilla":
                            vanilla_ids.add(state_id)
        self.vanilla_state_ids = vanilla_ids
        return regions

    def scan_custom_state_ids(self) -> set[str]:
        if not self.state_history_path.exists():
            return set()
        result: set[str] = set()
        text = vse.read_text(self.state_history_path)
        for key, _start, _end, block in vse.iter_named_blocks(text, vse.STATE_HISTORY_PATTERN):
            if any(entry.key == "create_state" for entry in vse.parse_top_level_entries(block)):
                result.add(key.removeprefix("s:"))
        return result

    def scan_country_colors(self) -> dict[str, tuple[int, int, int]]:
        colors: dict[str, tuple[int, int, int]] = {}
        for source in self.sources:
            for directory in self.country_definition_dirs(source):
                if not directory.is_dir():
                    continue
                for path in sorted(directory.glob("*.txt"), key=lambda item: item.name.lower()):
                    text = vse.read_text(path)
                    for tag, _start, _end, block in vse.iter_named_blocks(text, COUNTRY_KEY_RE):
                        parsed = parse_color(block)
                        if parsed is not None:
                            colors[tag] = parsed
        return colors

    def canonical_country_tag(self, tag: str) -> str:
        clean = strip_country_scope(tag)
        return self.country_tag_by_key.get(clean.casefold(), clean)

    def history_files(self, folder: str) -> list[Path]:
        files: list[Path] = []
        for source in self.sources:
            directory = self.history_dir(source, folder)
            if not directory.is_dir():
                continue
            files.extend(sorted(directory.glob("*.txt"), key=lambda item: item.name.lower()))
        return files

    def common_files(self, folder: str) -> list[Path]:
        files: list[Path] = []
        for source in self.sources:
            directory = source.content_root / "common" / folder
            if not directory.is_dir():
                continue
            files.extend(sorted(directory.glob("*.txt"), key=lambda item: item.name.lower()))
        return files

    def load_effective_ownership(
        self,
        skip_blocks: set[tuple[str, str]] | None = None,
        apply_startup_effects: bool = True,
    ) -> dict[str, str]:
        skip_blocks = skip_blocks or set()
        ownership: dict[str, str] = {}

        for path in self.history_files("states"):
            path_id = path_key(path)
            text = vse.read_text(path)
            for key, _start, _end, block in vse.iter_named_blocks(text, vse.STATE_HISTORY_PATTERN):
                state_id = key.removeprefix("s:")
                if (path_id, key) in skip_blocks:
                    continue
                region = self.state_regions.get(state_id)
                if region is None:
                    continue
                state_provinces = set(region.provinces)

                for entry in vse.parse_top_level_entries(strip_line_comments(block)):
                    if entry.key == "create_state":
                        tag = self.canonical_country_tag(parse_country_tag(entry.raw))
                        if not tag:
                            continue
                        provinces = extract_province_lists(entry.raw, "owned_provinces")
                        if not provinces:
                            provinces = region.provinces
                        for province in provinces:
                            if province in state_provinces:
                                ownership[province] = tag
                    elif entry.key == "set_owner_of_provinces":
                        tag = self.canonical_country_tag(parse_country_tag(entry.raw))
                        if not tag:
                            continue
                        for province in extract_province_lists(entry.raw, "provinces"):
                            if province in state_provinces:
                                ownership[province] = tag

        if apply_startup_effects:
            self.apply_startup_ownership_effects(ownership)
        return ownership

    def apply_startup_ownership_effects(self, ownership: dict[str, str]) -> None:
        action_names = self.startup_on_action_names()
        if not action_names:
            return

        pending_scripted_effects: list[str] = []
        seen_actions: set[str] = set()
        for action_name in action_names:
            if action_name in seen_actions:
                continue
            seen_actions.add(action_name)
            for action_block in self.find_common_blocks("on_actions", action_name):
                for entry in vse.parse_top_level_entries(strip_line_comments(action_block)):
                    if entry.key == "effect":
                        effect_block = strip_line_comments(entry.raw)
                        self.apply_ownership_effect_block(ownership, effect_block)
                        pending_scripted_effects.extend(self.scripted_effect_calls(effect_block))

        seen_effects: set[str] = set()
        while pending_scripted_effects:
            effect_name = pending_scripted_effects.pop(0)
            if effect_name in seen_effects:
                continue
            seen_effects.add(effect_name)
            for effect_block in self.find_common_blocks("scripted_effects", effect_name):
                clean_block = strip_line_comments(effect_block)
                self.apply_ownership_effect_block(ownership, clean_block)
                pending_scripted_effects.extend(self.scripted_effect_calls(clean_block))

    def startup_on_action_names(self) -> list[str]:
        names: list[str] = []
        for block in self.find_common_blocks("on_actions", "on_game_started"):
            for entry in vse.parse_top_level_entries(strip_line_comments(block)):
                if entry.key != "on_actions":
                    continue
                open_index = entry.raw.find("{")
                close_index = entry.raw.rfind("}")
                if open_index == -1 or close_index == -1 or close_index <= open_index:
                    continue
                names.extend(re.findall(r"\b[A-Za-z0-9_]+\b", entry.raw[open_index + 1 : close_index]))
        return names

    def find_common_blocks(self, folder: str, key: str) -> list[str]:
        blocks: list[str] = []
        for path in self.common_files(folder):
            text = strip_line_comments(vse.read_text(path))
            for block_key, _start, _end, block in vse.iter_named_blocks(text, GENERIC_BLOCK_RE):
                if block_key == key:
                    blocks.append(block)
        return blocks

    def scripted_effect_calls(self, block: str) -> list[str]:
        calls: list[str] = []
        for entry in vse.parse_top_level_entries(block):
            if entry.key == "effect":
                calls.extend(self.scripted_effect_calls(entry.raw))
            elif re.fullmatch(rf"\s*{re.escape(entry.key)}\s*=\s*yes\s*", entry.raw):
                calls.append(entry.key)
        return calls

    def apply_ownership_effect_block(self, ownership: dict[str, str], block: str) -> None:
        for entry in vse.parse_top_level_entries(block):
            if not entry.key.startswith("s:STATE_"):
                continue
            state_id = entry.key.removeprefix("s:")
            region = self.state_regions.get(state_id)
            if region is None:
                continue
            state_provinces = set(region.provinces)
            for child in vse.parse_top_level_entries(entry.raw):
                if child.key.startswith("region_state:"):
                    old_tag = self.canonical_country_tag(child.key.partition(":")[2])
                    self.apply_region_state_owner_effect(ownership, region, old_tag, child.raw)
                elif child.key == "set_state_owner":
                    new_tag = self.canonical_country_tag(parse_scope_tag(child.raw, "set_state_owner"))
                    if new_tag:
                        for province in region.provinces:
                            ownership[province] = new_tag
                elif child.key == "set_owner_of_provinces":
                    tag = self.canonical_country_tag(parse_country_tag(child.raw))
                    if not tag:
                        continue
                    for province in extract_province_lists(child.raw, "provinces"):
                        if province in state_provinces:
                            ownership[province] = tag

    def apply_region_state_owner_effect(
        self,
        ownership: dict[str, str],
        region: StateRegion,
        old_tag: str,
        block: str,
    ) -> None:
        new_tag = ""
        for entry in vse.parse_top_level_entries(block):
            if entry.key == "set_state_owner":
                new_tag = self.canonical_country_tag(parse_scope_tag(entry.raw, "set_state_owner"))
                break
        if not new_tag:
            return
        for province in region.provinces:
            if ownership.get(province) == old_tag:
                ownership[province] = new_tag

    def load_province_image(self) -> None:
        if not PIL_AVAILABLE:
            raise RuntimeError("Pillow and numpy are required for map visualization.")
        candidates = [
            self.mod_root / "map_data" / "provinces.png",
            self.mod_root / "map" / "data" / "provinces.png",
        ]
        if self.game_root:
            candidates.extend(
                [
                    self.game_root / "game" / "map_data" / "provinces.png",
                    self.game_root / "game" / "map" / "data" / "provinces.png",
                ]
            )
        for path in candidates:
            if path.exists():
                self.province_image_path = path
                self.province_image = Image.open(path).convert("RGB")
                self.province_image.load()
                self.province_rgb = np.asarray(self.province_image, dtype=np.uint8)
                self.visible_map_bounds = self.calculate_visible_map_bounds()
                return
        raise FileNotFoundError("Could not find provinces.png in c2c or the Victoria 3 install.")

    def calculate_visible_map_bounds(self) -> tuple[int, int, int, int] | None:
        if self.province_rgb is None or not self.province_to_state:
            return None
        province_values = np.array([province_to_packed(province) for province in self.province_to_state], dtype=np.int32)
        packed = (
            self.province_rgb[:, :, 0].astype(np.int32) << 16
        ) + (
            self.province_rgb[:, :, 1].astype(np.int32) << 8
        ) + self.province_rgb[:, :, 2].astype(np.int32)
        mask = np.isin(packed, province_values)
        if not np.any(mask):
            return None
        ys, xs = np.nonzero(mask)
        height, width = packed.shape
        pad = 48
        left = max(int(xs.min()) - pad, 0)
        top = max(int(ys.min()) - pad, 0)
        right = min(int(xs.max()) + pad + 1, width)
        bottom = min(int(ys.max()) + pad + 1, height)
        return left, top, right, bottom

    def is_custom_history_state(self, state_id: str) -> bool:
        if state_id in self.custom_state_ids:
            return True
        return state_id not in self.vanilla_state_ids

    def state_owner_groups(
        self,
        state_id: str,
        ownership: dict[str, str] | None = None,
    ) -> OrderedDict[str, list[str]]:
        ownership = ownership if ownership is not None else self.ownership
        region = self.state_regions[state_id]
        groups: OrderedDict[str, list[str]] = OrderedDict()
        for province in region.provinces:
            tag = ownership.get(province, "")
            if tag:
                groups.setdefault(tag, []).append(province)
        return groups

    def desired_groups(
        self,
        state_id: str,
        desired_owner_by_province: dict[str, str],
    ) -> OrderedDict[str, list[str]]:
        region = self.state_regions[state_id]
        groups: OrderedDict[str, list[str]] = OrderedDict()
        missing: list[str] = []
        for province in region.provinces:
            tag = self.canonical_country_tag(desired_owner_by_province.get(province, ""))
            if not tag:
                missing.append(province)
                continue
            groups.setdefault(tag, []).append(province)
        if missing:
            sample = ", ".join(missing[:8])
            raise ValueError(f"{state_id} has {len(missing)} province(s) without owner tags: {sample}")
        return groups

    def save_state(
        self,
        state_id: str,
        desired_owner_by_province: dict[str, str],
        redirects: dict[str, set[str]],
        move_orphans: bool,
        clean_orphans: bool,
    ) -> SaveResult:
        groups = self.desired_groups(state_id, desired_owner_by_province)
        result = SaveResult()
        if self.is_custom_history_state(state_id):
            result.add(self.save_custom_state_block(state_id, groups, desired_owner_by_province))
        else:
            result.add(self.save_vanilla_state_diff(state_id, groups, desired_owner_by_province))

        if clean_orphans:
            desired_tags = set(groups)
            result.add(
                self.sync_pop_history(state_id, groups, desired_tags, redirects, move_orphans=move_orphans)
            )
            result.add(
                self.sync_building_history(state_id, groups, desired_tags, redirects, move_orphans=move_orphans)
            )
        return result

    def save_custom_state_block(
        self,
        state_id: str,
        groups: OrderedDict[str, list[str]],
        desired_owner_by_province: dict[str, str],
    ) -> SaveResult:
        existing = self.find_state_blocks(self.state_history_path, state_id)
        preserved = self.preserved_state_entries_from_blocks(existing, ownership_keys=STATE_OWNERSHIP_KEYS)
        block = self.render_custom_state_block(state_id, groups, preserved)
        return self.update_states_file(self.state_history_path, f"s:{state_id}", block)

    def state_blocks_owner_by_province(
        self,
        state_id: str,
        blocks: list[tuple[int, int, str]],
    ) -> dict[str, str]:
        owner_by_province: dict[str, str] = {}
        region = self.state_regions.get(state_id)
        state_provinces = set(region.provinces) if region else set()

        for _start, _end, block in blocks:
            for entry in vse.parse_top_level_entries(strip_line_comments(block)):
                if entry.key not in STATE_OWNERSHIP_KEYS:
                    continue
                tag = self.canonical_country_tag(parse_country_tag(entry.raw))
                if not tag:
                    continue
                if entry.key == "create_state":
                    provinces = extract_province_lists(entry.raw, "owned_provinces")
                    if not provinces and region:
                        provinces = region.provinces
                else:
                    provinces = extract_province_lists(entry.raw, "provinces")
                for province in provinces:
                    if not state_provinces or province in state_provinces:
                        owner_by_province[province] = tag
        return owner_by_province

    def save_vanilla_state_diff(
        self,
        state_id: str,
        groups: OrderedDict[str, list[str]],
        desired_owner_by_province: dict[str, str],
    ) -> SaveResult:
        skip = {(path_key(self.state_history_path), f"s:{state_id}")}
        baseline = self.load_effective_ownership(skip_blocks=skip, apply_startup_effects=False)
        existing = self.find_state_blocks(self.state_history_path, state_id)
        explicit_master_owners = self.state_blocks_owner_by_province(state_id, existing)
        changed: OrderedDict[str, list[str]] = OrderedDict()
        for tag, provinces in groups.items():
            for province in provinces:
                desired_owner = desired_owner_by_province.get(province, "")
                if baseline.get(province, "") != desired_owner or province in explicit_master_owners:
                    changed.setdefault(tag, []).append(province)

        preserved = self.preserved_state_entries_from_blocks(existing, ownership_keys=STATE_OWNERSHIP_KEYS)
        block = None
        if changed or preserved:
            block = self.render_vanilla_state_block(state_id, changed, preserved)
        return self.update_states_file(self.state_history_path, f"s:{state_id}", block)

    def find_state_block(self, path: Path, state_id: str) -> tuple[int, int, str] | None:
        blocks = self.find_state_blocks(path, state_id)
        return blocks[0] if blocks else None

    def find_state_blocks(self, path: Path, state_id: str) -> list[tuple[int, int, str]]:
        if not path.exists():
            return []
        key = f"s:{state_id}"
        text = vse.read_text(path)
        return [
            (start, end, block)
            for block_key, start, end, block in vse.iter_named_blocks(text, vse.STATE_HISTORY_PATTERN)
            if block_key == key
        ]

    def preserved_state_entries(self, block: str | None, ownership_keys: set[str]) -> list[str]:
        if not block:
            return []
        preserved: list[str] = []
        for entry in vse.parse_top_level_entries(block):
            if entry.key in ownership_keys:
                continue
            preserved.append(entry.raw)
        return preserved

    def preserved_state_entries_from_blocks(
        self,
        blocks: list[tuple[int, int, str]],
        ownership_keys: set[str],
    ) -> list[str]:
        preserved: list[str] = []
        for _start, _end, block in blocks:
            preserved.extend(self.preserved_state_entries(block, ownership_keys))
        return preserved

    def render_custom_state_block(
        self,
        state_id: str,
        groups: OrderedDict[str, list[str]],
        preserved_entries: list[str],
    ) -> str:
        lines = [f"\ts:{state_id} = {{"]
        for tag, provinces in groups.items():
            lines.append("\t\tset_owner_of_provinces = {")
            lines.append(f"\t\t\tcountry = c:{tag}")
            lines.extend(render_province_block("provinces", provinces, "\t\t\t", quote=False))
            lines.append("\t\t}")
        for raw in preserved_entries:
            lines.append(vse.normalize_entry_indentation(raw.rstrip(), "\t\t"))
        lines.append("\t}")
        return "\n".join(lines)

    def render_vanilla_state_block(
        self,
        state_id: str,
        changed: OrderedDict[str, list[str]],
        preserved_entries: list[str],
    ) -> str:
        lines = [f"\ts:{state_id} = {{"]
        for tag, provinces in changed.items():
            lines.append("\t\tset_owner_of_provinces = {")
            lines.append(f"\t\t\tcountry = c:{tag}")
            lines.extend(render_province_block("provinces", provinces, "\t\t\t", quote=False))
            lines.append("\t\t}")
        for raw in preserved_entries:
            lines.append(vse.normalize_entry_indentation(raw.rstrip(), "\t\t"))
        lines.append("\t}")
        return "\n".join(lines)

    def update_states_file(self, path: Path, key: str, new_block: str | None) -> SaveResult:
        result = SaveResult()
        original = vse.read_text(path) if path.exists() else None
        newline = vse.detect_newline(path)

        if original is None:
            if new_block is None:
                return result
            updated = f"STATES = {{\n\n{new_block}\n}}\n"
        else:
            wrapper = vse.find_named_block(original, "STATES", vse.STATES_WRAPPER_PATTERN)
            if wrapper is None:
                if new_block is None:
                    return result
                updated = f"{original.rstrip()}\n\nSTATES = {{\n\n{new_block}\n}}\n"
            else:
                wrapper_start, wrapper_end, wrapper_block = wrapper
                if not self.state_history_blocks_in_wrapper(wrapper_block, key):
                    if new_block is None:
                        updated_wrapper = wrapper_block
                    else:
                        updated_wrapper = vse.insert_top_level_entry(wrapper_block, new_block)
                else:
                    updated_wrapper = self.replace_state_history_blocks(wrapper_block, key, new_block)
                updated = original[:wrapper_start] + updated_wrapper + original[wrapper_end:]

        if original != updated:
            path.parent.mkdir(parents=True, exist_ok=True)
            vse.write_text(path, updated, newline)
            result.changed_files.add(path)
        return result

    def state_history_blocks_in_wrapper(self, wrapper_block: str, key: str) -> list[tuple[int, int, str]]:
        return [
            (start, end, block)
            for block_key, start, end, block in vse.iter_named_blocks(wrapper_block, vse.STATE_HISTORY_PATTERN)
            if block_key == key
        ]

    def replace_state_history_blocks(self, wrapper_block: str, key: str, new_block: str | None) -> str:
        matches = self.state_history_blocks_in_wrapper(wrapper_block, key)
        if not matches:
            if new_block is None:
                return wrapper_block
            return vse.insert_top_level_entry(wrapper_block, new_block)

        updated = wrapper_block
        for start, end, _block in reversed(matches[1:]):
            updated = self.remove_text_span(updated, start, end)

        first_start, first_end, _first_block = matches[0]
        if new_block is None:
            return self.remove_text_span(updated, first_start, first_end)
        return updated[:first_start] + new_block + updated[first_end:]

    def remove_text_span(self, text: str, start: int, end: int) -> str:
        prefix = text[:start].rstrip("\r\n")
        suffix = text[end:].lstrip("\r\n")
        if not suffix:
            return prefix
        separator = "\n" if prefix.rstrip().endswith("{") or suffix.startswith("}") else "\n\n"
        return prefix + separator + suffix

    def sync_pop_history(
        self,
        state_id: str,
        groups: OrderedDict[str, list[str]],
        desired_tags: set[str],
        redirects: dict[str, set[str]],
        move_orphans: bool,
    ) -> SaveResult:
        if not self.pop_path.exists():
            return SaveResult()
        text = vse.read_text(self.pop_path)
        found = vse.find_pop_state_section(text, f"s:{state_id}")
        if found is None:
            return SaveResult()
        start, end, block = found
        new_block, warnings = self.sync_region_state_block(
            state_id,
            block,
            groups,
            desired_tags,
            redirects,
            kind="pops",
            move_orphans=move_orphans,
            create_empty_missing=False,
        )
        result = SaveResult(warnings=warnings)
        if new_block == block:
            return result
        if new_block is None:
            updated = vse.remove_pop_state_section(text, f"s:{state_id}")
        else:
            updated = vse.replace_pop_state_section(text, f"s:{state_id}", new_block)
        if updated != text:
            vse.write_text(self.pop_path, updated, vse.detect_newline(self.pop_path))
            result.changed_files.add(self.pop_path)
        return result

    def sync_building_history(
        self,
        state_id: str,
        groups: OrderedDict[str, list[str]],
        desired_tags: set[str],
        redirects: dict[str, set[str]],
        move_orphans: bool,
    ) -> SaveResult:
        if not self.building_path.exists():
            return SaveResult()
        text = vse.read_text(self.building_path)
        wrapper = vse.find_named_block(text, "BUILDINGS", vse.BUILDINGS_WRAPPER_PATTERN)
        if wrapper is None:
            return SaveResult()
        wrapper_start, wrapper_end, wrapper_block = wrapper
        state_key = f"s:{state_id}"
        state_entry = vse.find_top_level_entry_span(wrapper_block, state_key)
        if state_entry is None:
            return SaveResult()

        new_block, warnings = self.sync_region_state_block(
            state_id,
            state_entry.raw,
            groups,
            desired_tags,
            redirects,
            kind="buildings",
            move_orphans=move_orphans,
            create_empty_missing=False,
        )
        result = SaveResult(warnings=warnings)
        if new_block == state_entry.raw:
            return result
        if new_block is None:
            updated_wrapper = vse.remove_top_level_entry(wrapper_block, state_key)
        else:
            updated_wrapper = vse.replace_top_level_entry(wrapper_block, state_key, new_block)
        updated = text[:wrapper_start] + updated_wrapper + text[wrapper_end:]
        if updated != text:
            vse.write_text(self.building_path, updated, vse.detect_newline(self.building_path))
            result.changed_files.add(self.building_path)
        return result

    def sync_region_state_block(
        self,
        state_id: str,
        block: str,
        groups: OrderedDict[str, list[str]],
        desired_tags: set[str],
        redirects: dict[str, set[str]],
        kind: str,
        move_orphans: bool,
        create_empty_missing: bool,
    ) -> tuple[str | None, list[str]]:
        warnings: list[str] = []
        desired_order = list(groups)
        owner_blocks: OrderedDict[str, str] = OrderedDict()
        extras: list[str] = []
        changed = False

        for entry in vse.parse_top_level_entries(block):
            if entry.key.startswith("region_state:"):
                owner = self.canonical_country_tag(entry.key.partition(":")[2])
                if owner in desired_tags:
                    if owner in owner_blocks:
                        owner_blocks[owner] = self.merge_region_state_blocks(owner_blocks[owner], entry.raw, kind=kind)
                        changed = True
                    else:
                        owner_blocks[owner] = entry.raw
                    continue

                if move_orphans:
                    targets = {target for target in redirects.get(owner, set()) if target in desired_tags}
                    if len(targets) == 1:
                        target = next(iter(targets))
                        renamed = self.rename_region_state_block(entry.raw, owner, target)
                        if target in owner_blocks:
                            owner_blocks[target] = self.merge_region_state_blocks(
                                owner_blocks[target],
                                renamed,
                                kind=kind,
                            )
                        else:
                            owner_blocks[target] = renamed
                        warnings.append(f"Moved orphan {kind} region_state:{owner} to region_state:{target} in {state_id}.")
                        changed = True
                        continue

                if self.region_state_has_entries(entry.raw):
                    warnings.append(f"Removed orphan {kind} region_state:{owner} from {state_id}.")
                changed = True
                continue
            extras.append(entry.raw)

        if create_empty_missing:
            for tag in desired_order:
                if tag not in owner_blocks:
                    owner_blocks[tag] = f"\t\tregion_state:{tag} = {{\n\t\t}}"
                    changed = True

        if not owner_blocks and not extras:
            return None, warnings
        if not changed:
            return block, warnings

        lines = [f"\ts:{state_id} = {{"]
        for tag in desired_order:
            raw = owner_blocks.pop(tag, None)
            if raw is not None:
                lines.append(vse.normalize_entry_indentation(raw.rstrip(), "\t\t"))
        for _tag, raw in owner_blocks.items():
            lines.append(vse.normalize_entry_indentation(raw.rstrip(), "\t\t"))
        for raw in extras:
            lines.append(vse.normalize_entry_indentation(raw.rstrip(), "\t\t"))
        lines.append("\t}")
        return "\n".join(lines), warnings

    def region_state_has_entries(self, raw: str) -> bool:
        return bool(vse.parse_top_level_entries(raw))

    def rename_region_state_block(self, raw: str, old: str, new: str) -> str:
        renamed = re.sub(
            rf"(?m)^(\s*)region_state:{re.escape(old)}(\s*=\s*\{{)",
            rf"\1region_state:{new}\2",
            raw,
            count=1,
        )
        renamed = re.sub(rf"\bc:{re.escape(old)}\b", f"c:{new}", renamed)
        return renamed

    def merge_region_state_blocks(self, target_raw: str, source_raw: str, kind: str) -> str:
        target_entries = vse.parse_top_level_entries(target_raw)
        source_entries = vse.parse_top_level_entries(source_raw)
        if not source_entries:
            return target_raw

        child_indent = "\t\t\t"
        target_has_kill = any(entry.key == "kill_population_percent_in_state" for entry in target_entries)
        merged_source: list[str] = []
        for entry in source_entries:
            if kind == "pops" and entry.key == "kill_population_percent_in_state" and target_has_kill:
                continue
            merged_source.append(vse.normalize_entry_indentation(entry.raw.rstrip(), child_indent))
        if not merged_source:
            return target_raw

        close_index = target_raw.rfind("}")
        if close_index == -1:
            return target_raw
        prefix = target_raw[:close_index].rstrip("\r\n")
        suffix = target_raw[close_index:]
        joiner = "\n" if prefix.rstrip().endswith("{") else "\n"
        return prefix + joiner + "\n".join(merged_source) + "\n" + suffix

    def color_for_tag(self, tag: str) -> tuple[int, int, int]:
        canonical = self.canonical_country_tag(tag)
        return self.country_colors.get(canonical) or self.country_colors.get(tag) or stable_tag_color(tag)


class C2CReshuffleApp:
    def __init__(self, root: tk.Tk, repository: C2CTagRepository) -> None:
        if not PIL_AVAILABLE:
            raise RuntimeError("Pillow and numpy are required for the visual tool.")
        self.root = root
        self.repository = repository
        self.root.title("c2c Province Tag Reshuffle")
        self.root.geometry("1280x820")
        self.root.minsize(980, 640)

        self.owner_by_province: dict[str, str] = dict(repository.history_ownership)
        self.original_owner_by_province: dict[str, str] = dict(repository.history_ownership)
        self.redirects_by_state: dict[str, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))
        self.selected_state: str | None = None
        self.selected_provinces: set[str] = set()
        self.drag_start: tuple[float, float] | None = None
        self.drag_box: int | None = None
        self.scale = 0.25
        self.pending_view_center: tuple[float, float] | None = None
        self.preview_owner_cache: dict[str, str] | None = None
        self.display_photo = None
        self.selection_photo = None
        self.render_after_id: str | None = None
        self.view_left = 0
        self.view_top = 0
        self.virtual_width = 1
        self.virtual_height = 1
        self.tile_left = 0
        self.tile_top = 0
        self.tile_right = 0
        self.tile_bottom = 0
        self.tile_packed = None
        self.tag_label_bboxes: list[tuple[int, int, int, int]] = []
        self.tag_labels_hidden = False

        self.search_var = tk.StringVar()
        self.target_tag_var = tk.StringVar()
        self.status_var = tk.StringVar(value="Ready")
        self.summary_var = tk.StringVar(value="")
        self.hover_var = tk.StringVar(value="")
        self.show_all_var = tk.BooleanVar(value=True)
        self.show_labels_var = tk.BooleanVar(value=True)
        self.history_only_var = tk.BooleanVar(value=True)
        self.clean_orphans_var = tk.BooleanVar(value=True)
        self.move_orphans_var = tk.BooleanVar(value=True)

        self.state_display: list[tuple[str, str]] = []
        self._apply_theme()
        self._build_ui()
        self.refresh_state_list()
        self.select_initial_state()

    def _apply_theme(self) -> None:
        style = ttk.Style(self.root)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        self.root.configure(bg=DARK_BG)
        style.configure(".", background=DARK_BG, foreground=DARK_FG, fieldbackground=DARK_ELEVATED)
        style.configure("TFrame", background=DARK_BG)
        style.configure("Panel.TFrame", background=DARK_PANEL)
        style.configure("TLabel", background=DARK_BG, foreground=DARK_FG)
        style.configure("Panel.TLabel", background=DARK_PANEL, foreground=DARK_FG)
        style.configure("Muted.TLabel", background=DARK_PANEL, foreground=DARK_MUTED)
        style.configure("Warning.TLabel", background=DARK_PANEL, foreground=WARNING)
        style.configure("TButton", background=DARK_ELEVATED, foreground=DARK_FG)
        style.configure("TCheckbutton", background=DARK_PANEL, foreground=DARK_FG)
        style.configure("Treeview", background=DARK_ELEVATED, fieldbackground=DARK_ELEVATED, foreground=DARK_FG)
        style.configure("Treeview.Heading", background=DARK_PANEL, foreground=DARK_FG)

    def _build_ui(self) -> None:
        outer = ttk.Panedwindow(self.root, orient=tk.HORIZONTAL)
        outer.pack(fill=tk.BOTH, expand=True)

        left = ttk.Frame(outer, style="Panel.TFrame", padding=10)
        right = ttk.Frame(outer, padding=0)
        outer.add(left, weight=0)
        outer.add(right, weight=1)

        ttk.Label(left, text="States", style="Panel.TLabel").grid(row=0, column=0, sticky="w")
        search = ttk.Entry(left, textvariable=self.search_var, width=34)
        search.grid(row=1, column=0, sticky="ew", pady=(4, 8))
        search.bind("<KeyRelease>", lambda _event: self.refresh_state_list())

        self.state_listbox = tk.Listbox(
            left,
            width=42,
            height=15,
            bg=DARK_ELEVATED,
            fg=DARK_FG,
            selectbackground=ACCENT,
            highlightthickness=1,
            highlightbackground=DARK_BORDER,
            relief=tk.FLAT,
        )
        self.state_listbox.grid(row=2, column=0, sticky="nsew")
        self.state_listbox.bind("<<ListboxSelect>>", self.on_state_select)

        ttk.Label(left, text="Owner Tags", style="Panel.TLabel").grid(row=3, column=0, sticky="w", pady=(12, 4))
        self.owner_tree = ttk.Treeview(left, columns=("tag", "count"), show="headings", height=7)
        self.owner_tree.heading("tag", text="Tag")
        self.owner_tree.heading("count", text="Provinces")
        self.owner_tree.column("tag", width=90, anchor="w")
        self.owner_tree.column("count", width=90, anchor="e")
        self.owner_tree.grid(row=4, column=0, sticky="ew")
        self.owner_tree.bind("<<TreeviewSelect>>", self.on_owner_tree_select)

        edit = ttk.Frame(left, style="Panel.TFrame")
        edit.grid(row=5, column=0, sticky="ew", pady=(12, 0))
        ttk.Label(edit, text="Target tag", style="Panel.TLabel").grid(row=0, column=0, sticky="w")
        self.target_combo = ttk.Combobox(edit, textvariable=self.target_tag_var, width=12)
        self.target_combo.grid(row=0, column=1, sticky="ew", padx=(8, 0))
        edit.columnconfigure(1, weight=1)

        buttons = ttk.Frame(left, style="Panel.TFrame")
        buttons.grid(row=6, column=0, sticky="ew", pady=(10, 0))
        ttk.Button(buttons, text="Assign Selected", command=self.assign_selected).grid(row=0, column=0, sticky="ew", pady=2)
        ttk.Button(buttons, text="Select Tag Provinces", command=self.select_owner_provinces).grid(row=1, column=0, sticky="ew", pady=2)
        ttk.Button(buttons, text="Clear Selection", command=self.clear_selection).grid(row=2, column=0, sticky="ew", pady=2)
        ttk.Button(buttons, text="Save Selected State", command=self.save_selected_state).grid(row=3, column=0, sticky="ew", pady=(10, 2))
        ttk.Button(buttons, text="Save All Changed States", command=self.save_all_changed_states).grid(row=4, column=0, sticky="ew", pady=2)
        ttk.Button(buttons, text="Reload From Disk", command=self.reload_from_disk).grid(row=5, column=0, sticky="ew", pady=2)
        buttons.columnconfigure(0, weight=1)

        options = ttk.Frame(left, style="Panel.TFrame")
        options.grid(row=7, column=0, sticky="ew", pady=(12, 0))
        ttk.Checkbutton(options, text="Show all Canada/US states", variable=self.show_all_var, command=self.schedule_render).grid(row=0, column=0, sticky="w")
        ttk.Checkbutton(options, text="History files only", variable=self.history_only_var, command=self.on_display_mode_change).grid(row=1, column=0, sticky="w")
        ttk.Checkbutton(options, text="Show selected-state tag labels", variable=self.show_labels_var, command=self.schedule_render).grid(row=2, column=0, sticky="w")
        ttk.Checkbutton(options, text="Clean orphan pop/building tags", variable=self.clean_orphans_var).grid(row=3, column=0, sticky="w")
        ttk.Checkbutton(options, text="Move orphan sections when clear", variable=self.move_orphans_var).grid(row=4, column=0, sticky="w")

        ttk.Label(left, textvariable=self.summary_var, style="Muted.TLabel", wraplength=300).grid(
            row=8, column=0, sticky="ew", pady=(12, 0)
        )
        ttk.Label(left, textvariable=self.hover_var, style="Muted.TLabel", wraplength=300).grid(
            row=9, column=0, sticky="ew", pady=(8, 0)
        )
        ttk.Label(left, textvariable=self.status_var, style="Warning.TLabel", wraplength=300).grid(
            row=10, column=0, sticky="ew", pady=(8, 0)
        )

        left.columnconfigure(0, weight=1)
        left.rowconfigure(2, weight=1)

        self.h_scroll = ttk.Scrollbar(right, orient=tk.HORIZONTAL)
        self.v_scroll = ttk.Scrollbar(right, orient=tk.VERTICAL)
        self.canvas = tk.Canvas(
            right,
            bg="#0d1117",
            highlightthickness=0,
            xscrollcommand=self.h_scroll.set,
            yscrollcommand=self.v_scroll.set,
        )
        self.h_scroll.configure(command=self.on_xscroll)
        self.v_scroll.configure(command=self.on_yscroll)
        self.h_scroll.pack(side=tk.BOTTOM, fill=tk.X)
        self.v_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self.canvas.bind("<ButtonPress-1>", self.on_left_press)
        self.canvas.bind("<B1-Motion>", self.on_left_drag)
        self.canvas.bind("<ButtonRelease-1>", self.on_left_release)
        self.canvas.bind("<Button-3>", self.on_right_click)
        self.canvas.bind("<Motion>", self.on_motion)
        self.canvas.bind("<MouseWheel>", self.on_mousewheel)
        self.canvas.bind("<Button-4>", self.on_mousewheel)
        self.canvas.bind("<Button-5>", self.on_mousewheel)
        self.canvas.bind("<ButtonPress-2>", self.start_pan)
        self.canvas.bind("<B2-Motion>", self.do_pan)
        self.canvas.bind("<Configure>", lambda _event: self.schedule_render(delay=40))

    def refresh_state_list(self) -> None:
        query = self.search_var.get().strip().lower()
        display: list[tuple[str, str]] = []
        ownership = self.display_owner_by_province()
        for state_id in sorted(self.repository.state_regions):
            if query and query not in state_id.lower():
                continue
            region = self.repository.state_regions[state_id]
            groups = self.repository.state_owner_groups(state_id, ownership)
            label = f"{state_id}  [{region.source_name}]  {format_owner_summary(groups)}"
            display.append((state_id, label))
        self.state_display = display
        self.state_listbox.delete(0, tk.END)
        for _state_id, label in display:
            self.state_listbox.insert(tk.END, label)

    def select_initial_state(self) -> None:
        preferred = "STATE_ONTARIO"
        for index, (state_id, _label) in enumerate(self.state_display):
            if state_id == preferred:
                self.state_listbox.selection_set(index)
                self.select_state(state_id)
                return
        if self.state_display:
            self.state_listbox.selection_set(0)
            self.select_state(self.state_display[0][0])

    def on_state_select(self, _event: object) -> None:
        selection = self.state_listbox.curselection()
        if not selection:
            return
        state_id = self.state_display[selection[0]][0]
        self.select_state(state_id)

    def select_state(self, state_id: str) -> None:
        self.selected_state = state_id
        self.selected_provinces.clear()
        groups = self.repository.state_owner_groups(state_id, self.display_owner_by_province())
        tags = sorted(set(groups) | set(self.repository.country_colors))
        self.target_combo.configure(values=tags)
        if groups and not self.target_tag_var.get().strip():
            self.target_tag_var.set(next(iter(groups)))
        self.refresh_owner_tree()
        self.schedule_render()
        region = self.repository.state_regions[state_id]
        kind = "master set_owner full state" if self.repository.is_custom_history_state(state_id) else "master set_owner diff"
        self.summary_var.set(f"{state_id} from {region.source_name}; save mode: {kind}.")

    def refresh_owner_tree(self) -> None:
        self.owner_tree.delete(*self.owner_tree.get_children())
        if not self.selected_state:
            return
        groups = self.repository.state_owner_groups(self.selected_state, self.display_owner_by_province())
        for tag, provinces in groups.items():
            self.owner_tree.insert("", tk.END, iid=tag, values=(tag, len(provinces)))
        self.refresh_state_list()

    def on_owner_tree_select(self, _event: object) -> None:
        selection = self.owner_tree.selection()
        if selection:
            self.target_tag_var.set(selection[0])

    def display_owner_by_province(self) -> dict[str, str]:
        if self.history_only_var.get():
            return self.owner_by_province
        if self.preview_owner_cache is None:
            ownership = dict(self.owner_by_province)
            self.repository.apply_startup_ownership_effects(ownership)
            self.preview_owner_cache = ownership
        return self.preview_owner_cache

    def invalidate_display_cache(self) -> None:
        self.preview_owner_cache = None

    def on_display_mode_change(self) -> None:
        mode = "history files" if self.history_only_var.get() else "history plus startup ownership effects"
        if self.selected_state:
            groups = self.repository.state_owner_groups(self.selected_state, self.display_owner_by_province())
            tags = sorted(set(groups) | set(self.repository.country_colors))
            self.target_combo.configure(values=tags)
        self.refresh_owner_tree()
        self.schedule_render()
        self.status_var.set(f"Map display: {mode}.")

    def schedule_render(self, delay: int = 20, replace: bool = True) -> None:
        if self.render_after_id is not None:
            if not replace:
                return
            self.root.after_cancel(self.render_after_id)
        self.render_after_id = self.root.after(delay, self.render_map)

    def render_map(self) -> None:
        self.render_after_id = None
        if self.repository.province_image is None:
            return
        bounds = self.repository.visible_map_bounds or (0, 0, *self.repository.province_image.size)
        self.view_left, self.view_top, view_right, view_bottom = bounds
        source_width = view_right - self.view_left
        source_height = view_bottom - self.view_top
        self.virtual_width = max(1, int(source_width * self.scale))
        self.virtual_height = max(1, int(source_height * self.scale))
        self.canvas.configure(scrollregion=(0, 0, self.virtual_width, self.virtual_height))
        self.restore_pending_view_center(self.virtual_width, self.virtual_height)
        self.canvas.update_idletasks()

        viewport_width = max(1, self.canvas.winfo_width())
        viewport_height = max(1, self.canvas.winfo_height())
        viewport_left = max(0, int(self.canvas.canvasx(0)))
        viewport_top = max(0, int(self.canvas.canvasy(0)))
        wanted_left = max(0, viewport_left - RENDER_MARGIN)
        wanted_top = max(0, viewport_top - RENDER_MARGIN)
        wanted_right = min(self.virtual_width, viewport_left + viewport_width + RENDER_MARGIN)
        wanted_bottom = min(self.virtual_height, viewport_top + viewport_height + RENDER_MARGIN)

        source_left = max(0, int(math.floor(wanted_left / max(self.scale, 0.0001))))
        source_top = max(0, int(math.floor(wanted_top / max(self.scale, 0.0001))))
        source_right = min(source_width, int(math.ceil(wanted_right / max(self.scale, 0.0001))))
        source_bottom = min(source_height, int(math.ceil(wanted_bottom / max(self.scale, 0.0001))))
        if source_right <= source_left or source_bottom <= source_top:
            return

        tile_left = max(0, int(source_left * self.scale))
        tile_top = max(0, int(source_top * self.scale))
        tile_right = min(self.virtual_width, max(tile_left + 1, int(math.ceil(source_right * self.scale))))
        tile_bottom = min(self.virtual_height, max(tile_top + 1, int(math.ceil(source_bottom * self.scale))))
        width = tile_right - tile_left
        height = tile_bottom - tile_top
        self.tile_left = tile_left
        self.tile_top = tile_top
        self.tile_right = tile_right
        self.tile_bottom = tile_bottom

        source = self.repository.province_image.crop(
            (
                self.view_left + source_left,
                self.view_top + source_top,
                self.view_left + source_right,
                self.view_top + source_bottom,
            )
        )
        scaled = source.resize((width, height), Image.Resampling.NEAREST)
        arr = np.asarray(scaled, dtype=np.uint8)
        packed = (
            arr[:, :, 0].astype(np.int32) << 16
        ) + (
            arr[:, :, 1].astype(np.int32) << 8
        ) + arr[:, :, 2].astype(np.int32)
        self.tile_packed = packed
        unique, inverse = np.unique(packed.reshape(-1), return_inverse=True)
        palette = np.zeros((len(unique), 3), dtype=np.uint8)
        selected_state = self.selected_state
        dim_other_states = not self.show_all_var.get()
        display_ownership = self.display_owner_by_province()

        for index, packed_value in enumerate(unique.tolist()):
            province = packed_to_province(packed_value)
            state_id = self.repository.province_to_state.get(province)
            owner = display_ownership.get(province, "")
            if state_id is None:
                palette[index] = np.array([18, 21, 26], dtype=np.uint8)
            elif selected_state and dim_other_states and state_id != selected_state:
                palette[index] = np.array([30, 34, 40], dtype=np.uint8)
            elif owner:
                palette[index] = np.array(self.repository.color_for_tag(owner), dtype=np.uint8)
            else:
                palette[index] = np.array([70, 70, 70], dtype=np.uint8)

        rendered = palette[inverse].reshape(height, width, 3)
        self.apply_selected_state_outline(rendered, packed)
        self.display_photo = ImageTk.PhotoImage(Image.fromarray(rendered))
        self.canvas.delete("all")
        self.tag_label_bboxes.clear()
        self.tag_labels_hidden = False
        self.canvas.create_image(tile_left, tile_top, image=self.display_photo, anchor="nw")
        self.update_selection_overlay()
        if self.show_labels_var.get():
            self.draw_tag_labels(tile_left, tile_top, packed, display_ownership)

    def apply_selected_state_outline(self, rendered: object, packed: object) -> None:
        if not self.selected_state:
            return
        region = self.repository.state_regions.get(self.selected_state)
        if region is None:
            return
        values = np.array([province_to_packed(province) for province in region.provinces], dtype=np.int32)
        mask = np.isin(packed, values)
        if not np.any(mask):
            return
        padded = np.pad(mask, 1, mode="constant", constant_values=False)
        interior = (
            mask
            & padded[:-2, 1:-1]
            & padded[2:, 1:-1]
            & padded[1:-1, :-2]
            & padded[1:-1, 2:]
        )
        outline = mask & ~interior
        thick = outline.copy()
        thick[1:, :] |= outline[:-1, :]
        thick[:-1, :] |= outline[1:, :]
        thick[:, 1:] |= outline[:, :-1]
        thick[:, :-1] |= outline[:, 1:]
        rendered[thick] = np.array([247, 209, 84], dtype=np.uint8)

    def selected_province_boundary_mask(self, selected_mask: object, packed: object) -> object:
        boundary = np.zeros_like(selected_mask, dtype=bool)
        boundary[1:, :] |= selected_mask[1:, :] & (packed[1:, :] != packed[:-1, :])
        boundary[:-1, :] |= selected_mask[:-1, :] & (packed[:-1, :] != packed[1:, :])
        boundary[:, 1:] |= selected_mask[:, 1:] & (packed[:, 1:] != packed[:, :-1])
        boundary[:, :-1] |= selected_mask[:, :-1] & (packed[:, :-1] != packed[:, 1:])
        return boundary

    def update_selection_overlay(self) -> None:
        self.canvas.delete("selection_overlay")
        if self.tile_packed is None or not self.selected_provinces:
            self.selection_photo = None
            return

        values = np.array([province_to_packed(province) for province in self.selected_provinces], dtype=np.int32)
        if len(values) == 1:
            selected_mask = self.tile_packed == values[0]
        else:
            selected_mask = np.isin(self.tile_packed, values)
        if not np.any(selected_mask):
            self.selection_photo = None
            return

        height, width = self.tile_packed.shape
        overlay = np.zeros((height, width, 4), dtype=np.uint8)
        overlay[selected_mask] = np.array([247, 209, 84, 92], dtype=np.uint8)
        boundary = self.selected_province_boundary_mask(selected_mask, self.tile_packed)
        overlay[boundary] = np.array([16, 20, 26, 230], dtype=np.uint8)
        self.selection_photo = ImageTk.PhotoImage(Image.fromarray(overlay, "RGBA"))
        self.canvas.create_image(
            self.tile_left,
            self.tile_top,
            image=self.selection_photo,
            anchor="nw",
            tags=("selection_overlay",),
        )
        self.canvas.tag_raise("tag_label_box")
        self.canvas.tag_raise("tag_label")
        if self.drag_box is not None:
            self.canvas.tag_raise(self.drag_box)

    def draw_tag_labels(self, tile_left: int, tile_top: int, packed: object, ownership: dict[str, str]) -> None:
        self.tag_label_bboxes.clear()
        self.tag_labels_hidden = False
        if not self.selected_state:
            return
        groups = self.repository.state_owner_groups(self.selected_state, ownership)
        for tag, provinces in groups.items():
            values = np.array([province_to_packed(province) for province in provinces], dtype=np.int32)
            mask = np.isin(packed, values)
            if not np.any(mask):
                continue
            ys, xs = np.nonzero(mask)
            x = tile_left + int(np.mean(xs))
            y = tile_top + int(np.mean(ys))
            text_id = self.canvas.create_text(
                x,
                y,
                text=tag,
                fill="#ffffff",
                font=("", 12, "bold"),
                tags=("tag_label",),
            )
            bbox = self.canvas.bbox(text_id)
            if bbox is None:
                continue
            x0, y0, x1, y1 = bbox
            label_box = (x0 - 5, y0 - 3, x1 + 5, y1 + 3)
            rect_id = self.canvas.create_rectangle(
                label_box[0],
                label_box[1],
                label_box[2],
                label_box[3],
                fill="#111820",
                outline="#f7d154",
                width=1,
                tags=("tag_label_box",),
            )
            self.tag_label_bboxes.append(label_box)
            self.canvas.tag_lower(rect_id, text_id)

    def update_label_hover(self, canvas_x: float, canvas_y: float) -> None:
        should_hide = any(
            x0 <= canvas_x <= x1 and y0 <= canvas_y <= y1
            for x0, y0, x1, y1 in self.tag_label_bboxes
        )
        if should_hide == self.tag_labels_hidden:
            return
        state = tk.HIDDEN if should_hide else tk.NORMAL
        self.canvas.itemconfigure("tag_label", state=state)
        self.canvas.itemconfigure("tag_label_box", state=state)
        self.tag_labels_hidden = should_hide

    def canvas_to_province(self, canvas_x: float, canvas_y: float) -> str | None:
        if self.repository.province_rgb is None:
            return None
        source_height, source_width = self.repository.province_rgb.shape[:2]
        src_x = int(canvas_x / max(self.scale, 0.0001)) + self.view_left
        src_y = int(canvas_y / max(self.scale, 0.0001)) + self.view_top
        if src_x < 0 or src_y < 0 or src_x >= source_width or src_y >= source_height:
            return None
        red, green, blue = self.repository.province_rgb[src_y, src_x].tolist()
        return f"x{red:02x}{green:02x}{blue:02x}"

    def render_size_for_scale(self, scale: float) -> tuple[int, int]:
        if self.repository.province_image is None:
            return (1, 1)
        left, top, right, bottom = self.repository.visible_map_bounds or (0, 0, *self.repository.province_image.size)
        return max(1, int((right - left) * scale)), max(1, int((bottom - top) * scale))

    def viewport_needs_render(self) -> bool:
        if self.display_photo is None:
            return True
        viewport_width = max(1, self.canvas.winfo_width())
        viewport_height = max(1, self.canvas.winfo_height())
        viewport_left = int(self.canvas.canvasx(0))
        viewport_top = int(self.canvas.canvasy(0))
        viewport_right = viewport_left + viewport_width
        viewport_bottom = viewport_top + viewport_height
        cushion = max(48, RENDER_MARGIN // 3)
        return (
            viewport_left < self.tile_left + cushion
            or viewport_top < self.tile_top + cushion
            or viewport_right > self.tile_right - cushion
            or viewport_bottom > self.tile_bottom - cushion
        )

    def remember_zoom_center(self, width: int, height: int) -> None:
        viewport_width = max(1, self.canvas.winfo_width())
        viewport_height = max(1, self.canvas.winfo_height())
        center_x = self.canvas.canvasx(viewport_width / 2)
        center_y = self.canvas.canvasy(viewport_height / 2)
        self.pending_view_center = (
            max(0.0, min(1.0, center_x / max(1, width))),
            max(0.0, min(1.0, center_y / max(1, height))),
        )

    def restore_pending_view_center(self, width: int, height: int) -> None:
        if self.pending_view_center is None:
            return
        rel_x, rel_y = self.pending_view_center
        self.pending_view_center = None
        self.canvas.update_idletasks()
        viewport_width = max(1, self.canvas.winfo_width())
        viewport_height = max(1, self.canvas.winfo_height())
        left = max(0.0, min(max(0, width - viewport_width), rel_x * width - viewport_width / 2))
        top = max(0.0, min(max(0, height - viewport_height), rel_y * height - viewport_height / 2))
        self.canvas.xview_moveto(left / max(1, width))
        self.canvas.yview_moveto(top / max(1, height))

    def on_left_press(self, event: tk.Event) -> str:
        self.drag_start = (self.canvas.canvasx(event.x), self.canvas.canvasy(event.y))
        if self.drag_box is not None:
            self.canvas.delete(self.drag_box)
            self.drag_box = None
        return "break"

    def on_left_drag(self, event: tk.Event) -> str:
        if self.drag_start is None:
            return "break"
        x0, y0 = self.drag_start
        x1, y1 = self.canvas.canvasx(event.x), self.canvas.canvasy(event.y)
        if self.drag_box is None:
            self.drag_box = self.canvas.create_rectangle(x0, y0, x1, y1, outline=SELECTION, width=2, dash=(5, 3))
        else:
            self.canvas.coords(self.drag_box, x0, y0, x1, y1)
        return "break"

    def on_left_release(self, event: tk.Event) -> str:
        if self.drag_start is None:
            return "break"
        start = self.drag_start
        end = (self.canvas.canvasx(event.x), self.canvas.canvasy(event.y))
        self.drag_start = None
        if self.drag_box is not None:
            self.canvas.delete(self.drag_box)
            self.drag_box = None
        if abs(start[0] - end[0]) >= 5 or abs(start[1] - end[1]) >= 5:
            self.toggle_box_selection(start, end)
        else:
            province = self.canvas_to_province(end[0], end[1])
            self.toggle_province_selection(province)
        return "break"

    def toggle_box_selection(self, start: tuple[float, float], end: tuple[float, float]) -> None:
        if self.repository.province_rgb is None or not self.selected_state:
            return
        source_height, source_width = self.repository.province_rgb.shape[:2]
        x0 = int(min(start[0], end[0]) / max(self.scale, 0.0001)) + self.view_left
        x1 = int(max(start[0], end[0]) / max(self.scale, 0.0001)) + self.view_left
        y0 = int(min(start[1], end[1]) / max(self.scale, 0.0001)) + self.view_top
        y1 = int(max(start[1], end[1]) / max(self.scale, 0.0001)) + self.view_top
        x0, x1 = max(0, x0), min(source_width - 1, x1)
        y0, y1 = max(0, y0), min(source_height - 1, y1)
        if x1 < x0 or y1 < y0:
            return
        rgb_slice = self.repository.province_rgb[y0 : y1 + 1, x0 : x1 + 1]
        packed = (
            rgb_slice[:, :, 0].astype(np.int32) << 16
        ) + (
            rgb_slice[:, :, 1].astype(np.int32) << 8
        ) + rgb_slice[:, :, 2].astype(np.int32)
        added = 0
        for value in np.unique(packed.reshape(-1)).tolist():
            province = packed_to_province(value)
            if self.repository.province_to_state.get(province) != self.selected_state:
                continue
            if province in self.selected_provinces:
                self.selected_provinces.remove(province)
            else:
                self.selected_provinces.add(province)
                added += 1
        self.status_var.set(f"Box toggled selection. Selected: {len(self.selected_provinces)}.")
        self.update_selection_overlay()

    def toggle_province_selection(self, province: str | None) -> None:
        if not province or not self.selected_state:
            return
        state_id = self.repository.province_to_state.get(province)
        owner = self.display_owner_by_province().get(province, "")
        if state_id != self.selected_state:
            self.status_var.set(f"{province} belongs to {state_id or 'no loaded state'}; select that state first.")
            return
        if province in self.selected_provinces:
            self.selected_provinces.remove(province)
            self.status_var.set(f"Deselected {province} ({owner}).")
        else:
            self.selected_provinces.add(province)
            self.status_var.set(f"Selected {province} ({owner}).")
        self.update_selection_overlay()

    def on_right_click(self, event: tk.Event) -> str:
        province = self.canvas_to_province(self.canvas.canvasx(event.x), self.canvas.canvasy(event.y))
        if not province:
            return "break"
        owner = self.display_owner_by_province().get(province, "")
        state_id = self.repository.province_to_state.get(province)
        if state_id and state_id != self.selected_state:
            self.select_state(state_id)
            self.select_state_in_list(state_id)
        if owner:
            self.target_tag_var.set(owner)
        self.status_var.set(f"Picked {province}: {state_id or 'unknown'} / {owner or 'no owner'}.")
        return "break"

    def on_motion(self, event: tk.Event) -> None:
        canvas_x = self.canvas.canvasx(event.x)
        canvas_y = self.canvas.canvasy(event.y)
        self.update_label_hover(canvas_x, canvas_y)
        province = self.canvas_to_province(canvas_x, canvas_y)
        if not province:
            self.hover_var.set("")
            return
        state_id = self.repository.province_to_state.get(province, "unknown state")
        owner = self.display_owner_by_province().get(province, "no owner")
        self.hover_var.set(f"{province}  {state_id}  {owner}")

    def on_mousewheel(self, event: tk.Event) -> str:
        delta = getattr(event, "delta", 0)
        num = getattr(event, "num", None)
        old_scale = self.scale
        steps = max(1, min(6, abs(int(delta)) // 120 if delta else 1))
        if num == 4 or delta > 0:
            self.scale = min(MAX_SCALE, self.scale * (ZOOM_FACTOR ** steps))
        elif num == 5 or delta < 0:
            self.scale = max(MIN_SCALE, self.scale / (ZOOM_FACTOR ** steps))
        if self.scale != old_scale:
            old_width, old_height = self.render_size_for_scale(old_scale)
            self.remember_zoom_center(old_width, old_height)
            self.schedule_render()
        return "break"

    def on_xscroll(self, *args: object) -> None:
        self.canvas.xview(*args)
        if self.viewport_needs_render():
            self.schedule_render(delay=12, replace=False)

    def on_yscroll(self, *args: object) -> None:
        self.canvas.yview(*args)
        if self.viewport_needs_render():
            self.schedule_render(delay=12, replace=False)

    def start_pan(self, event: tk.Event) -> str:
        self.canvas.scan_mark(event.x, event.y)
        return "break"

    def do_pan(self, event: tk.Event) -> str:
        self.canvas.scan_dragto(event.x, event.y, gain=1)
        if self.viewport_needs_render():
            self.schedule_render(delay=12, replace=False)
        return "break"

    def select_state_in_list(self, state_id: str) -> None:
        for index, (candidate, _label) in enumerate(self.state_display):
            if candidate == state_id:
                self.state_listbox.selection_clear(0, tk.END)
                self.state_listbox.selection_set(index)
                self.state_listbox.see(index)
                return

    def assign_selected(self) -> None:
        if not self.selected_state:
            return
        target = self.repository.canonical_country_tag(self.target_tag_var.get())
        if not target:
            messagebox.showerror("Missing tag", "Enter a target country tag first.")
            return
        if not self.selected_provinces:
            messagebox.showinfo("No selection", "Select one or more provinces first.")
            return

        changed = 0
        redirects = self.redirects_by_state[self.selected_state]
        for province in list(self.selected_provinces):
            if self.repository.province_to_state.get(province) != self.selected_state:
                continue
            old = self.owner_by_province.get(province, "")
            if old == target:
                continue
            if old:
                redirects[old].add(target)
            self.owner_by_province[province] = target
            changed += 1
        self.selected_provinces.clear()
        self.invalidate_display_cache()
        self.refresh_owner_tree()
        self.schedule_render()
        self.status_var.set(f"Assigned {changed} province(s) in {self.selected_state} to {target}.")

    def select_owner_provinces(self) -> None:
        if not self.selected_state:
            return
        selection = self.owner_tree.selection()
        tag = selection[0] if selection else self.repository.canonical_country_tag(self.target_tag_var.get())
        if not tag:
            return
        self.selected_provinces.clear()
        region = self.repository.state_regions[self.selected_state]
        display_ownership = self.display_owner_by_province()
        for province in region.provinces:
            if display_ownership.get(province, "") == tag:
                self.selected_provinces.add(province)
        self.status_var.set(f"Selected {len(self.selected_provinces)} province(s) owned by {tag}.")
        self.update_selection_overlay()

    def clear_selection(self) -> None:
        self.selected_provinces.clear()
        self.update_selection_overlay()
        self.status_var.set("Selection cleared.")

    def changed_state_ids(self) -> list[str]:
        changed: set[str] = set()
        province_ids = set(self.owner_by_province) | set(self.original_owner_by_province)
        for province in province_ids:
            if self.owner_by_province.get(province, "") == self.original_owner_by_province.get(province, ""):
                continue
            state_id = self.repository.province_to_state.get(province)
            if state_id and state_id in self.repository.state_regions:
                changed.add(state_id)
        return sorted(changed)

    def confirm_orphan_cleanup(self, state_ids: list[str]) -> bool:
        if not self.clean_orphans_var.get():
            return True

        removed_by_state: list[tuple[str, list[str]]] = []
        for state_id in state_ids:
            groups = self.repository.state_owner_groups(state_id, self.owner_by_province)
            original_tags = set(self.repository.state_owner_groups(state_id, self.original_owner_by_province))
            removed_tags = sorted(original_tags - set(groups))
            if removed_tags:
                removed_by_state.append((state_id, removed_tags))
        if not removed_by_state:
            return True

        if len(removed_by_state) == 1:
            state_id, removed_tags = removed_by_state[0]
            message = (
                f"{state_id} no longer has these owner tags: {', '.join(removed_tags)}.\n\n"
                "The tool will clean matching pop/building region_state sections in c2c history."
            )
        else:
            shown = "\n".join(
                f"{state_id}: {', '.join(removed_tags)}"
                for state_id, removed_tags in removed_by_state[:12]
            )
            extra = len(removed_by_state) - 12
            if extra > 0:
                shown += f"\n...and {extra} more state(s)."
            message = (
                "These states no longer have one or more owner tags:\n\n"
                f"{shown}\n\n"
                "The tool will clean matching pop/building region_state sections in c2c history."
            )
        return messagebox.askyesno("Clean orphan region_state sections?", message)

    def refresh_saved_state_from_disk(
        self,
        state_id: str,
        queued_ownership: dict[str, str],
        previous_original: dict[str, str],
    ) -> None:
        self.refresh_saved_states_from_disk([state_id], queued_ownership, previous_original)

    def refresh_saved_states_from_disk(
        self,
        state_ids: list[str],
        queued_ownership: dict[str, str],
        previous_original: dict[str, str],
    ) -> None:
        owner_by_province = dict(queued_ownership)
        original_owner_by_province = dict(previous_original)

        for state_id in state_ids:
            region = self.repository.state_regions.get(state_id)
            if region is None:
                continue
            for province in region.provinces:
                owner = self.repository.history_ownership.get(province, "")
                if owner:
                    owner_by_province[province] = owner
                    original_owner_by_province[province] = owner
                else:
                    owner_by_province.pop(province, None)
                    original_owner_by_province.pop(province, None)

        self.owner_by_province = owner_by_province
        self.original_owner_by_province = original_owner_by_province

    def save_current_state(self) -> None:
        self.save_selected_state()

    def save_selected_state(self) -> None:
        if not self.selected_state:
            return
        self.save_states([self.selected_state])

    def save_all_changed_states(self) -> None:
        state_ids = self.changed_state_ids()
        if not state_ids:
            messagebox.showinfo("No session changes", "No states have ownership changes queued in this session.")
            return
        self.save_states(state_ids)

    def save_states(self, state_ids: list[str]) -> None:
        state_ids = [state_id for state_id in state_ids if state_id in self.repository.state_regions]
        if not state_ids:
            return

        for state_id in state_ids:
            groups = self.repository.state_owner_groups(state_id, self.owner_by_province)
            if not groups:
                messagebox.showerror("No owners", f"{state_id} has no owner tags to save.")
                return
        if not self.confirm_orphan_cleanup(state_ids):
            return

        queued_ownership = dict(self.owner_by_province)
        previous_original = dict(self.original_owner_by_province)
        result = SaveResult()
        saved_states: list[str] = []
        try:
            for state_id in state_ids:
                state_result = self.repository.save_state(
                    state_id,
                    self.owner_by_province,
                    self.redirects_by_state.get(state_id, {}),
                    move_orphans=self.move_orphans_var.get(),
                    clean_orphans=self.clean_orphans_var.get(),
                )
                result.add(state_result)
                saved_states.append(state_id)
        except Exception as exc:
            if saved_states:
                self.repository.load(load_image=False)
                self.refresh_saved_states_from_disk(saved_states, queued_ownership, previous_original)
                self.invalidate_display_cache()
                for state_id in saved_states:
                    self.redirects_by_state.pop(state_id, None)
                self.selected_provinces.clear()
                self.refresh_state_list()
                if self.selected_state and self.selected_state in self.repository.state_regions:
                    self.select_state(self.selected_state)
                    self.select_state_in_list(self.selected_state)
            messagebox.showerror("Save failed", f"{exc}\n\nSaved before failure: {len(saved_states)} state(s).")
            return

        self.repository.load(load_image=False)
        self.refresh_saved_states_from_disk(saved_states, queued_ownership, previous_original)
        self.invalidate_display_cache()
        for state_id in saved_states:
            self.redirects_by_state.pop(state_id, None)
        self.selected_provinces.clear()
        self.refresh_state_list()
        if self.selected_state and self.selected_state in self.repository.state_regions:
            self.select_state(self.selected_state)
            self.select_state_in_list(self.selected_state)
        else:
            self.refresh_owner_tree()
            self.schedule_render()
        changed = ", ".join(path.name for path in sorted(result.changed_files, key=lambda item: item.name)) or "no files"
        warning_text = "\n".join(result.warnings[:6])
        state_label = saved_states[0] if len(saved_states) == 1 else f"{len(saved_states)} states"
        self.status_var.set(f"Saved {state_label}: {changed}.")
        if result.warnings:
            messagebox.showwarning("Saved with cleanup notes", warning_text)
        else:
            messagebox.showinfo("Saved", f"Saved {state_label}.\nChanged: {changed}.")

    def reload_from_disk(self) -> None:
        selected = self.selected_state
        self.repository.load(load_image=False)
        self.owner_by_province = dict(self.repository.history_ownership)
        self.original_owner_by_province = dict(self.repository.history_ownership)
        self.invalidate_display_cache()
        self.redirects_by_state.clear()
        self.selected_provinces.clear()
        self.refresh_state_list()
        if selected and selected in self.repository.state_regions:
            self.select_state(selected)
            self.select_state_in_list(selected)
        self.status_var.set("Reloaded from disk.")


def build_repository(args: argparse.Namespace) -> C2CTagRepository:
    repo_root = Path(args.repo).resolve() if args.repo else repo_root_from_script()
    game_root = Path(args.game_root).resolve() if args.game_root else DEFAULT_GAME_ROOT
    upstream = Path(args.upstream_mod).resolve() if args.upstream_mod else DEFAULT_USFP_ROOT
    repository = C2CTagRepository(repo_root, game_root if game_root.exists() else None, upstream)
    repository.load(load_image=not args.check)
    return repository


def run_check(repository: C2CTagRepository) -> int:
    province_total = sum(len(region.provinces) for region in repository.state_regions.values())
    assigned = sum(
        1
        for region in repository.state_regions.values()
        for province in region.provinces
        if province in repository.ownership
    )
    unknown = province_total - assigned
    print(f"State regions: {len(repository.state_regions)}")
    print(f"Canada/US strategic states: {len(repository.relevant_state_ids)}")
    print(f"State provinces: {province_total}")
    print(f"Owned provinces: {assigned}")
    print(f"Unowned/unknown provinces: {unknown}")
    full_history_states = sum(1 for state_id in repository.state_regions if repository.is_custom_history_state(state_id))
    print(f"Full-history set_owner states: {full_history_states}")
    print(f"Legacy create_state states read: {len(repository.custom_state_ids)}")
    print(f"Loaded sources: {', '.join(source.name for source in repository.sources)}")
    print(f"State history output: {repository.state_history_path}")
    print(f"Pop output: {repository.pop_path}")
    print(f"Building output: {repository.building_path}")
    return 0 if repository.state_regions and assigned else 1


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="c2c province tag reshuffle history editor")
    parser.add_argument("--repo", default=None, help="Repository root. Defaults to the parent of script/.")
    parser.add_argument("--game-root", default=str(DEFAULT_GAME_ROOT), help="Victoria 3 install root.")
    parser.add_argument("--upstream-mod", default=str(DEFAULT_USFP_ROOT), help="Optional USFP/Hail, Columbia! root.")
    parser.add_argument("--check", action="store_true", help="Load data and print a summary instead of opening the GUI.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    repository = build_repository(args)
    if args.check:
        return run_check(repository)
    if not PIL_AVAILABLE:
        print("Pillow and numpy are required for the GUI.", file=sys.stderr)
        return 2
    root = tk.Tk()
    C2CReshuffleApp(root, repository)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
