"""
Turn the SRD document into node and edge batches.

Pure: it takes the dict ``srd.load()`` returns and gives back
:class:`~.model.GraphData`.  No driver, no I/O, no settings.

Two ideas shape the result.

**The section tree is the spine.**  Every one of its nodes becomes a
``:Section`` keyed on its dotted path id — the only globally unique, stable
identifier the artifact has — and entity types become *extra labels on that
same node* rather than parallel copies.  A spell is therefore one node
carrying both its prose and its ``char_start``/``char_end``, so anything
found by traversal resolves straight back to the text in the book.

**Flat collections stay their own nodes.**  ``creatures`` is the exception,
because a stat block *is* its section (1:1, and the mapper fails if that ever
stops being true).  The rest — equipment, classes, glossary — are separate
nodes joined to their section by ``DEFINED_IN``.  Glossary terms in
particular cannot be folded in: all thirteen damage types share the section
id ``11.2.46.1``, since they come from one table.
"""

from __future__ import annotations

import re
from collections import defaultdict
from typing import Any, Iterator

from .model import EdgeBatch, GraphData, NodeBatch, as_json, clean

# --------------------------------------------------------------------------
# Vocabulary
# --------------------------------------------------------------------------

# Section entity types.  Where a flat collection covers the same ground, the
# section keeps the qualified name and the entity gets the clean one.
SECTION_LABELS = {
    "rule": "Rule",
    "trap": "Trap",
    "contagion": "Contagion",
    "environmental_effect": "EnvironmentalEffect",
    "spell": "Spell",
    "magic_item": "MagicItem",
    "creature": "Creature",
    "creature_group": "CreatureGroup",
    "class_feature": "ClassFeature",
    "origin": "Origin",
    "feat": "FeatSection",
    "equipment": "EquipmentSection",
    "glossary_term": "GlossarySection",
    "front_matter": "FrontMatter",
}

GLOSSARY_LABELS = {
    "definition": "Definition",
    "condition": "Condition",
    "damage type": "DamageType",
    "poison type": "PoisonType",
    "action": "Action",
    "area of effect": "AreaOfEffect",
    "hazard": "Hazard",
    "attitude": "Attitude",
}

EQUIPMENT_LABELS = {
    "weapon": "Weapon",
    "armor": "Armor",
    "gear": "Gear",
    "poison": "Poison",
}

# Reference targets name a type; the glossary names a term_type.  Only the
# punctuation differs, but it has to be bridged explicitly.
TARGET_TERM_TYPES = {
    "condition": "condition",
    "action": "action",
    "damage_type": "damage type",
    "area_of_effect": "area of effect",
}

ABILITY_LISTS = ("traits", "actions", "bonus_actions",
                 "reactions", "legendary_actions")

ABILITIES = ("str", "dex", "con", "int", "wis", "cha")


def walk(nodes: list[dict]) -> Iterator[dict]:
    """Depth-first over the section tree, parents before children."""
    for node in nodes:
        yield node
        yield from walk(node.get("subsections", []))


def ability_key(creature: str, category: str, name: str) -> str:
    """
    Identify a stat block entry, which has no id of its own.

    The tail is exactly the shape ``references[].source.part`` already uses
    (``"actions/Bite"``), so mechanics edges land on the ability that causes
    them rather than being smeared across the whole creature.
    """
    return f"{creature}|{category}/{name}"


class Mapper:
    """Accumulates batches while walking the document once per collection."""

    def __init__(self, document: dict) -> None:
        self.document = document
        self.data = GraphData()
        self._nodes: dict[tuple[str, ...], NodeBatch] = {}
        self._edges: dict[tuple, EdgeBatch] = {}
        # id -> row, so a later collection can enrich a section it belongs to
        # instead of writing a second node beside it.
        self._section_rows: dict[str, dict] = {}
        self._section_batches: dict[str, NodeBatch] = {}
        self._by_name: dict[str, dict[str, str]] = defaultdict(dict)
        self._ambiguous: dict[str, set[str]] = defaultdict(set)

    # -- batch plumbing ----------------------------------------------------

    def node_batch(self, *labels: str, key: str = "id") -> NodeBatch:
        """One batch per exact label set, MERGE-ing on ``labels[0]``."""
        batch = self._nodes.get(labels)
        if batch is None:
            batch = NodeBatch(labels=list(labels), key=key)
            self._nodes[labels] = batch
            self.data.nodes.append(batch)
        return batch

    def edge(self, type_: str, start: tuple[str, str], start_id: str,
             end: tuple[str, str], end_id: str, **properties: Any) -> None:
        signature = (type_, start, end)
        batch = self._edges.get(signature)
        if batch is None:
            batch = EdgeBatch(type=type_, start_label=start[0], start_key=start[1],
                              end_label=end[0], end_key=end[1])
            self._edges[signature] = batch
            self.data.edges.append(batch)
        batch.add(start_id, end_id, **properties)

    def warn(self, message: str) -> None:
        self.data.warnings.append(message)

    # -- name resolution ---------------------------------------------------

    def index(self, kind: str, name: str, key: str) -> None:
        known = self._by_name[kind]
        if name in known and known[name] != key:
            self._ambiguous[kind].add(name)
            return  # first one wins; see resolve_item for the tie-break
        known[name] = key

    def lookup(self, kind: str, name: str) -> str | None:
        return self._by_name[kind].get(name)

    def relabel(self, section_id: str, *extra: str) -> dict:
        """
        Move a section's row into a batch carrying additional labels.

        Used where an entity *is* its section and so must not become a second
        node beside it — a gear item or a poison, which the book prints as a
        heading with prose.  The row moves rather than being copied, so the
        node is still written exactly once.
        """
        batch = self._section_batches[section_id]
        row = self._section_rows[section_id]
        batch.rows.remove(row)
        moved = self.node_batch(*batch.labels, *extra, key=batch.key)
        moved.rows.append(row)
        self._section_batches[section_id] = moved
        return row

    def section_row(self, section_id: str) -> dict:
        """The row already emitted for a section, so a later collection
        can add properties to it instead of writing a node beside it."""
        return self._section_rows[section_id]

    def resolve_target(self, type_: str, name: str) -> tuple[str, str, str] | None:
        """A reference target -> (label, key property, key value), or None."""
        if type_ in TARGET_TERM_TYPES:
            key = self.lookup("glossary", name)
            return ("GlossaryTerm", "name", key) if key else None
        key = self.lookup(type_, name)
        return ("Section", "id", key) if key else None


def add_sections(mapper: "Mapper") -> None:
    """
    Every tree node, with its entity type as a second label.

    Magic items are indexed in two passes: the heading "Deck of
    Illusions" appears twice, so a name alone is not a safe key and the
    node carrying ``item`` metadata wins.
    """
    nodes = list(walk(mapper.document["sections"]))

    for node in nodes:
        entity_type = node.get("entity_type") or "rule"
        label = SECTION_LABELS.get(entity_type)
        if label is None:
            mapper.warn(f"unknown entity_type {entity_type!r} on {node['id']}")
            label = "Rule"
        source = node.get("source") or {}
        row = {
            "id": node["id"],
            "name": node.get("heading"),
            "heading": node.get("heading"),
            "content": node.get("content"),
            "entity_type": entity_type,
            "depth": node["id"].count(".") + 1,
            "page_start": source.get("page_start"),
            "page_end": source.get("page_end"),
            "char_start": source.get("char_start"),
            "char_end": source.get("char_end"),
            "term_type": node.get("term_type"),
            "preamble": node.get("preamble"),
            "entries_json": as_json(node.get("entries")),
        }
        row |= _spell_properties(node.get("spell"))
        row |= _item_properties(node.get("item"))
        batch = mapper.node_batch("Section", label)
        batch.add(**row)
        mapper._section_rows[node["id"]] = batch.rows[-1]
        mapper._section_batches[node["id"]] = batch

        if entity_type in ("spell", "creature"):
            mapper.index(entity_type, node["heading"], node["id"])

        for child in node.get("subsections", []):
            mapper.edge("HAS_SUBSECTION", ("Section", "id"), node["id"],
                      ("Section", "id"), child["id"])

    for node in nodes:
        if node.get("entity_type") == "magic_item" and node.get("item"):
            mapper.index("magic_item", node["heading"], node["id"])
    for node in nodes:
        if node.get("entity_type") == "magic_item" and not node.get("item"):
            mapper._by_name["magic_item"].setdefault(node["heading"], node["id"])

    for name in sorted(mapper._ambiguous["magic_item"]):
        mapper.warn(f"ambiguous magic item name: {name!r}")


def _spell_properties(spell: dict | None) -> dict:
    if not spell:
        return {}
    components = spell.get("components") or {}
    damage = spell.get("damage") or []
    return {
        "level": spell.get("level"),
        "school": spell.get("school"),
        "spell_classes": spell.get("classes"),
        "ritual": spell.get("ritual"),
        "concentration": spell.get("concentration"),
        "casting_time": spell.get("casting_time"),
        "range": spell.get("range"),
        "duration": spell.get("duration"),
        "verbal": components.get("verbal"),
        "somatic": components.get("somatic"),
        "material": components.get("material"),
        "material_cost_gp": components.get("material_cost_gp"),
        "material_consumed": components.get("material_consumed"),
        "saving_throw": spell.get("saving_throw"),
        "attack_kind": (spell.get("attack") or {}).get("kind"),
        "conditions_imposed": spell.get("conditions_imposed"),
        **_damage_properties(damage),
    }


def _item_properties(item: dict | None) -> dict:
    if not item:
        return {}
    return {
        "category": item.get("category"),
        "subtype": item.get("subtype"),
        "rarity": item.get("rarity"),
        "requires_attunement": item.get("requires_attunement"),
        "attunement_requirement": item.get("attunement_requirement"),
    }


def _range_properties(range_ft: int | dict | None) -> dict:
    """A thrown or ranged weapon prints two ranges, a plain one prints one."""
    if isinstance(range_ft, dict):
        return {"range_ft": range_ft.get("normal"),
                "range_long_ft": range_ft.get("long")}
    return {"range_ft": range_ft}


def _damage_properties(damage: list[dict] | None) -> dict:
    """
    A damage list becomes parallel arrays.

    Neo4j has no list-of-maps, and the dice, type and average of one damage
    component belong together only by position — which is exactly what the
    arrays preserve.  Averages are dropped rather than padded with a
    sentinel when the book does not print them: spells give dice only, and a
    -1 among real averages would read as a number rather than as a gap.
    """
    entries = [d for d in (damage or []) if d]
    if not entries:
        return {}
    properties = {
        "damage_dice": [str(d.get("dice") or "") for d in entries],
        "damage_types": [str(d.get("type") or "") for d in entries],
    }
    averages = [d.get("average") for d in entries]
    if all(average is not None for average in averages):
        properties["damage_averages"] = [int(a) for a in averages]
    return properties


def add_creatures(mapper: "Mapper") -> None:
    """
    Enrich each creature's section node with its stat block, then give every
    trait, action and reaction a node of its own.

    A stat block *is* its section, so the two must line up exactly.  Both
    sides are 336 with unique names, and if that ever stops being true the
    load fails here rather than producing a graph quietly missing creatures.
    """
    for creature in mapper.document.get("creatures", []):
        name = creature["name"]
        section_id = mapper.lookup("creature", name)
        if section_id is None:
            raise ValueError(
                f"creature {name!r} has no section node to attach to; the "
                "stat blocks and the section tree have diverged")
        mapper.section_row(section_id).update(_creature_properties(creature))

        for category in ABILITY_LISTS:
            for entry in creature.get(category) or []:
                _add_ability(mapper, name, section_id, category, entry)


def _add_ability(mapper: "Mapper", creature: str, section_id: str,
                 category: str, entry: dict) -> None:
    key = ability_key(creature, category, entry["name"])
    attack = entry.get("attack") or {}
    save = entry.get("save") or {}
    uses = entry.get("uses") or {}
    mapper.node_batch("CreatureAbility", key="key").add(
        key=key,
        name=entry["name"],
        creature=creature,
        category=category,
        description=entry.get("description"),
        attack_kind=attack.get("kind"),
        attack_bonus=attack.get("bonus"),
        reach_ft=attack.get("reach_ft"),
        **_range_properties(attack.get("range_ft")),
        save_ability=save.get("ability"),
        save_dc=save.get("dc"),
        save_targets=save.get("targets"),
        uses_type=uses.get("type"),
        uses_times=uses.get("times"),
        uses_printed=uses.get("printed"),
        conditions_imposed=entry.get("conditions_imposed"),
        outcomes_json=as_json(entry.get("outcomes")),
        **_damage_properties(entry.get("damage")),
    )
    mapper.edge("HAS_ABILITY", ("Section", "id"), section_id,
                ("CreatureAbility", "key"), key, category=category)


def _creature_properties(creature: dict) -> dict:
    """Flatten a stat block into properties Neo4j can hold and query."""
    hp = creature.get("hp") or {}
    initiative = creature.get("initiative") or {}
    row: dict[str, Any] = {
        "creature_type": creature.get("type"),
        "alignment": creature.get("alignment"),
        "ac": creature.get("ac"),
        "cr": creature.get("cr"),
        "xp": creature.get("xp"),
        "xp_in_lair": creature.get("xp_in_lair"),
        "hp_average": hp.get("average"),
        "hp_formula": hp.get("formula"),
        "initiative_bonus": initiative.get("bonus"),
        "initiative_score": initiative.get("score"),
        "initiative_advantage": initiative.get("advantage"),
        "proficiency_bonus": creature.get("proficiency_bonus"),
        "senses": creature.get("senses"),
        "languages": creature.get("languages"),
        "skills_json": as_json(creature.get("skills")),
        "immunities": creature.get("immunities"),
        "resistances": creature.get("resistances"),
        "vulnerabilities": creature.get("vulnerabilities"),
        "condition_immunities": creature.get("condition_immunities"),
        "gear": creature.get("gear"),
        "warnings": creature.get("warnings"),
    }
    for movement, distance in (creature.get("speed") or {}).items():
        row[f"speed_{movement}"] = distance
    for ability in ABILITIES:
        scores = (creature.get("abilities") or {}).get(ability) or {}
        row[f"{ability}_score"] = scores.get("score")
        row[f"{ability}_modifier"] = scores.get("modifier")
        row[f"{ability}_save"] = scores.get("save")
    return {k: v for k, v in row.items() if v is not None and v != []}


def add_glossary(mapper: "Mapper") -> None:
    """
    Conditions, actions, damage types and the rest of the Rules Glossary.

    These stay separate from their sections: all thirteen damage types are
    printed in one table and so share the section id ``11.2.46.1``, which
    makes the section useless as a key.  ``DEFINED_IN`` keeps the link to the
    prose without pretending the two are the same node.
    """
    for term in mapper.document.get("glossary", []):
        term_type = term.get("term_type") or "definition"
        label = GLOSSARY_LABELS.get(term_type)
        if label is None:
            mapper.warn(f"unknown glossary term_type {term_type!r}")
            label = "Definition"
        mapper.node_batch("GlossaryTerm", label, key="name").add(
            name=term["name"],
            term_type=term_type,
            description=term.get("description"),
            section_id=term.get("section_id"),
            **_pages(term),
        )
        mapper.index("glossary", term["name"], term["name"])
        mapper.index(term_type, term["name"], term["name"])
        if term.get("section_id"):
            mapper.edge("DEFINED_IN", ("GlossaryTerm", "name"), term["name"],
                        ("Section", "id"), term["section_id"])


def add_equipment(mapper: "Mapper") -> None:
    """
    Weapons, armour, gear and poisons.

    Weapons and armour are printed only as table rows, so they become nodes
    of their own.  Gear and poisons are printed as a heading with prose, so
    they *are* their section and fold into it — otherwise the same paragraph
    would be stored twice, once as a section and once as an item, and every
    edge drawn from it would exist twice over.
    """
    for item in mapper.document.get("equipment", []):
        kind = item.get("kind") or "gear"
        label = EQUIPMENT_LABELS.get(kind)
        if label is None:
            mapper.warn(f"unknown equipment kind {kind!r}")
            label = "Gear"
        damage = item.get("damage") or {}
        section_id = item.get("section_id")
        if section_id:
            _fold_into_section(mapper, item, label, section_id, damage)
            mapper.index("equipment", item["name"], item["name"])
            continue
        mapper.node_batch("Equipment", label, key="name").add(
            name=item["name"],
            kind=kind,
            category=item.get("category"),
            description=item.get("description"),
            cost=item.get("cost"),
            cost_gp=item.get("cost_gp"),
            weight_lb=item.get("weight_lb"),
            properties=item.get("properties"),
            mastery=item.get("mastery"),
            damage_dice=damage.get("dice"),
            damage_type=damage.get("type"),
            armor_class=item.get("armor_class"),
            strength_requirement=item.get("strength_requirement"),
            stealth_disadvantage=item.get("stealth_disadvantage"),
            poison_type=item.get("poison_type"),
            **_pages(item),
        )
        mapper.index("equipment", item["name"], item["name"])


def _fold_into_section(mapper: "Mapper", item: dict, label: str,
                       section_id: str, damage: dict) -> None:
    """
    Add the item's labels and properties to the section that prints it.

    ``name`` deliberately overwrites the heading-derived one: the heading is
    "Acid (25 GP)" and the entity is "Acid", and `heading` still holds what
    the book prints.
    """
    if section_id not in mapper._section_rows:
        mapper.warn(f"{item['name']!r} names section {section_id}, which does "
                    "not exist")
        return
    row = mapper.relabel(section_id, "Equipment", label)
    row.update(clean({
        "name": item["name"],
        "kind": item.get("kind"),
        "category": item.get("category"),
        "cost": item.get("cost"),
        "cost_gp": item.get("cost_gp"),
        "weight_lb": item.get("weight_lb"),
        "properties": item.get("properties"),
        "mastery": item.get("mastery"),
        "damage_dice": damage.get("dice"),
        "damage_type": damage.get("type"),
        "armor_class": item.get("armor_class"),
        "strength_requirement": item.get("strength_requirement"),
        "stealth_disadvantage": item.get("stealth_disadvantage"),
        "poison_type": item.get("poison_type"),
    }))


def add_classes(mapper: "Mapper") -> None:
    """
    Classes, their subclasses, their features and the level table.

    The twenty progression rows become ``:ClassLevel`` nodes so a query can
    ask what a level grants without unpacking a list property, and the
    resources map — which Neo4j cannot store — becomes parallel arrays.
    """
    for klass in mapper.document.get("classes", []):
        name = klass["name"]
        mapper.node_batch("Class", key="name").add(
            name=name,
            section_id=klass.get("section_id"),
            hit_point_die=klass.get("hit_point_die"),
            primary_ability=klass.get("primary_ability"),
            saving_throw=klass.get("saving_throw"),
            skill_proficiencies=klass.get("skill_proficiencies"),
            tool_proficiencies=klass.get("tool_proficiencies"),
            weapon_proficiencies=klass.get("weapon_proficiencies"),
            armor_training=klass.get("armor_training"),
            starting_equipment=klass.get("starting_equipment"),
            **_pages(klass),
        )
        mapper.index("class", name, name)
        if klass.get("section_id"):
            mapper.edge("DEFINED_IN", ("Class", "name"), name,
                        ("Section", "id"), klass["section_id"])

        features = {f["name"]: f for f in klass.get("features", [])}
        for feature in klass.get("features", []):
            _link_feature(mapper, ("Class", "name"), name, feature)

        for subclass in klass.get("subclasses", []):
            _add_subclass(mapper, name, subclass)
            features |= {f["name"]: f for f in subclass.get("features", [])}

        for row in klass.get("progression", []):
            _add_class_level(mapper, name, row, features)


def _add_subclass(mapper: "Mapper", class_name: str, subclass: dict) -> None:
    key = subclass.get("section_id") or f"{class_name}|{subclass['name']}"
    mapper.node_batch("Subclass", key="key").add(
        key=key,
        name=subclass["name"],
        parent_class=class_name,
        section_id=subclass.get("section_id"),
        description=subclass.get("description"),
    )
    mapper.edge("HAS_SUBCLASS", ("Class", "name"), class_name,
                ("Subclass", "key"), key)
    if subclass.get("section_id"):
        mapper.edge("DEFINED_IN", ("Subclass", "key"), key,
                    ("Section", "id"), subclass["section_id"])
    for feature in subclass.get("features", []):
        _link_feature(mapper, ("Subclass", "key"), key, feature)


def _link_feature(mapper: "Mapper", owner: tuple[str, str], owner_id: str,
                  feature: dict) -> None:
    """Point at the feature's own section node rather than copying its prose."""
    section_id = feature.get("section_id")
    if not section_id:
        mapper.warn(f"class feature {feature['name']!r} has no section_id")
        return
    mapper.edge("HAS_FEATURE", owner, owner_id, ("Section", "id"), section_id,
                level=feature.get("level"))


def _add_class_level(mapper: "Mapper", class_name: str, row: dict,
                     features: dict[str, dict]) -> None:
    level = row["level"]
    key = f"{class_name}|{level}"
    resources = row.get("resources") or {}
    mapper.node_batch("ClassLevel", key="key").add(
        key=key,
        parent_class=class_name,
        level=level,
        proficiency_bonus=row.get("proficiency_bonus"),
        resource_names=list(resources),
        resource_values=[str(v) for v in resources.values()],
    )
    mapper.edge("AT_LEVEL", ("Class", "name"), class_name,
                ("ClassLevel", "key"), key, level=level)
    for feature_name in row.get("features", []):
        feature = features.get(feature_name)
        if feature is None or not feature.get("section_id"):
            continue  # the table names some features the chapter never details
        mapper.edge("GRANTS_FEATURE", ("ClassLevel", "key"), key,
                    ("Section", "id"), feature["section_id"])


def add_origins(mapper: "Mapper") -> None:
    """Species, backgrounds and feats — same shape, three labels."""
    for kind, label, collection in (
        ("species", "Species", "species"),
        ("background", "Background", "backgrounds"),
        ("feat", "Feat", "feats"),
    ):
        for entry in mapper.document.get(collection, []):
            name = entry["name"]
            mapper.node_batch(label, key="name").add(
                name=name,
                description=entry.get("description"),
                section_id=entry.get("section_id"),
                size=entry.get("size"),
                speed=entry.get("speed"),
                creature_type=entry.get("creature_type"),
                ability_scores=entry.get("ability_scores"),
                skill_proficiencies=entry.get("skill_proficiencies"),
                tool_proficiency=entry.get("tool_proficiency"),
                equipment=entry.get("equipment"),
                category=entry.get("category"),
                feat_group=entry.get("group"),
                **_pages(entry),
            )
            mapper.index(kind, name, name)
            if entry.get("section_id"):
                mapper.edge("DEFINED_IN", (label, "name"), name,
                            ("Section", "id"), entry["section_id"])
            for trait in entry.get("traits") or []:
                _add_trait(mapper, label, name, trait)


def _add_trait(mapper: "Mapper", owner_label: str, owner: str,
               trait: dict) -> None:
    key = f"{owner}|{trait['name']}"
    mapper.node_batch("Trait", key="key").add(
        key=key, name=trait["name"], owner=owner,
        description=trait.get("description"))
    mapper.edge("HAS_TRAIT", (owner_label, "name"), owner,
                ("Trait", "key"), key)


def _pages(entry: dict) -> dict:
    source = entry.get("source") or {}
    return {"page_start": source.get("page_start"),
            "page_end": source.get("page_end")}


def add_references(mapper: "Mapper") -> None:
    """
    The cross-references stage 1 found in the book's own markup.

    Neither endpoint is ever created here.  A target carries a name and a
    type but no id, and inventing a node for a name that fails to resolve
    would hide the drift between the stages that this pass exists to catch,
    so unresolved ends are collected in ``data.unresolved`` instead.
    """
    for reference in mapper.document.get("references", []):
        source, target = reference["source"], reference["target"]
        relation = reference["relation"].upper()

        start = _resolve_source(mapper, source)
        if start is None:
            mapper.data.unresolved.append(
                {"end": "source", "relation": relation,
                 "type": source["type"], "name": source.get("name", ""),
                 "part": source.get("part", "")})
            continue

        end = mapper.resolve_target(target["type"], target["name"])
        if end is None:
            mapper.data.unresolved.append(
                {"end": "target", "relation": relation,
                 "type": target["type"], "name": target["name"], "part": ""})
            continue

        start_label, start_key, start_id = start
        end_label, end_key, end_id = end
        mapper.edge(relation, (start_label, start_key), start_id,
                    (end_label, end_key), end_id)


def _resolve_source(mapper: "Mapper", source: dict) -> tuple[str, str, str] | None:
    """
    Sections carry their id; stat blocks and table rows do not.

    A creature source names the entry it came from in ``part``
    (``"actions/Bite"``), which is the tail of a ``:CreatureAbility`` key, so
    those edges attach to the ability rather than the whole creature.
    """
    if source.get("part"):
        key = f"{source['name']}|{source['part']}"
        return ("CreatureAbility", "key", key)
    if source.get("id"):
        return ("Section", "id", source["id"])
    name = mapper.lookup("equipment", source.get("name", ""))
    return ("Equipment", "name", name) if name else None


def add_derived(mapper: "Mapper") -> None:
    """
    Edges implied by list fields on entities already loaded.

    A creature's ``immunities`` and ``gear``, a spell's class list, a
    poison's delivery type: names that resolve to a node become a
    relationship, so they can be traversed rather than scanned.
    """
    for creature in mapper.document.get("creatures", []):
        section_id = mapper.lookup("creature", creature["name"])
        start = ("Section", "id")
        for field, relation, kind in (
            ("immunities", "IMMUNE_TO", "damage type"),
            ("resistances", "RESISTANT_TO", "damage type"),
            ("vulnerabilities", "VULNERABLE_TO", "damage type"),
            ("condition_immunities", "IMMUNE_TO_CONDITION", "condition"),
        ):
            for name in creature.get(field) or []:
                if mapper.lookup(kind, name):
                    mapper.edge(relation, start, section_id,
                                ("GlossaryTerm", "name"), name)
        for name in creature.get("gear") or []:
            if mapper.lookup("equipment", name):
                mapper.edge("CARRIES", start, section_id,
                            ("Equipment", "name"), name)

    for node in walk(mapper.document["sections"]):
        # A node's own ``creatures`` list only ever names itself, so
        # containment is left to HAS_SUBSECTION rather than duplicated.
        for name in node.get("spell", {}).get("classes", []) or []:
            if mapper.lookup("class", name):
                mapper.edge("ON_SPELL_LIST", ("Section", "id"), node["id"],
                            ("Class", "name"), name)

    for item in mapper.document.get("equipment", []):
        # The four delivery types are defined in one passage of their own,
        # which nothing else refers to; without this edge it is unreachable
        # from the poisons it describes.
        name = item.get("poison_type")
        if name and mapper.lookup("poison type", name):
            mapper.edge("HAS_POISON_TYPE", ("Equipment", "name"), item["name"],
                        ("GlossaryTerm", "name"), name)

    for background in mapper.document.get("backgrounds", []):
        feat = _feat_name(background.get("feat"))
        if feat and mapper.lookup("feat", feat):
            mapper.edge("GRANTS_FEAT", ("Background", "name"),
                        background["name"], ("Feat", "name"), feat)


def _feat_name(printed: str | None) -> str | None:
    """``'Magic Initiate (Cleric) (see "Feats")'`` -> ``'Magic Initiate'``."""
    if not printed:
        return None
    return re.split(r"\s*\(", printed, maxsplit=1)[0].strip() or None


def build(document: dict) -> GraphData:
    """The whole translation, in the order the passes depend on each other."""
    mapper = Mapper(document)
    add_sections(mapper)      # indexes spells, creatures and magic items
    add_glossary(mapper)      # indexes conditions, damage types, actions
    add_equipment(mapper)
    add_classes(mapper)
    add_origins(mapper)
    add_creatures(mapper)     # needs the creature index from add_sections
    add_references(mapper)    # needs every index above
    add_derived(mapper)
    return mapper.data
