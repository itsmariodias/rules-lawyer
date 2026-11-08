- Nodes are multi-label: `:Section:Spell` is one node, so `MATCH (n:Spell)`
  and `MATCH (n:Section)` can return the same node. Match on the most
  specific label.
- `:Section` is the SRD's heading tree and carries `id`, the dotted string
  (`10.3.116`) that is the only citable identifier. RETURN it whenever the
  answer will cite the row.
- A creature, a gear item and a poison *are* their section, so a `:Creature`
  has an `id`. A `:CreatureAbility`, `:GlossaryTerm`, `:Weapon` or `:Class`
  is not a section and has none: reach the section through `HAS_ABILITY`,
  `DEFINED_IN` or `CARRIES` when you need something to cite.
- `:CreatureAbility` is keyed `key` (`Goblin|actions/Bite`) and carries
  `name`, `creature`, `category`, `description`, `save_ability`, `save_dc`,
  `attack_bonus`, `damage_dice`, `damage_types`.
- `:GlossaryTerm` is keyed on `name` and carries a second label for its kind
  (`:Condition`, `:DamageType`, `:Action`), so a condition is
  `(:GlossaryTerm:Condition {name: 'Frightened'})`.
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
