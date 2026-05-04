# USFP Compatibility Notes

This pass treats `Hail, Columbia!` as a dependency that loads before c2c.

## Implemented

- `mod/common/history/states/zz_c2c_history_states.txt` is the single c2c state-history master file. It contains c2c custom-state creation, vanilla-state owner diffs, USFP compatibility owner assignments, state claims, and homelands.
- `zz_c2c_history_states.txt` reapplies the province-owner changes from `usfp_history_states_canada.txt` and `usfp_history_states_natives.txt` onto c2c's split Canadian states, including USFP owners whose vanilla provinces land in c2c custom states.
- `zz_c2c_history_states.txt` also pre-applies USFP's northern startup owner cleanup in Northwest Territories, Nunavut, and Yukon so USFP does not need to convert c2c HBC/ATB shell region_states at game start.
- `mod/common/on_actions/c2c_on_actions.txt` dispatches c2c startup cleanup through `mod/common/scripted_effects/c2c_map_startup_effect.txt`, mirroring USFP's `usfp_map_startup_effect` pattern for callable map-startup compatibility.
- `c2c_map_startup_effect.txt` preserves USFP's `NEW` Newfoundland colony when that tag exists by transferring both c2c `STATE_NEWFOUNDLAND` and split `STATE_LABRADOR` to `NEW` after map history has loaded.
- `mod/common/history/pops/zz_c2c_history_pops.txt` loads after USFP pop history and wipes the vanilla-state region-state populations c2c overrides before recreating c2c's values.
- `zz_c2c_history_pops.txt` splits USFP native pop history across c2c custom states and ports USFP's Quebec/Ontario native pop moves onto the c2c split-state layout.
- `zz_c2c_history_pops.txt` also fills persistent owner-only c2c/USFP northern region_states found by auditing final province ownership against pop history: `IRC` in Athabasca, `CPW` in Keewatin, `DGB`/`GWC`/`INV`/`STU`/`SVY` in Northwest Territories, `INV` in Nunavut, and `GWC`/`TLT`/`TTC`/`usfp_IPQ` in Yukon. It also fills the pre-startup one-province `NEW` Labrador shell before `c2c_map_startup_effect` consolidates Newfoundland and Labrador under `NEW`. The deliberate one-province startup-transfer shells in British Columbia and Ontario remain unpopulated because `c2c_map_startup_effect` immediately collapses them.

## Common Overrides

- State history:
  c2c `zz_c2c_history_states.txt`
  overlap USFP `usfp_history_states_canada.txt`, `usfp_history_states_natives.txt`, and `usfp_history_state_claims.txt`.
  Province-owner compatibility is now handled.
  Remaining merge candidate: split the USFP Canadian claims onto c2c's custom states instead of leaving them on unsplit vanilla regions.

- Journal entries:
  c2c `c2c_canada_australia_override.txt` and USFP `usfp_canada.txt` both replace `je_canada_can` and `je_canada_gbr`.
  Because c2c loads later, it currently discards USFP's `calc_true_if >= 7` confederation logic and the `change_tag = CAN` effect.
  Proposed merge: rebuild USFP's completion/effect logic against c2c's split-state list.

- Confederation events:
  c2c still triggers USFP `can_aus.5`, while c2c overrides `can_aus.6`.
  `can_aus.5` still works against vanilla-style regions like `STATE_BRITISH_COLUMBIA`, `STATE_ONTARIO`, `STATE_QUEBEC`, `STATE_SASKATCHEWAN`, and `STATE_ALBERTA`, so it likely misses some USFP tags once c2c's split states are in play.
  Proposed merge: add a c2c-side override for `can_aus.5`.

- Pop history:
  c2c `zz_c2c_history_pops.txt` overlaps USFP `usfp_history_native_pops.txt` in `STATE_ALBERTA`, `STATE_BRITISH_COLUMBIA`, `STATE_MANITOBA`, `STATE_NORTHWEST_TERRITORIES`, `STATE_NUNAVUT`, `STATE_ONTARIO`, `STATE_QUEBEC`, and `STATE_SASKATCHEWAN`.
  c2c also overlaps USFP `usfp_history_natives_extra_pops.txt` in `STATE_NEW_BRUNSWICK`.
  Handled by loading c2c's pop history after USFP, using `kill_population_percent_in_state` in c2c's vanilla-state region-state blocks, and recreating USFP native pops in c2c's custom state regions.
  Remaining balance candidate: old c2c HBC/ORG/ATB settler-heavy blocks are still gameplay-inflated for 1836 and should be reviewed separately before a full historical rebalance.

- Building history:
  No direct Canadian overlap found between c2c `c2c_history_buildings.txt` and USFP `usfp_history_buildings.txt`.

- State traits:
  No direct Canadian overlap found between c2c state-trait files and USFP `usfp_state_traits.txt`.
