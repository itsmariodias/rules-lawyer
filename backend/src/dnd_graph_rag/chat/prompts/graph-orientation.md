- Nodes are multi-label: `:Section:Spell` is one node, so `MATCH (n:Spell)`
  and `MATCH (n:Section)` can return the same node. Match on the most
  specific label.
- `:Section` is the SRD's heading tree and carries `id`, the dotted string
  (`10.3.116`) that is the only citable identifier. RETURN it whenever the
  answer will cite the row.
- Anything printed under its own heading *is* that section and has an `id`:
  a `:Creature`, `:Gear`, `:Poison`, `:Class`, `:Subclass`, `:Species`,
  `:Background`, `:Feat`, and every glossary term except the damage and
  poison types. What has no heading of its own has no `id`: reach a
  `:CreatureAbility`'s section through `HAS_ABILITY`, and a `:DamageType`,
  `:PoisonType`, `:ClassLevel`, `:Weapon` or `:Armor`'s through
  `DEFINED_IN` (a class level or weapon is defined in the table printing its
  row).
- A captioned table is a `:Section:Rule` of its own, and a section that
  names it ("the Barbarian Features table") has `REFERENCES_TABLE` to it.
- `:CreatureAbility` is keyed `key` (`Goblin|actions/Bite`) and carries
  `name`, `creature`, `category`, `description`, `save_ability`, `save_dc`,
  `attack_bonus`, `damage_dice`, `damage_types`.
- `:GlossaryTerm` is matched on `name` and carries a second label for its
  kind (`:Condition`, `:DamageType`, `:Action`), so a condition is
  `(:GlossaryTerm:Condition {name: 'Frightened'})`, and its `id` is the
  section to cite. `name` is the entity and `heading` the printed form
  ("Prone" and "Prone [Condition]").
- A species or feat lists its named traits in `traits`, so
  `WHERE 'Darkvision' IN s.traits` finds them; the trait text is in the
  section's `content`.
- Every `:Section` has `heading`, `content`, `entity_type`, `page_start`.
  A `:Creature` adds `cr`, `ac`, `hp_average`, `creature_type`; a `:Spell`
  adds `level`, `school`, `concentration`, `ritual`.
- An effect usually reaches its target through an intermediate node, so a
  question about creatures is a two- or three-hop pattern rather than one
  edge. A creature imposes a condition through its ability
  (`(:Creature)-[:HAS_ABILITY]->()-[:IMPOSES_CONDITION]->(:Condition)`) and
  also through a spell that ability casts
  (`(:Creature)-[:HAS_ABILITY]->()-[:REFERENCES_SPELL]->(:Spell)-[:IMPOSES_CONDITION]->(:Condition)`).
  A "which creatures" question wants every such path: cover them in one query
  with a UNION or a variable-length pattern, rather than running each on its
  own and guessing at what none of them returned.
- RETURN the columns that answer the whole question, not just the names. An
  ability's `description`, `save_ability` and `save_dc` are what "and how do
  they do it" is asking for, and they come back with the row; fetching each
  one afterwards with get_srd_section is the same answer for twenty times the
  work.
