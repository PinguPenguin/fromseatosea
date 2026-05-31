# Canada Flavour Mod Integration Audit

Source archive: `Canada Flavour Mod.rar`

The archive is Thomas's unreleased and work-in-progress Canada Flavour Mod (CFM). CFM was built against vanilla Victoria 3, so it was not imported wholesale. The integration below keeps C2C as the owner of load-order-sensitive Canadian content and adapts usable CFM ideas into `c2c_`-prefixed definitions.

## Integrated as C2C Content

- Responsible government journal entry, buttons, events, law, and election-law restrictions.
- Family Compact journal entry, progress bar, events, amendments, modifiers, and interest group naming.
- Canadian rebellion journal entry and stable monthly/event flavor.
- Act of Union decision and event, with placeholder modifiers replaced and no direct vanilla map override.
- Canadian colonial ideologies: Canadian Reformer, Clear Grit, Patriote, and Colonial Moralist.
- Selected CFM character additions for Upper Canada, Lower Canada, and Nova Scotia.
- Chateau Clique journal entry, events, and placeholder outcome modifier for Lower Canada.
- Representation by Population journal entry as a C2C-prefixed placeholder after the Act of Union.
- CFM's Canada party flavor, rebased onto current vanilla party definitions instead of using CFM's old full copy.
- George Brown and Lord Durham character event scaffolds, with C2C-prefixed templates replacing missing CFM templates.
- Vote of No Confidence event, scoped to Canadian countries instead of being broad global political behavior.
- John Robinson and John Strachan DNA data from CFM.
- CFM concepts, messages, and localization under C2C keys.
- CFM's confederation journal entry, conference button, invitation events, and interest tracking, adapted to replace C2C's Canada formation flow through `je_canada_can`.

## Prefix and Compatibility Changes

- CFM keys were renamed from `cfm_` or unprefixed keys to `c2c_`/`je_c2c_`/`ideology_c2c_`/`amendment_c2c_`.
- `je_responsible_government` became `je_c2c_responsible_government`.
- `law_responsible_colonial_administration` became `law_c2c_responsible_colonial_administration`.
- CFM variables such as `responsible_government_var`, `sovereignist_in_gov_timer`, and `unionact_decision` became C2C-prefixed variables.
- CFM notifications and static modifiers were C2C-prefixed to avoid collisions.
- CFM party keys were kept only where they are intended public localization keys; internal modifier descs use C2C-prefixed keys such as `from_c2c_family_compact`.

## Vanilla-Copy File Audit

- `common/history/countries/ont - ontario.txt`: CFM added appointed-executive and clergy-reserve amendments, Responsible Government, Family Compact, and Clear Grit rural folk flavor. These were integrated additively so C2C preserves current vanilla laws such as anti-strike laws instead of replacing the whole country file.
- `common/history/countries/que - quebec.txt`: CFM added Responsible Government and Chateau Clique. Both are now integrated additively, with Chateau Clique converted from placeholder `xxx` events to C2C events.
- `common/parties/cfm_parties.txt`: CFM was an old full copy of vanilla conservative/liberal parties. The actual Canada deltas were: Loyalist Tories before 1860, Liberal-Conservative Party after 1860, Reform Party for Upper Canada, and a Family Compact penalty against liberal-party attraction for conservative Upper Canadian IGs. Victoria 3 does not expose a separate party-name append hook, and workshop mods that rename vanilla party archetypes use full archetype replacements, so C2C now keeps a minimal vanilla-current replacement in `mod/common/parties/zz_c2c_canada_flavour_parties.txt`.
- `map_data/state_regions/05_north_america.txt`: CFM is an old full copy of the North America state-region file. Its meaningful Canada delta is a PEI/Nova Scotia/New Brunswick split with old resource schema and different hub/province assumptions. This conflicts with C2C's current split-state map setup and remains pending confirmation.
- `localization/english/states_l_english.yml`: Most CFM values are old/current vanilla values. The meaningful Canada delta is CFM's New Brunswick/Nova Scotia split naming; C2C already supplies New Brunswick and Nova Scotia localization for its own state setup.
- `localization/english/hub_names_l_english.yml`: Most CFM values are old/current vanilla values. The meaningful Canada deltas are CFM's PEI/Nova Scotia/New Brunswick hub names, which assume CFM's different Maritimes map split and therefore conflict with C2C's current hub placement.

## Map and Subject Assumptions Audited

- CFM's full `map_data/state_regions/05_north_america.txt` was not imported. It is a vanilla-copy file and would conflict with C2C's split Canadian state regions.
- CFM's full `states_l_english.yml` and `hub_names_l_english.yml` were not imported for the same reason.
- The Act of Union uses `annex_with_incorporation` between `c:ONT` and `c:QUE` rather than hardcoding vanilla state ownership.
- The Welland/Upper Canada state reference was kept on C2C's `STATE_ONTARIO_PENINSULA`.
- Vancouver Island now starts as a `c2c_responsible_colony`, and the C2C startup effect converts any remaining vanilla `subject_type_colony` pact for `c:VAN` to `subject_type_c2c_responsible_colony`.
- Responsible Government grants/keeps C2C's responsible colony subject type instead of vanilla dominion or colony assumptions.
- CFM's confederation logic uses C2C subject types: eligible colonies are vanilla colonies or `subject_type_c2c_responsible_colony`, and the resulting Canada becomes `subject_type_c2c_self_governing_dominion`.
- CFM's PEI assumptions are handled as the C2C `c:PEI` tag occupying province `x70C040` in `STATE_NEW_BRUNSWICK`; no separate PEI map region was imported or referenced.

## Pending Confirmation

- CFM's Maritimes map split and hub localization were left out because they conflict with C2C's current state regions and hub placement.

## Source Issues Fixed During Integration

- Replaced malformed decision gating (`exists = c:GBR c:GBR = ROOT exists = c:ONTexists = c:QUE`) with valid C2C logic.
- Replaced placeholder modifiers `some_modifier`, `some_other_modifier`, and broken `add_modifier = #Welland...`.
- Avoided broad `REPLACE:can_reformer_movement_fury` by adding `c2c_reformer_movement_fury`.
- Fixed culture references like `culture = anglo_canadian` to `culture = cu:anglo_canadian`.
- Avoided missing DNA/template references for Wolfred Nelson, Peter McGill, George Brown, and Lord Durham.
- Replaced vanilla colony assumptions with C2C responsible-colony behavior.
- Replaced CFM's incomplete `je_confederation`/`cfm_confederation` keys with C2C-prefixed events, buttons, variables, and effects wired into the vanilla/C2C `je_canada_can` override.
