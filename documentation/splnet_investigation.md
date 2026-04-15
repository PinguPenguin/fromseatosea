# `spline_network.splnet` Investigation

## Bottom line

Victoria 3 appears to load road splines from a single binary asset at:

- Vanilla: `game/gfx/map/spline_network/spline_network.splnet`
- Mod override: `mod/gfx/map/spline_network/spline_network.splnet`

There is no sign in the shipped files of a native "load several regional `.splnet` files" workflow. So the practical path to mod compatibility is not to split the asset inside the game, but to build a merger that combines multiple mods into one final `spline_network.splnet` before launch or before packaging a compatibility patch.

## What the file looks like

This file is not compressed garbage; it is a structured tagged binary container.

The header stores three counts:

- Vanilla counts: `34828 / 4291 / 4289`
- This mod's counts: `35998 / 4398 / 4395`

The body then breaks into three record tables:

1. Node table
   Contains an integer ID plus two `float32` coordinates.
2. Spline table
   Contains an integer ID plus a variable-length list of node IDs.
3. Metadata table
   Contains a spline-linked ID plus two additional integer fields. The exact semantics are still unclear, but the records can still be preserved and merged by raw chunk.

`script/analyze_splnet.py` now parses these tables well enough to summarize and diff `.splnet` files.

## What changed in this mod vs vanilla

Using the new parser against vanilla and the mod copy:

- Nodes: `+2086 / -916 / moved 54`
- Splines: `+181 / -74 / changed_existing 0`
- Metadata raw records: `+180 / -74`
- Patch bounding box: roughly `x=760..2928`, `y=2533..3259`

The important compatibility finding is that the diff is cleaner than a raw binary replacement suggests:

- Every added node is only referenced by added splines.
- Every removed node is only referenced by removed splines.
- Every moved node is only referenced by added/removed splines, not by unchanged vanilla splines.
- Shared spline IDs were not edited in place; they were added/removed instead.
- The metadata table does not have fully unique primary IDs, so it should be merged as raw record chunks rather than as a simple keyed map.

That means a merger can treat most spline edits as record-level additions and removals, rather than trying to rewrite the whole network blindly.

## Practical compatibility strategy

The recommended approach is a build-time merger:

1. Parse vanilla `.splnet` into nodes, splines, and metadata records.
2. Parse each mod's `.splnet`.
3. Convert each mod into a patch against vanilla:
   - add/remove/move nodes
   - add/remove splines
   - add/remove metadata records
4. Merge patches from multiple mods.
5. Re-emit one final `spline_network.splnet`.

This can work even before the exact meaning of the metadata table is fully decoded, because the merger can preserve added metadata records as raw binary chunks and remove records by ID.

## What will and will not work

Will likely work:

- A standalone merger script.
- Per-region patch files in JSON or another text format that are compiled back into one `.splnet`.
- Compatibility rules based on spline IDs, node IDs, and spatial bounding boxes.

Will likely not work:

- Shipping several `.splnet` files side by side and hoping the game merges them.
- Breaking the file into regional chunks without an external rebuild step.
- Blind binary concatenation without updating counts and preserving cross-references.

## Authoring rules that would make future merges easier

If you want multiple mods to coexist, the safest conventions are:

- Treat vanilla nodes as immutable whenever possible.
- For new routes, allocate new node IDs and new spline IDs instead of reusing vanilla IDs.
- When replacing a vanilla route, prefer:
  - remove the old spline record
  - add new spline records
  - add new nodes for the replacement geometry
- Avoid moving a node that is still referenced by unchanged splines.

Your current Canada changes are already close to this pattern, which is why a merger looks realistic here.

## Useful commands

Summary:

```powershell
python script/analyze_splnet.py summary mod/gfx/map/spline_network/spline_network.splnet
```

Diff against vanilla:

```powershell
python script/analyze_splnet.py diff "C:/Program Files (x86)/Steam/steamapps/common/Victoria 3/game/gfx/map/spline_network/spline_network.splnet" mod/gfx/map/spline_network/spline_network.splnet
```
