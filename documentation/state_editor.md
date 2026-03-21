# State Editor

`script/vic3_state_editor.py` is a standalone Tkinter editor for manually adjusting Canadian state demographics and state-level resources in this mod.

## What it edits

- Population history in `mod/common/history/pops`
- State resources in `mod/map_data/state_regions`
- Split states with multiple `region_state:TAG` owner slices

It reads ownership from `mod/common/history/states` so split states are shown as separate owner tabs.

## How to run

From the repository root:

```powershell
python script\vic3_state_editor.py
```

Or on Windows:

```powershell
script\launch_state_editor.bat
```

## Useful options

```powershell
python script\vic3_state_editor.py --check
```

`--check` loads the repository, reports what the tool sees, and exits without opening the GUI.

## Notes

- The default state list is filtered to the Canadian states currently used by this mod.
- Use `Show all loaded states` in the GUI if you need to inspect everything the loader can parse.
- The tool edits the currently effective state block for each state. If duplicate state or pop blocks exist in multiple files, it will use the last-loaded one and show a warning in the UI.
- Population rows are merged by identical `culture + religion` on save, and zero-sized rows are dropped.
- If a state has no pop block yet, saving it will create a new per-state file under `mod/common/history/pops`.
