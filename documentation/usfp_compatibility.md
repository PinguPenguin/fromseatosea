# USFP Compatibility Notes

This pass treats `Hail, Columbia!` as a dependency that loads before c2c.

## Implemented

- `mod/common/history/states/zz_c2c_usfp_history_compat.txt` reapplies the province-owner changes from `usfp_history_states_canada.txt` and `usfp_history_states_natives.txt` onto c2c's split Canadian states.
- `zz_c2c_usfp_history_compat.txt` also restores USFP owners whose vanilla provinces land in c2c custom states, including `usfp_ALG`, `usfp_ATK`, and `usfp_TSI`.
- `mod/common/on_actions/c2c_on_actions.txt` now reapplies the BC and western-north owners that c2c's startup cleanup would otherwise overwrite.
- `mod/common/history/pops/zz_c2c_history_pops.txt` loads after USFP pop history and wipes the vanilla-state region-state populations c2c overrides before recreating c2c's values.
- `zz_c2c_history_pops.txt` splits USFP native pop history across c2c custom states and ports USFP's Quebec/Ontario native pop moves onto the c2c split-state layout.

## Common Overrides

- State history:
  c2c `c2c_history_states_override.txt` and `c2c_history_states_custom.txt`
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
