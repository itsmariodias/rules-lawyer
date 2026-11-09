# The graph

What `srd-graph-load` builds in Neo4j from `data/output/srd_hierarchy.json`:
every node label and every relationship type, what it means, what identifies
it, and what it carries.

## How to read this

**A label is a tag, not a type.** A node can carry several, so
`MATCH (n:Section)` and `MATCH (n:Spell)` can return the *same* node. Nodes
merge on the **first** label and its key; any second label is set alongside.

**There are two kinds of node.**

- **`:Section` nodes:** the SRD's heading tree, joined by `HAS_SUBSECTION`.
  Each carries exactly one entity label saying what kind of section it is, so
  those labels partition the tree. An entity printed under its own heading
  *is* that section: a creature, gear item, poison, class, subclass,
  species, background, feat or glossary term folds into it, adding its
  record's label and properties, rather than becoming a second node beside
  it. Such a node cites itself.
- **Everything else:** what has no heading of its own. Stat block entries,
  class levels, weapon and armour rows, and the damage and poison types,
  which share one passage per kind.

**The graph leaves out one kind of heading.** The book heads a stat block
with its monster entry even when the entry holds only that stat block and no
prose ("Aboleth" above the Aboleth stat block). Those 139 entries are in the
artifact but not the graph; the stat block hangs from the entry's parent and
keeps its own id. An entry whose one stat block has another name ("Crawling
Claw" above "Swarm of Crawling Claws") stays, since its heading is the only
place that name is printed.

**A `:Section` is one heading**, at any of the SRD's five levels. Its
subsections are separate nodes, not part of it. Most nodes are leaves, which
is where most entities live — a spell or a creature is normally a leaf.

**Two fields describe a section's text, over different spans.** `content` is
the node's own prose, between its heading and its first child heading — so a
chapter heading has none. `char_start` / `char_end` span the node's whole
subtree in `srd_hierarchy.md`. They agree on a leaf and diverge on a branch:
use `content` for what a section itself says, the char range to pull
everything beneath it.

**Properties are sparse.** The loader drops nulls rather than storing them,
so a property listed as *optional* below is simply absent where the book
prints nothing.

---

# Nodes

## Section nodes

All merge on `:Section`, key `id` — the dotted path (`10.3.123`), the
artifact's only globally unique stable identifier.

**Every section carries** `id`, `name`, `heading`, `content`, `entity_type`,
`depth`, `page_start`, `page_end`, `char_start`, `char_end`. Where the parser
split a node into named entries it also carries `preamble` and
`entries_json`. The entries below list only what each second label *adds*.

**A section with prose also carries `embedding`**, a 1536-float unit vector
of its ancestor headings and its content, indexed by `srd_vector`. 2172 of
the 2394 have one; the remaining 222 are headings whose children hold all the
text, so there was nothing to embed. The vectors come from
`data/output/srd_embeddings.idx`, which is either generated once with a
Gemini key (`srd-embed`) or downloaded — see **Constraints and indexes**.

### `:Section:ClassFeature`

One feature of a class or subclass, as its own heading ("Level N: ..."), or
an option chosen through one: the 10 Metamagic Options and 28 Eldritch
Invocation Options. Reached from a `:Section:Class` or `:Section:Subclass` by
`HAS_FEATURE`, and from a `:ClassLevel` by `GRANTS_FEATURE` (options are
not, since no level grants a particular one).

- **Adds** — nothing beyond the shared section properties
- **Example:** `6.1.3.21` "Level 20: Primal Champion"

### `:Section:Class`

One class: its introduction, with the Core Traits and Features tables, and
its features and subclass below it. The class record folds into it, so the
node carries both the prose and the core traits. Edges reach it as
`(:Class {name})`.

- **Adds:** `hit_point_die`, `primary_ability`, `saving_throw`,
  `skill_proficiencies`, `weapon_proficiencies`, `armor_training`,
  `starting_equipment`; optionally `tool_proficiencies`
- **Example**

```cypher
(:Section:Class {
  id: "6.12", name: "Wizard", heading: "Wizard",
  hit_point_die: "D6 per Wizard level", primary_ability: "Intelligence",
  saving_throw: "Intelligence and Wisdom",
  weapon_proficiencies: "Simple weapons", armor_training: "None" })
```

### `:Section:Subclass`

One subclass, with its record folded in. The SRD prints a single one per
class. `name` is the subclass; `heading` keeps the printed form.

- **Adds:** `parent_class`
- **Example:** `(:Section:Subclass {id: "6.1.4",
  name: "Path of the Berserker",
  heading: "Barbarian Subclass: Path of the Berserker",
  parent_class: "Barbarian"})`

### `:Section:Rule`

Rules prose: the chapters explaining how the game works, and their
sub-headings. Also every section nothing else types: a chapter heading, a
table, a sidebar, a class's spell list, "Parts of a Background". A section
is never typed by the chapter it sits in.

- **Example** — `4.8.4` "Cover"

### `:Section:Spell`

One spell. Its prose *is* the entity, so the spell node **is** its section
rather than something hanging off it.

- **Adds** — `level`, `school`, `spell_classes`, `ritual`, `concentration`,
  `casting_time`, `range`, `duration`, `verbal`, `somatic`
- **Optional** — `material`, `material_cost_gp`, `material_consumed`,
  `saving_throw`, `attack_kind`, `conditions_imposed`, `damage_dice`,
  `damage_types`
- **No `damage_averages`** — spells print dice without an average, so the
  property is omitted rather than padded with a sentinel. Creature abilities,
  which do print averages, have it
- **Example**

```cypher
(:Section:Spell {
  id: "10.3.123", name: "Fireball", level: 3, school: "Evocation",
  spell_classes: ["Sorcerer", "Wizard"], casting_time: "Action",
  range: "150 feet", duration: "Instantaneous",
  concentration: false, ritual: false, verbal: true, somatic: true,
  material: "a ball of bat guano and sulfur", saving_throw: "Dexterity",
  damage_dice: ["8d6"], damage_types: ["Fire"],
  page_start: 131, char_start: 535443, char_end: 536138 })
```

### `:Section:Creature`

A stat block, folded into its own section. The two are 1:1 by construction —
names are unique on both sides — and the mapper raises rather than loading a
graph quietly missing creatures if that ever stops being true.

- **Identity** — `creature_type`, `alignment`, `cr`, `xp`; optionally
  `xp_in_lair`
- **Defence** — `ac`, `hp_formula`; optionally `hp_average`
- **Initiative** — `initiative_bonus`, `initiative_score`,
  `initiative_advantage`
- **Abilities** — `str_score` / `str_modifier` / `str_save`, and the same
  three for `dex`, `con`, `int`, `wis`, `cha`
- **Movement** — `speed_walk`, and `speed_fly` / `speed_swim` /
  `speed_climb` / `speed_burrow` where the creature has them
- **Lists** — optionally `immunities`, `resistances`, `vulnerabilities`,
  `condition_immunities`, `gear`. Each also becomes relationships; see
  *Derived* below
- **Other** — `senses`, `languages`, `proficiency_bonus`; optionally
  `skills_json` and `warnings`
- **Example**

```cypher
(:Section:Creature {
  id: "10.3.10.1", name: "Animated Object",
  creature_type: "Huge or Smaller Construct", alignment: "Unaligned",
  cr: "None", ac: 15, hp_average: 10, hp_formula: "Medium or smaller",
  speed_walk: 30, str_score: 16, str_modifier: 3, str_save: 3, wis_score: 3,
  immunities: ["Poison", "Psychic"],
  condition_immunities: ["Charmed", "Exhaustion", "Frightened",
    "Paralyzed", "Poisoned"],
  senses: "Blindsight 30 ft.; Passive Perception 6",
  page_start: 109, char_start: 434992, char_end: 435872 })
```

### `:Section:MagicItem`

A magic item. Like spells, the prose is the entity.

- **Adds** — `category`, `rarity`, `requires_attunement`
- **Optional** — `subtype`, `attunement_requirement`
- **Example**

```cypher
(:Section:MagicItem {
  id: "13.9.16", name: "Bag of Holding", category: "Wondrous Item",
  rarity: "Uncommon", requires_attunement: false, page_start: 212 })
```

### `:Section:Trap`

One of the example traps from the Gameplay Toolbox. Typed as a set because
the book introduces them under "Example Traps"; their prose already carries
the damage, action and condition edges, so typing them is what makes
"which traps deal Poison damage" answerable.

- **Example** — `12.7.2.4` "Hidden Pit"

### `:Section:EnvironmentalEffect`

A hazard of terrain or weather — Deep Water, Extreme Cold, Thin Ice — from
the "Environmental Effects" section. Distinct from `:GlossaryTerm:Hazard`
(Burning, Falling, Suffocation), which the Rules Glossary defines separately.

- **Example** — `12.4.2` "Extreme Cold"

### `:Section:Contagion`

A magical disease: Cackle Fever, Sewer Plague, Sight Rot. The book prints
"Example Contagions" as a plain sibling heading ahead of the three rather
than nesting them under it, so only those three are typed.

- **Example** — `12.3.2.3` "Cackle Fever"

### `:Section:CreatureGroup`

A section in the monster chapters (Monsters, Monsters A-Z, Animals) whose
subtree holds stat blocks other than its own: a monster's entry. In the
graph only 38 of the artifact's 177 remain: those grouping several stat
blocks, and the 7 whose one stat block has another name. The other 139
wrapped a stat block of their own name with no prose and are left out (see
**How to read this**). The chapters themselves are `:Rule`. Outside those
chapters a section printing a stat block keeps its own type: the summoning
spell `10.3.10` "Animate Objects" is a `:Spell`, and its Animated Object
stat block is a `:Creature` below it.

- **Adds:** `members`, the names of the stat blocks in its subtree
- **Example:** `15.16` "Black Dragons", whose members are the four black
  dragon stat blocks

### `:Section:Origin:Species`

One species, its record folded into the section describing it.

- **Adds:** `size`, `speed`, `creature_type`, and `traits`, the names of
  its bolded sub-entries ("Breath Weapon", "Darkvision"), whose text is in
  `content`
- **Example:** `(:Section:Origin:Species {name: "Dragonborn",
  creature_type: "Humanoid", size: "Medium (about 5–7 feet tall)",
  speed: "30 feet"})`

### `:Section:Origin:Background`

One background, its record folded in.

- **Adds:** `ability_scores`, `skill_proficiencies`, `tool_proficiency`,
  `equipment`
- **Example:** `7.1.2.1` "Acolyte"

### `:Section:Feat`

One feat, its record folded in.

- **Adds:** `category`, `feat_group`, and `traits` as for species
- **Example:** `8.1.2.1` "Alert", an Origin Feat, with
  `traits: ["Initiative Proficiency", "Initiative Swap"]`

### `:Section:FrontMatter`

Legal Information, Contents, and the Index of Stat Blocks. These have no
subsections and nothing references them, so they are the graph's only
expected orphan sections.

- **Example** — `1` "Legal Information"

## Stat block entries

### `:CreatureAbility`

Every trait, action, bonus action, reaction and legendary action, as its own
node. They exist separately **because references point at them**: a
creature-sourced reference names the entry it came from, so a mechanics edge
attaches to the ability that causes it instead of smearing across the whole
stat block. Without this, "which creatures can Frighten, and *how*" loses its
second half.

- **Key** — `key`, formed `Creature|category/Name` — the same string the
  artifact uses in `references[].source.part`
- **Always** — `key`, `name`, `creature`, `category` (one of `traits`,
  `actions`, `bonus_actions`, `reactions`, `legendary_actions`),
  `description`
- **Attack** — `attack_kind`, `attack_bonus`, `reach_ft`, `range_ft`, and
  `range_long_ft` where a thrown or ranged weapon prints two ranges
- **Save** — `save_ability`, `save_dc`, `save_targets`
- **Damage** — `damage_dice`, `damage_types`, `damage_averages`, three
  arrays corresponding by position, because Neo4j has no list-of-maps
- **Other** — `outcomes_json`, `conditions_imposed`, `uses_type`,
  `uses_printed`, `uses_times`
- **Example**

```cypher
(:CreatureAbility {
  key: "Animated Object|actions/Slam", name: "Slam",
  creature: "Animated Object", category: "actions",
  description: "_Melee Attack Roll:_ Bonus equals your spell attack…",
  outcomes_json: "{\"hit\": {\"text\": \"Force damage equal to 1d4 + 3…\"}}" })
```

## Glossary terms

The book prints glossary terms two ways, and the graph follows it, as it
does for equipment.

- **A term with a heading of its own** (155 of 172) is that section,
  labelled `:Section:GlossaryTerm` plus its kind, so Prone is
  `(:Section:GlossaryTerm:Condition {id: "11.2.114", name: "Prone",
  heading: "Prone [Condition]"})`. It carries the section's properties plus
  `term_type`; its definition is `content`.
- **A term sharing a passage** cannot be that passage: the 13 damage types
  are one table (`11.2.46.1`) and the 4 poison types one paragraph (`12.6`).
  These are nodes of their own, merging on `:GlossaryTerm`, key `name`,
  carrying `name`, `term_type`, `description`, `section_id`, `page_start`,
  `page_end`, and `DEFINED_IN` that passage.

Every term has the `:GlossaryTerm` label and a unique `name` either way, so
an edge reaches it as `(:GlossaryTerm {name})`. The second label is the
`term_type`.

### `:GlossaryTerm:Definition`

A defined term with no special mechanics attached: the bulk of the Rules
Glossary. Nothing targets these; they are reached through the tree or by
search.

- **Example** — "Ability Check"

### `:GlossaryTerm:Condition`

A condition something can impose or be immune to. The target of
`IMPOSES_CONDITION`, `REFERENCES_CONDITION` and `IMMUNE_TO_CONDITION`.

- **Example** — "Prone"

### `:GlossaryTerm:DamageType`

A damage type. The target of `REFERENCES_DAMAGE_TYPE`, `IMMUNE_TO`,
`RESISTANT_TO` and `VULNERABLE_TO`. They all come from one table and share a
single section id, which is why these stay nodes of their own, `DEFINED_IN`
it.

- **Example** — "Fire"

### `:GlossaryTerm:PoisonType`

One of the four ways a poison is delivered. Like the damage types, they are
defined together in a single passage — the paragraph introducing the Sample
Poisons — rather than one section each. Nothing in the book refers to them
except the poisons themselves, which is why each poison links to its type:
that edge is the only thing that makes the definition reachable.

- **Example** — "Injury": *"Injury poison can be applied as a Bonus Action to
  a weapon, a piece of ammunition, or similar object…"*

### `:GlossaryTerm:Action`

An action a creature can take on its turn. The target of `REFERENCES_ACTION`,
which matches only on required phrasing ("the Utilize action") so bare nouns
do not fire.

- **Example** — "Dash"

### `:GlossaryTerm:AreaOfEffect`

A spell area shape. The target of `REFERENCES_AREA_OF_EFFECT`.

- **Example** — "Cone"

### `:GlossaryTerm:Hazard`

An environmental hazard.

- **Example** — "Burning"

### `:GlossaryTerm:Attitude`

An NPC's attitude toward the party.

- **Example** — "Friendly"

## Equipment

The book prints equipment two ways, and the graph follows it.

- **Weapons and armour** are bare table rows. They have no prose and no
  section, so they are nodes of their own, merging on `:Equipment`, key
  `name`. Many have no relationships at all — a Dagger has a price and a
  damage die and nothing more. That is a fact about the book, not a load
  failure.
- **Gear and poisons** are printed as a heading with a paragraph under it, so
  each one **is** a section. It folds into that section exactly as a creature
  does, giving one node that carries the price, the prose *and* the
  `char_start` / `char_end` that locate it in the book. Its labels are
  `:Section:Equipment` plus its kind, so `Acid` is `:Section:Equipment:Gear`.

A folded node keeps `heading` as the book prints it — "Acid (25 GP)" — while
`name` is the entity, "Acid".

**All carry** `name`, `kind`, `category`, `cost`, `page_start`, `page_end`,
plus `cost_gp` and `weight_lb` where the book prints them.

### `:Equipment:Weapon`

- **Adds** — `damage_dice`, `damage_type`, `mastery`, `properties`
- **Example**

```cypher
(:Equipment:Weapon {
  name: "Longsword", kind: "weapon", category: "Martial Melee",
  damage_dice: "1d8", damage_type: "Slashing", mastery: "Sap",
  properties: ["Versatile (1d10)"], cost: "15 GP", cost_gp: 15.0,
  weight_lb: 3.0, page_start: 91 })
```

### `:Equipment:Gear`

Adventuring gear. Folded into its section, so it is also a `:Section` and
sits in the tree. Its prose carries references of its own — Acid's mentions
the Attack action, which becomes a real edge from this node.

- **Adds** — the section's properties, since it is one
- **Example:** `9.5.2` `:Section:Equipment:Gear`,
  `name: "Acid"`, `heading: "Acid (25 GP)"`, `cost_gp: 25.0`

### `:Equipment:Poison`

Printed with a paragraph each, so folded into its section like gear. Each
names a delivery type.

- **Adds** — `poison_type` (Ingested, Injury, Inhaled or Contact), plus the
  section's properties
- **Links** — `HAS_POISON_TYPE` to the `:GlossaryTerm:PoisonType` that
  explains what that type does
- **Example:** `12.6.3.10` `:Section:Equipment:Poison`,
  `name: "Serpent Venom"`, `poison_type: "Injury"`

### `:Equipment:Armor`

- **Adds** — `armor_class`, `stealth_disadvantage`, and
  `strength_requirement` on the heaviest
- **Example** — "Chain Mail", AC 16, Str 13, Stealth disadvantage

## Character options

Classes, subclasses, species, backgrounds and feats are their sections (see
**Section nodes**). What remains is the level table.

### `:ClassLevel`

One node per class per level. A node rather than a list property, so a query
can ask what a level grants without unpacking anything.

- **Key:** `key`, formed `Class|level`
- **Properties:** `parent_class`, `level`, `proficiency_bonus`,
  `resource_names`, `resource_values`
- **Why two arrays:** the level table's resources are a `{name: value}` map
  in the artifact, and Neo4j has no map property, so they become two arrays
  corresponding by position
- **Example**

```cypher
(:ClassLevel {
  key: "Barbarian|1", parent_class: "Barbarian", level: 1,
  proficiency_bonus: 2,
  resource_names:  ["Rages", "Rage Damage", "Weapon Mastery"],
  resource_values: ["2",     "+2",          "2"] })
```

---

# Relationships

Only three carry properties: `HAS_ABILITY` has `category`, `HAS_FEATURE` and
`AT_LEVEL` have `level`. Every other edge is bare.

## Structural

From the artifact's own containment — one thing printed inside another.

### `HAS_SUBSECTION`

```cypher
(:Section)-[:HAS_SUBSECTION]->(:Section)
```

The heading tree. Every section except the roots has exactly one parent,
which `verify.py` checks on each load.

- **Example** — `(10 "Spells")-->(10.1 "Gaining Spells")`

### `HAS_ABILITY`

```cypher
(:Section:Creature)-[:HAS_ABILITY {category}]->(:CreatureAbility)
```

A stat block to each of its entries. `category` repeats the ability's own, so
a traversal can filter to actions without visiting the ability node.

- **Example** — `(Goblin Warrior)-[:HAS_ABILITY {category: "bonus_actions"}]->(Goblin Warrior|bonus_actions/Nimble Escape)`

### `HAS_FEATURE`

```cypher
(:Section:Class)-[:HAS_FEATURE {level}]->(:Section:ClassFeature)
(:Section:Subclass)-[:HAS_FEATURE {level}]->(:Section:ClassFeature)
```

A class or subclass to the features it grants. It points at the feature's own
section rather than copying its prose.

- **Example:** `(Barbarian)-[:HAS_FEATURE {level: 20}]->(6.1.3.21 "Level 20: Primal Champion")`

### `AT_LEVEL`

```cypher
(:Section:Class)-[:AT_LEVEL {level}]->(:ClassLevel)
```

A class to each of its level rows.

- **Example** — `(Barbarian)-[:AT_LEVEL {level: 1}]->(Barbarian|1)`

### `GRANTS_FEATURE`

```cypher
(:ClassLevel)-[:GRANTS_FEATURE]->(:Section:ClassFeature)
```

A level row to the features its table names. Not every row has one, and a few
name a feature the chapter never details separately.

- **Example** — `(Barbarian|1)-[:GRANTS_FEATURE]->("Level 1: Rage")`

### `HAS_SUBCLASS`

```cypher
(:Section:Class)-[:HAS_SUBCLASS]->(:Section:Subclass)
```

- **Example:** `(Barbarian)-->(6.1.4 "Path of the Berserker")`

### `DEFINED_IN`

```cypher
(:GlossaryTerm:DamageType|PoisonType)-[:DEFINED_IN]->(:Section)
```

A glossary term back to the passage defining it, for the 17 terms that share
one and so cannot be it. Every other entity printed under its own heading
**is** that section and needs no such edge.

- **Example:** `(Fire)-->(11.2.46.1 "Damage Types")`

## Cross-references

The edges the parser found in the book's own markup. Spells and magic items
are italicised in the SRD and creatures bolded; conditions, actions and
damage types are not marked up at all, so they match on required phrasing
("Prone condition", "Utilize action", "Fire damage") — which keeps "Cover",
"Attack" and "Force" from firing as bare nouns.

A **source** is whatever the prose belonged to: a `:Section` of any kind
(including a folded gear item or poison), or a `:CreatureAbility` when the
text came from inside a stat block. Each paragraph is scanned once, so an
item that is its own section does not also emit edges under its item
identity. A **target** is
always matched, never merged — an unresolvable name is reported rather than
turned into an empty node.

### `REFERENCES_SPELL`

```cypher
(source)-[:REFERENCES_SPELL]->(:Section:Spell)
```

An italicised spell name in the prose. Mostly from class features, creature
abilities and magic items.

- **Example** — `("Level 20: Words of Creation")-->(Power Word Heal)`

### `REFERENCES_DAMAGE_TYPE`

```cypher
(source)-[:REFERENCES_DAMAGE_TYPE]->(:GlossaryTerm:DamageType)
```

The phrase "Fire damage" and its siblings. Mostly from creature abilities and
stat blocks.

- **Example** — `(Animated Object|actions/Slam)-->(Force)`

### `REFERENCES_CONDITION`

```cypher
(source)-[:REFERENCES_CONDITION]->(:GlossaryTerm:Condition)
```

A condition **mentioned**. The weaker half of a pair: it covers target
eligibility ("one creature that has the Prone condition") and immunity text
as well as bare mention. See `IMPOSES_CONDITION` for the stronger claim.

- **Example** — `("Actions")-->(Incapacitated)`

### `REFERENCES_AREA_OF_EFFECT`

```cypher
(source)-[:REFERENCES_AREA_OF_EFFECT]->(:GlossaryTerm:AreaOfEffect)
```

- **Example** — `(Acid Splash)-->(Sphere)`

### `REFERENCES_ACTION`

```cypher
(source)-[:REFERENCES_ACTION]->(:GlossaryTerm:Action)
```

- **Example** — `(Amulet of the Planes)-->(Magic)`

### `REFERENCES_CREATURE`

```cypher
(source)-[:REFERENCES_CREATURE]->(:Section:Creature)
```

A bolded creature name.

- **Example** — `(Bag of Beans)-->(Treant)`

### `REFERENCES_MAGIC_ITEM`

```cypher
(source)-[:REFERENCES_MAGIC_ITEM]->(:Section:MagicItem)
```

- **Example** — `("Expanding and Replacing a Spellbook")-->(Spell Scroll)`

### `IMPOSES_CONDITION`

```cypher
(:CreatureAbility)-[:IMPOSES_CONDITION]->(:GlossaryTerm:Condition)
(:Section:Spell)-[:IMPOSES_CONDITION]->(:GlossaryTerm:Condition)
```

The condition is actually **inflicted**, not merely mentioned. Typography
alone cannot separate the two, so direction comes from `mechanics.py`, which
scopes negation to the clause after the last comma, semicolon or full stop:
*"While Charmed, the target has the Incapacitated condition"* imposes it;
*"while the vampire has the Incapacitated condition"* does not.

- **Example** — `(Otherworldly Steed|bonus_actions/Fell Glare)-->(Frightened)`

## Derived

Not present in the artifact's `references`. The loader builds these from
fields the parser already extracted, because turning a list of names into
edges is what makes a rules question a traversal instead of a scan.

### `ON_SPELL_LIST`

```cypher
(:Section:Spell)-[:ON_SPELL_LIST]->(:Section:Class)
```

From each spell's own subtitle — "Level 3 Evocation (Sorcerer, Wizard)".

- **Example** — `(Fireball)-->(Wizard)` and `(Fireball)-->(Sorcerer)`

### `IMMUNE_TO`

```cypher
(:Section:Creature)-[:IMMUNE_TO]->(:GlossaryTerm:DamageType)
```

From the stat block's `immunities` list.

- **Example** — `(Animated Object)-->(Poison)`

### `RESISTANT_TO`

```cypher
(:Section:Creature)-[:RESISTANT_TO]->(:GlossaryTerm:DamageType)
```

From `resistances`.

- **Example** — `(Draconic Spirit)-->(Acid)`

### `VULNERABLE_TO`

```cypher
(:Section:Creature)-[:VULNERABLE_TO]->(:GlossaryTerm:DamageType)
```

From `vulnerabilities`. Rare — the SRD prints few.

- **Example** — `(Awakened Shrub)-->(Fire)`

### `IMMUNE_TO_CONDITION`

```cypher
(:Section:Creature)-[:IMMUNE_TO_CONDITION]->(:GlossaryTerm:Condition)
```

From `condition_immunities`. Kept apart from `IMMUNE_TO` so damage-type and
condition immunity never blur together.

- **Example** — `(Animated Object)-->(Charmed)`

### `HAS_POISON_TYPE`

```cypher
(:Section:Equipment:Poison)-[:HAS_POISON_TYPE]->(:GlossaryTerm:PoisonType)
```

From the poison's `poison_type`. Every poison has exactly one. This is what
lets a poison be read together with what its delivery type actually means,
rather than leaving the type as a bare string.

```cypher
MATCH (p:Poison)-[:HAS_POISON_TYPE]->(t:PoisonType)
RETURN p.name, p.cost, t.name, t.description;
```

- **Example** — `(Serpent Venom)-->(Injury)`

### `CARRIES`

```cypher
(:Section:Creature)-[:CARRIES]->(:Equipment)
```

From the stat block's `gear` line.

- **Example** — `(Assassin)-->(Light Crossbow)`

### `GRANTS_FEAT`

```cypher
(:Section:Origin:Background)-[:GRANTS_FEAT]->(:Section:Feat)
```

From the background's printed feat, with the parenthetical stripped:
`Magic Initiate (Cleric) (see "Feats")` resolves to "Magic Initiate".

- **Example** — `(Acolyte)-->(Magic Initiate)`

---

# Constraints and indexes

A uniqueness constraint on every merge key, which doubles as the index
`MERGE` needs, and on the names edges match folded records by (a
`(:Class {name})` is a section, merged on its `id`). A constraint on a key
no longer listed is dropped when the schema is applied.

| Label | Property |  | Label | Property |
| --- | --- | --- | --- | --- |
| `:Section` | `id` |  | `:ClassLevel` | `key` |
| `:CreatureAbility` | `key` |  | `:Species` | `name` |
| `:GlossaryTerm` | `name` |  | `:Background` | `name` |
| `:Equipment` | `name` |  | `:Feat` | `name` |
| `:Class` | `name` |  | | |

Range indexes on the filters a rules question starts from:
`Section.entity_type`, `Section.name`, `Section.cr`, `Section.level`,
`GlossaryTerm.term_type`, `Equipment.kind`, `CreatureAbility.creature`.

A full-text index `srd_text` over `Section.heading` and `Section.content`:

```cypher
CALL db.index.fulltext.queryNodes('srd_text', 'opportunity attack')
YIELD node, score
RETURN node.heading, node.page_start, node.char_start LIMIT 5;
```

And a vector index `srd_vector` over `Section.embedding`, 1536 dimensions,
cosine. Cosine rather than dot product because the loader normalises every
vector to unit length, where the two agree, and cosine is the one that stays
right if a later model does not. The width is baked into the index, so
changing `EMBED_DIMENSIONS` means dropping it: `IF NOT EXISTS` would keep the
old one and every write would then fail against it.

Nothing in the chat queries this yet. What it answers today is "what else is
like this passage", which is one embedding the graph already holds:

```cypher
MATCH (n:Section {id: '11.2.114'})
CALL db.index.vector.queryNodes('srd_vector', 6, n.embedding)
YIELD node, score
RETURN node.id, node.heading, round(score, 4) AS score;
```

```text
"11.2.114"  "Prone [Condition]"        0.9988
"11.2.150"  "Unconscious [Condition]"  0.944
"11.2.119"  "Restrained [Condition]"   0.9412
"11.2.106"  "Paralyzed [Condition]"    0.9392
"4.8.2.3"   "Dropping Prone"           0.9368
"11.2.71"   "Grappled [Condition]"     0.9368
```

Answering a *question* needs the question embedded too, which is a live API
call per turn and is why the query half is a separate step.
