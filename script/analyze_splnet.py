#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import struct
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path


NODE_SECTION_SPECIAL_PREFIX = (4, 1524, 1, 3)
SPLINE_SECTION_SPECIAL_PREFIX = (4, 4, 1525, 1, 3, 3, 11, 1)
METADATA_SECTION_SPECIAL_PREFIX = (4, 4, 1526, 1, 3, 3, 11, 1)
REGULAR_RECORD_PREFIX = (4, 3, 11, 1, 668)
NEXT_SECTION_PREFIX = (4, 4, 1526, 1, 3)


@dataclass(frozen=True)
class NodeRecord:
    record_id: int
    x: float
    y: float
    raw_words: tuple[int, ...]


@dataclass(frozen=True)
class SplineRecord:
    record_id: int
    node_ids: tuple[int, ...]
    raw_words: tuple[int, ...]


@dataclass(frozen=True)
class MetadataRecord:
    record_id: int
    field_a: int
    field_b: int | None
    raw_words: tuple[int, ...]


@dataclass(frozen=True)
class SplnetFile:
    path: Path
    header_counts: tuple[int, int, int]
    nodes: list[NodeRecord]
    splines: list[SplineRecord]
    metadata: list[MetadataRecord]

    @property
    def node_map(self) -> dict[int, NodeRecord]:
        return {record.record_id: record for record in self.nodes}

    @property
    def spline_map(self) -> dict[int, SplineRecord]:
        return {record.record_id: record for record in self.splines}

    @property
    def metadata_map(self) -> dict[int, MetadataRecord]:
        return {record.record_id: record for record in self.metadata}


def _u32(low_word: int, high_word: int) -> int:
    return low_word + (high_word << 16)


def _f32(low_word: int, high_word: int) -> float:
    return struct.unpack("<f", struct.pack("<HH", low_word, high_word))[0]


def _read_words(path: Path) -> tuple[int, ...]:
    data = path.read_bytes()
    if len(data) % 2:
        raise ValueError(f"{path} does not have an even byte length")
    return struct.unpack("<" + "H" * (len(data) // 2), data)


def _find_next_record_start(
    words: tuple[int, ...],
    start_index: int,
    prefixes: tuple[tuple[int, ...], ...],
) -> int:
    longest = max(len(prefix) for prefix in prefixes)
    for index in range(start_index + 1, len(words) - longest + 1):
        if words[index - 1] != 4:
            continue
        for prefix in prefixes:
            if words[index : index + len(prefix)] == prefix:
                return index
    return len(words)


def _parse_node_record(raw_words: tuple[int, ...]) -> NodeRecord:
    if raw_words[:4] == NODE_SECTION_SPECIAL_PREFIX:
        record_id = _u32(raw_words[8], raw_words[9])
        x = _f32(raw_words[14], raw_words[15])
        y = _f32(raw_words[17], raw_words[18])
    else:
        record_id = _u32(raw_words[5], raw_words[6])
        x = _f32(raw_words[11], raw_words[12])
        y = _f32(raw_words[14], raw_words[15])
    return NodeRecord(record_id=record_id, x=x, y=y, raw_words=raw_words)


def _parse_spline_record(raw_words: tuple[int, ...]) -> SplineRecord:
    if raw_words[:8] == SPLINE_SECTION_SPECIAL_PREFIX:
        record_id = _u32(raw_words[9], raw_words[10])
        node_start = 16
    else:
        record_id = _u32(raw_words[5], raw_words[6])
        node_start = 12
    node_ids: list[int] = []
    index = node_start
    while index + 2 < len(raw_words):
        if raw_words[index] == 20:
            node_ids.append(_u32(raw_words[index + 1], raw_words[index + 2]))
            index += 3
            continue
        index += 1
    return SplineRecord(record_id=record_id, node_ids=tuple(node_ids), raw_words=raw_words)


def _parse_metadata_record(raw_words: tuple[int, ...]) -> MetadataRecord:
    if raw_words[:8] == METADATA_SECTION_SPECIAL_PREFIX:
        record_id = _u32(raw_words[9], raw_words[10])
        field_a = _u32(raw_words[11], raw_words[12])
        field_b = _u32(raw_words[17], raw_words[18]) if len(raw_words) > 18 else None
    else:
        record_id = _u32(raw_words[5], raw_words[6])
        field_a = _u32(raw_words[7], raw_words[8])
        field_b = _u32(raw_words[13], raw_words[14]) if len(raw_words) > 14 else None
    return MetadataRecord(
        record_id=record_id,
        field_a=field_a,
        field_b=field_b,
        raw_words=raw_words,
    )


def load_splnet(path: Path) -> SplnetFile:
    words = _read_words(path)
    if words[:2] != (238, 1):
        raise ValueError(f"{path} does not start with the expected splnet header")

    node_count = words[9]
    spline_count = words[12]
    metadata_count = words[15]

    index = 17

    node_records: list[NodeRecord] = []
    node_records.append(_parse_node_record(tuple(words[index : index + 20])))
    index += 20
    for _ in range(node_count - 1):
        node_records.append(_parse_node_record(tuple(words[index : index + 17])))
        index += 17

    spline_records: list[SplineRecord] = []
    for _ in range(spline_count):
        next_index = _find_next_record_start(
            words,
            index,
            prefixes=(REGULAR_RECORD_PREFIX, NEXT_SECTION_PREFIX),
        )
        spline_records.append(_parse_spline_record(tuple(words[index:next_index])))
        index = next_index

    metadata_records: list[MetadataRecord] = []
    for _ in range(metadata_count):
        next_index = _find_next_record_start(words, index, prefixes=(REGULAR_RECORD_PREFIX,))
        metadata_records.append(_parse_metadata_record(tuple(words[index:next_index])))
        index = next_index

    return SplnetFile(
        path=path,
        header_counts=(node_count, spline_count, metadata_count),
        nodes=node_records,
        splines=spline_records,
        metadata=metadata_records,
    )


def _bbox(points: list[tuple[float, float]]) -> dict[str, float] | None:
    if not points:
        return None
    xs = [point[0] for point in points]
    ys = [point[1] for point in points]
    return {
        "min_x": min(xs),
        "min_y": min(ys),
        "max_x": max(xs),
        "max_y": max(ys),
    }


def _record_length_stats(records: list[NodeRecord | SplineRecord | MetadataRecord]) -> dict[str, object]:
    lengths = Counter(len(record.raw_words) for record in records)
    return {
        "min_words": min(lengths),
        "max_words": max(lengths),
        "by_length": dict(sorted(lengths.items())),
    }


def summarize(splnet: SplnetFile) -> dict[str, object]:
    return {
        "path": str(splnet.path),
        "header_counts": {
            "nodes": splnet.header_counts[0],
            "splines": splnet.header_counts[1],
            "metadata": splnet.header_counts[2],
        },
        "node_bounds": _bbox([(record.x, record.y) for record in splnet.nodes]),
        "node_record_lengths": _record_length_stats(splnet.nodes),
        "spline_record_lengths": _record_length_stats(splnet.splines),
        "metadata_record_lengths": _record_length_stats(splnet.metadata),
    }


def diff(base: SplnetFile, modded: SplnetFile) -> dict[str, object]:
    base_nodes = base.node_map
    mod_nodes = modded.node_map
    base_splines = base.spline_map
    mod_splines = modded.spline_map
    added_node_ids = sorted(set(mod_nodes) - set(base_nodes))
    removed_node_ids = sorted(set(base_nodes) - set(mod_nodes))
    moved_node_ids = sorted(
        record_id
        for record_id in set(base_nodes) & set(mod_nodes)
        if (base_nodes[record_id].x, base_nodes[record_id].y)
        != (mod_nodes[record_id].x, mod_nodes[record_id].y)
    )

    added_spline_ids = sorted(set(mod_splines) - set(base_splines))
    removed_spline_ids = sorted(set(base_splines) - set(mod_splines))
    changed_spline_ids = sorted(
        record_id
        for record_id in set(base_splines) & set(mod_splines)
        if base_splines[record_id].node_ids != mod_splines[record_id].node_ids
    )

    base_metadata_records = Counter(record.raw_words for record in base.metadata)
    mod_metadata_records = Counter(record.raw_words for record in modded.metadata)
    added_metadata_records = sum((mod_metadata_records - base_metadata_records).values())
    removed_metadata_records = sum((base_metadata_records - mod_metadata_records).values())

    added_node_refs: defaultdict[int, int] = defaultdict(int)
    removed_node_refs: defaultdict[int, int] = defaultdict(int)
    unchanged_node_refs: defaultdict[int, int] = defaultdict(int)

    for spline_id, record in mod_splines.items():
        target = unchanged_node_refs if spline_id in base_splines else added_node_refs
        for node_id in record.node_ids:
            target[node_id] += 1

    for spline_id, record in base_splines.items():
        if spline_id in mod_splines:
            continue
        for node_id in record.node_ids:
            removed_node_refs[node_id] += 1

    patch_points: list[tuple[float, float]] = []
    patch_points.extend((mod_nodes[node_id].x, mod_nodes[node_id].y) for node_id in added_node_ids)
    patch_points.extend((mod_nodes[node_id].x, mod_nodes[node_id].y) for node_id in moved_node_ids)
    patch_points.extend((base_nodes[node_id].x, base_nodes[node_id].y) for node_id in removed_node_ids)

    return {
        "base_path": str(base.path),
        "modded_path": str(modded.path),
        "base_header_counts": {
            "nodes": base.header_counts[0],
            "splines": base.header_counts[1],
            "metadata": base.header_counts[2],
        },
        "modded_header_counts": {
            "nodes": modded.header_counts[0],
            "splines": modded.header_counts[1],
            "metadata": modded.header_counts[2],
        },
        "nodes": {
            "added": len(added_node_ids),
            "removed": len(removed_node_ids),
            "moved": len(moved_node_ids),
            "added_ids_sample": added_node_ids[:25],
            "removed_ids_sample": removed_node_ids[:25],
            "moved_ids_sample": moved_node_ids[:25],
        },
        "splines": {
            "added": len(added_spline_ids),
            "removed": len(removed_spline_ids),
            "changed_existing": len(changed_spline_ids),
            "added_ids_sample": added_spline_ids[:25],
            "removed_ids_sample": removed_spline_ids[:25],
            "changed_ids_sample": changed_spline_ids[:25],
        },
        "metadata": {
            "added_raw_records": added_metadata_records,
            "removed_raw_records": removed_metadata_records,
            "note": "Metadata records are diffed by raw chunk because their primary IDs are not fully unique.",
        },
        "patch_bbox": _bbox(patch_points),
        "mergeability_checks": {
            "added_nodes_only_used_by_added_splines": all(
                added_node_refs[node_id] > 0
                and removed_node_refs[node_id] == 0
                and unchanged_node_refs[node_id] == 0
                for node_id in added_node_ids
            ),
            "removed_nodes_only_used_by_removed_splines": all(
                removed_node_refs[node_id] > 0
                and added_node_refs[node_id] == 0
                and unchanged_node_refs[node_id] == 0
                for node_id in removed_node_ids
            ),
            "moved_nodes_not_used_by_unchanged_splines": all(
                unchanged_node_refs[node_id] == 0 for node_id in moved_node_ids
            ),
        },
    }


def _print_summary(summary: dict[str, object]) -> None:
    counts = summary["header_counts"]
    bbox = summary["node_bounds"]
    print(summary["path"])
    print(
        "  Header counts:"
        f" nodes={counts['nodes']}"
        f" splines={counts['splines']}"
        f" metadata={counts['metadata']}"
    )
    if bbox is None:
        print("  Node bounds: none")
    else:
        print(
            "  Node bounds:"
            f" x=[{bbox['min_x']:.3f}, {bbox['max_x']:.3f}]"
            f" y=[{bbox['min_y']:.3f}, {bbox['max_y']:.3f}]"
        )
    print(
        "  Record lengths:"
        f" nodes={summary['node_record_lengths']['by_length']}"
        f" splines={summary['spline_record_lengths']['by_length']}"
        f" metadata={summary['metadata_record_lengths']['by_length']}"
    )


def _print_diff(summary: dict[str, object]) -> None:
    print(summary["base_path"])
    print(summary["modded_path"])
    print(
        "  Counts:"
        f" base={summary['base_header_counts']}"
        f" modded={summary['modded_header_counts']}"
    )
    print(
        "  Nodes:"
        f" +{summary['nodes']['added']}"
        f" -{summary['nodes']['removed']}"
        f" moved={summary['nodes']['moved']}"
    )
    print(
        "  Splines:"
        f" +{summary['splines']['added']}"
        f" -{summary['splines']['removed']}"
        f" changed_existing={summary['splines']['changed_existing']}"
    )
    print(
        "  Metadata raw records:"
        f" +{summary['metadata']['added_raw_records']}"
        f" -{summary['metadata']['removed_raw_records']}"
    )
    bbox = summary["patch_bbox"]
    if bbox is not None:
        print(
            "  Patch bbox:"
            f" x=[{bbox['min_x']:.3f}, {bbox['max_x']:.3f}]"
            f" y=[{bbox['min_y']:.3f}, {bbox['max_y']:.3f}]"
        )
    checks = summary["mergeability_checks"]
    print("  Mergeability checks:")
    for key, value in checks.items():
        print(f"    {key}={value}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Inspect Victoria 3 spline_network.splnet files.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    summary_parser = subparsers.add_parser("summary", help="Print a structural summary of a splnet file.")
    summary_parser.add_argument("path", type=Path)
    summary_parser.add_argument("--json", action="store_true", dest="as_json")

    diff_parser = subparsers.add_parser("diff", help="Compare a modded splnet file against a base file.")
    diff_parser.add_argument("base_path", type=Path)
    diff_parser.add_argument("modded_path", type=Path)
    diff_parser.add_argument("--json", action="store_true", dest="as_json")

    args = parser.parse_args()

    if args.command == "summary":
        result = summarize(load_splnet(args.path))
        if args.as_json:
            print(json.dumps(result, indent=2, sort_keys=True))
        else:
            _print_summary(result)
        return

    result = diff(load_splnet(args.base_path), load_splnet(args.modded_path))
    if args.as_json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        _print_diff(result)


if __name__ == "__main__":
    main()
