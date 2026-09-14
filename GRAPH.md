# The graph

What `srd-graph-load` builds in Neo4j from `data/output/srd_hierarchy.json`:
every node label and every relationship type, what it means, what identifies
it, and what it carries.

## How to read this

**A label is a tag, not a type.** A node can carry several, so
`MATCH (n:Section)` and `MATCH (n:Spell)` can return the *same* node. Nodes
merge on the **first** label and its key; any second label is set alongside.

**There are two kinds of node.**

- **`:Section` nodes** — the SRD's heading tree, joined by `HAS_SUBSECTION`.
  Each carries exactly one entity label saying what kind of section it is, so
  those labels partition the tree.
- **Everything else** — stat-block entries, glossary terms, weapon and armour
  rows, classes and so on: things that are not headings, or are not 1:1 with
  one. Where an entity *is* its heading — a creature, a gear item, a poison —
  it folds into that section rather than becoming a second node beside it.

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
of its ancestor headings and its content, indexed by `srd_vector`. 2156 of
the 2368 have one; the remaining 212 are headings whose children hold all the
text, so there was nothing to embed. The vectors come from
`data/output/srd_embeddings.idx`, which is either generated once with a
Gemini key (`srd-embed`) or downloaded — see **Constraints and indexes**.

### `:Section:ClassFeature`

One feature of a class or subclass, as its own heading. Reached from a
`:Class` or `:Subclass` by `HAS_FEATURE`, and from a `:ClassLevel` by
`GRANTS_FEATURE`.

- **Adds** — nothing beyond the shared section properties
- **Example** — `6.1.2.20` "Level 20: Primal Champion"

### `:Section:Rule`

Rules prose: the chapters explaining how the game works, and their
sub-headings.

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
  page_start: 131, char_start: 535009, char_end: 535704 })
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
  condition_immunities: ["Charmed", "Exhaustion"],
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

### `:Section:EquipmentSection`

Equipment *prose* — how weapon properties and armour training work. Distinct
from `:Equipment`, which is the table rows; hence the clumsy name. Both exist
because they are genuinely different things.

- **Example** — `9.2.2` "Properties"

### `:Section:CreatureGroup`

A section whose subtree contains stat blocks. The label is assigned by what a
section *contains*, so a summoning spell counts as one — and still carries
its own spell properties.

- **Adds** — spell or item properties on the few nodes that are also a spell
  or an item
- **Example** — `10.3.10` "Animate Objects", which is both a spell and the
  parent of the Animated Object stat block

### `:Section:GlossarySection`

The prose behind a `:GlossaryTerm`. Separate from the term itself because the
two are not 1:1 — every damage type is printed in one shared table.

- **Adds** — `term_type`
- **Example** — `11.2.114` "Prone [Condition]"

### `:Section:Origin`

Species and background prose.

- **Example** — `7.1.1` "Parts of a Background"

### `:Section:FeatSection`

Feat prose. Distinct from `:Feat`, the extracted entity.

- **Example** — `8.1.2.1` "Alert"

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

All merge on `:GlossaryTerm`, key `name`, and all carry `name`, `term_type`,
`description`, `section_id`, `page_start`, `page_end`. The second label is
the `term_type`. They stay separate from their sections because they are not
1:1 with them.

### `:GlossaryTerm:Definition`

A defined term with no special mechanics attached — the bulk of the Rules
Glossary. Nothing targets these; they are reached by `DEFINED_IN` or
full-text search.

- **Example** — "Ability Check"

### `:GlossaryTerm:Condition`

A condition something can impose or be immune to. The target of
`IMPOSES_CONDITION`, `REFERENCES_CONDITION` and `IMMUNE_TO_CONDITION`.

- **Example** — "Prone"

### `:GlossaryTerm:DamageType`

A damage type. The target of `REFERENCES_DAMAGE_TYPE`, `IMMUNE_TO`,
`RESISTANT_TO` and `VULNERABLE_TO`. They all come from one table and share a
single section id, which is exactly why glossary terms are not folded into
their sections.

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
  `char_start` / `char_end` that locate it in the book. Its labels are the
  section's plus `:Equipment` and its kind, so `Acid` is
  `:Section:EquipmentSection:Equipment:Gear`.

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
- **Example** — `9.5.1` `:Section:EquipmentSection:Equipment:Gear`,
  `name: "Acid"`, `heading: "Acid (25 GP)"`, `cost_gp: 25.0`

### `:Equipment:Poison`

Printed with a paragraph each, so folded into its section like gear. Each
names a delivery type.

- **Adds** — `poison_type` (Ingested, Injury, Inhaled or Contact), plus the
  section's properties
- **Links** — `HAS_POISON_TYPE` to the `:GlossaryTerm:PoisonType` that
  explains what that type does
- **Example** — `12.6.3.10` `:Section:Rule:Equipment:Poison`,
  `name: "Serpent Venom"`, `poison_type: "Injury"`

### `:Equipment:Armor`

- **Adds** — `armor_class`, `stealth_disadvantage`, and
  `strength_requirement` on the heaviest
- **Example** — "Chain Mail", AC 16, Str 13, Stealth disadvantage

## Character options

### `:Class`

One of the SRD's classes.

- **Key** — `name`
- **Properties** — `section_id`, `hit_point_die`, `primary_ability`,
  `saving_throw`, `skill_proficiencies`, `weapon_proficiencies`,
  `armor_training`, `starting_equipment`, `page_start`, `page_end`;
  optionally `tool_proficiencies`
- **Example**

```cypher
(:Class {
  name: "Wizard", section_id: "6.12", hit_point_die: "D6 per Wizard level",
  primary_ability: "Intelligence", saving_throw: "Intelligence and Wisdom",
  weapon_proficiencies: "Simple weapons", armor_training: "None" })
```

### `:Subclass`

One subclass. The SRD prints a single one per class.

- **Key** — `key`, which is its section id
- **Properties** — `name`, `parent_class`, `section_id`, `description`
- **Example** — `(:Subclass {key: "6.1.3", name: "Path of the Berserker",
  parent_class: "Barbarian"})`

### `:ClassLevel`

One node per class per level. A node rather than a list property, so a query
can ask what a level grants without unpacking anything.

- **Key** — `key`, formed `Class|level`
- **Properties** — `parent_class`, `level`, `proficiency_bonus`,
  `resource_names`, `resource_values`
- **Why two arrays** — the level table's resources are a `{name: value}` map
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

### `:Species`

- **Key** — `name`
- **Properties** — `section_id`, `description`, `size`, `speed`,
  `creature_type`, `page_start`, `page_end`
- **Example** — "Dragonborn": Humanoid, Medium, 30 feet

### `:Background`

- **Key** — `name`
- **Properties** — `section_id`, `description`, `ability_scores`,
  `skill_proficiencies`, `tool_proficiency`, `equipment`, `page_start`,
  `page_end`
- **Example** — "Acolyte"

### `:Feat`

The extracted feat. Distinct from `:Section:FeatSection`, its prose.

- **Key** — `name`
- **Properties** — `section_id`, `description`, `category`, `feat_group`,
  `page_start`, `page_end`
- **Example** — "Alert", an Origin Feat

### `:Trait`

A named trait belonging to a species or a feat — the bolded sub-entries in
their descriptions.

- **Key** — `key`, formed `Owner|Trait Name`
- **Properties** — `name`, `owner`, `description`
- **Example** — `(:Trait {key: "Dragonborn|Draconic Ancestry",
  owner: "Dragonborn", name: "Draconic Ancestry"})`

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
(:Class)-[:HAS_FEATURE {level}]->(:Section:ClassFeature)
(:Subclass)-[:HAS_FEATURE {level}]->(:Section:ClassFeature)
```

A class or subclass to the features it grants. It points at the feature's own
section rather than copying its prose.

- **Example** — `(Barbarian)-[:HAS_FEATURE {level: 20}]->(6.1.2.20 "Level 20: Primal Champion")`

### `AT_LEVEL`

```cypher
(:Class)-[:AT_LEVEL {level}]->(:ClassLevel)
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
(:Class)-[:HAS_SUBCLASS]->(:Subclass)
```

- **Example** — `(Barbarian)-->(6.1.3 "Path of the Berserker")`

### `DEFINED_IN`

```cypher
(:GlossaryTerm)-[:DEFINED_IN]->(:Section)
(:Class|:Subclass|:Species|:Background|:Feat)-[:DEFINED_IN]->(:Section)
```

An entity from a flat collection back to the prose defining it. It exists for
exactly those collections that are *not* 1:1 with a section — which is why
creatures have none: they **are** their section.

- **Example** — `(Prone)-->(11.2.114 "Prone [Condition]")`

### `HAS_TRAIT`

```cypher
(:Species)-[:HAS_TRAIT]->(:Trait)
(:Feat)-[:HAS_TRAIT]->(:Trait)
```

- **Example** — `(Dragonborn)-->(Dragonborn|Breath Weapon)`

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
(:Section:Spell)-[:ON_SPELL_LIST]->(:Class)
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
(:Equipment:Poison)-[:HAS_POISON_TYPE]->(:GlossaryTerm:PoisonType)
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
(:Background)-[:GRANTS_FEAT]->(:Feat)
```

From the background's printed feat, with the parenthetical stripped:
`Magic Initiate (Cleric) (see "Feats")` resolves to "Magic Initiate".

- **Example** — `(Acolyte)-->(Magic Initiate)`

---

# Constraints and indexes

A uniqueness constraint on every merge key, which doubles as the index
`MERGE` needs:

| Label | Property |  | Label | Property |
| --- | --- | --- | --- | --- |
| `:Section` | `id` |  | `:ClassLevel` | `key` |
| `:CreatureAbility` | `key` |  | `:Species` | `name` |
| `:GlossaryTerm` | `name` |  | `:Background` | `name` |
| `:Equipment` | `name` |  | `:Feat` | `name` |
| `:Class` | `name` |  | `:Trait` | `key` |
| `:Subclass` | `key` |  | | |

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
