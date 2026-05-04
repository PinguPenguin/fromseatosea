# Script Directory

This folder is organized by purpose:

- `analysis/`: read-only investigation and reporting helpers.
- `localization/`: localization cloning scripts and their input lists.
- `tools/`: larger Python tools used to inspect or edit c2c data.
- `launchers/`: Windows entry points for the GUI/workflow tools.

Prefer adding new scripts to one of these folders instead of the `script/`
root. If a tool is meant to be double-clicked on Windows, put the implementation
in `tools/` and add a small launcher in `launchers/`.
