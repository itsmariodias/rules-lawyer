"""
The stage 1 document as node and edge batches.  Pure: no driver, no I/O.

Every tree node is a ``:Section`` keyed on its dotted id, with its entity
type as a second label.  Creatures, gear and poisons fold into the section
that prints them.  Other collections are separate nodes joined by
``DEFINED_IN``; glossary terms cannot fold because several share a section
(all thirteen damage types are ``11.2.46.1``).
"""

from __future__ import annotations

import re
from collections import defaultdict
from typing import Any, Iterator

from .model import EdgeBatch, GraphData, NodeBatch, as_json, clean

# --------------------------------------------------------------------------
# Vocabulary
# --------------------------------------------------------------------------

# Where a flat collection has the plain name (Feat, Equipment), the section
# label is qualified (FeatSection, EquipmentSection).
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

# Reference target type -> glossary term_type.
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
    The ``:CreatureAbility`` key for a stat block entry.

    The part after ``|`` matches ``references[].source.part``, so
    ``_resolve_source`` can attach reference edges to the ability.

    Args:
        creature: The creature's name.
        category: e.g. ``"actions"``.
        name: The entry's name.

    Returns:
        e.g. ``"Goblin|actions/Bite"``.
    """
    return f"{creature}|{category}/{name}"


class Mapper:
    """Accumulates batches and name indexes across the ``add_*`` passes."""

    def __init__(self, document: dict) -> None:
        self.document = document
        self.data = GraphData()
        self._nodes: dict[tuple[str, ...], NodeBatch] = {}
        self._edges: dict[tuple, EdgeBatch] = {}
        # Section id -> its emitted row and batch, for folding entities in.
        self._section_rows: dict[str, dict] = {}
        self._section_batches: dict[str, NodeBatch] = {}
        self._by_name: dict[str, dict[str, str]] = defaultdict(dict)
        self._ambiguous: dict[str, set[str]] = defaultdict(set)

    # -- batch plumbing ----------------------------------------------------

    def node_batch(self, *labels: str, key: str = "id") -> NodeBatch:
        """
        The batch for an exact label set, created on first use.

        Args:
            *labels: Labels in order; rows MERGE on the first.
            key: The property rows MERGE on.

        Returns:
            The shared batch for that label set.
        """
        batch = self._nodes.get(labels)
        if batch is None:
            batch = NodeBatch(labels=list(labels), key=key)
            self._nodes[labels] = batch
            self.data.nodes.append(batch)
        return batch

    def edge(self, type_: str, start: tuple[str, str], start_id: str,
             end: tuple[str, str], end_id: str, **properties: Any) -> None:
        """
        Add an edge to the batch for its type and endpoint labels.

        Args:
            type_: Relationship type.
            start: ``(label, key_property)`` of the start node.
            start_id: Key value of the start node.
            end: ``(label, key_property)`` of the end node.
            end_id: Key value of the end node.
            **properties: Relationship properties.
        """
        signature = (type_, start, end)
        batch = self._edges.get(signature)
        if batch is None:
            batch = EdgeBatch(type=type_, start_label=start[0], start_key=start[1],
                              end_label=end[0], end_key=end[1])
            self._edges[signature] = batch
            self.data.edges.append(batch)
        batch.add(start_id, end_id, **properties)

    def warn(self, message: str) -> None:
        """Record a non-fatal mapping problem in ``data.warnings``."""
        self.data.warnings.append(message)

    # -- name resolution ---------------------------------------------------

    def index(self, kind: str, name: str, key: str) -> None:
        """
        Record that ``name`` of ``kind`` resolves to node key ``key``.

        The first key for a name wins; a conflicting one marks it ambiguous.
        """
        known = self._by_name[kind]
        if name in known and known[name] != key:
            self._ambiguous[kind].add(name)
            return
        known[name] = key

    def lookup(self, kind: str, name: str) -> str | None:
        """The key ``index`` recorded for a name, or None."""
        return self._by_name[kind].get(name)

    def relabel(self, section_id: str, *extra: str) -> dict:
        """
        Move a section's row to the batch with ``extra`` labels added.

        Args:
            section_id: The section to relabel.
            *extra: Labels to add.

        Returns:
            The moved row, for the caller to add properties to.
        """
        batch = self._section_batches[section_id]
        row = self._section_rows[section_id]
        batch.rows.remove(row)
        moved = self.node_batch(*batch.labels, *extra, key=batch.key)
        moved.rows.append(row)
        self._section_batches[section_id] = moved
        return row

    def section_row(self, section_id: str) -> dict:
        """The row already emitted for a section, for adding properties to."""
        return self._section_rows[section_id]

    def resolve_target(self, type_: str, name: str) -> tuple[str, str, str] | None:
        """
        Args:
            type_: A reference target's ``type``.
            name: Its ``name``.

        Returns:
            ``(label, key_property, key_value)``, or None if unresolved.
        """
        if type_ in TARGET_TERM_TYPES:
            key = self.lookup("glossary", name)
            return ("GlossaryTerm", "name", key) if key else None
        key = self.lookup(type_, name)
        return ("Section", "id", key) if key else None


def add_sections(mapper: "Mapper") -> None:
    """
    Every tree node, with its entity type as a second label, plus
    ``HAS_SUBSECTION``.  Indexes spells, creatures and magic items by name.

    "Deck of Illusions" heads two sections, so magic items are indexed in two
    passes and the one carrying ``item`` metadata wins.
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
    """``range_ft`` is an int, or ``{"normal", "long"}`` for ranged attacks."""
    if isinstance(range_ft, dict):
        return {"range_ft": range_ft.get("normal"),
                "range_long_ft": range_ft.get("long")}
    return {"range_ft": range_ft}


def _damage_properties(damage: list[dict] | None) -> dict:
    """
    A damage list as parallel ``damage_dice``/``damage_types``/
    ``damage_averages`` arrays, since Neo4j has no list of maps.

    ``damage_averages`` is omitted unless every entry has one (spells print
    dice only); a sentinel would read as a real number.
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
    Fold each stat block into its section, and add a ``:CreatureAbility``
    per entry with ``HAS_ABILITY``.

    Raises:
        ValueError: A creature has no ``creature`` section of the same name.
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
    """A stat block's fields as flat section properties, Nones dropped."""
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
    A ``:GlossaryTerm`` per glossary entry, ``DEFINED_IN`` its section.

    Indexes each by name under ``"glossary"`` and under its term type.
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

    Items with a ``section_id`` (gear, poisons) fold into that section;
    weapons and armour, which are only table rows, become ``:Equipment``
    nodes.
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

    ``name`` overwrites the section's ("Acid (25 GP)" becomes "Acid");
    ``heading`` keeps the printed form.
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
    ``:Class``, ``:Subclass`` and one ``:ClassLevel`` per progression row,
    with ``HAS_FEATURE``, ``HAS_SUBCLASS``, ``AT_LEVEL`` and
    ``GRANTS_FEATURE``.  A level's resources become parallel
    ``resource_names``/``resource_values`` arrays.
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
    """``HAS_FEATURE`` from the owner to the feature's section."""
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
            continue  # named in the table but never given a section
        mapper.edge("GRANTS_FEATURE", ("ClassLevel", "key"), key,
                    ("Section", "id"), feature["section_id"])


def add_origins(mapper: "Mapper") -> None:
    """Species, backgrounds and feats, each with ``DEFINED_IN`` and ``HAS_TRAIT``."""
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
    One edge per stage 1 reference, relation uppercased.

    Endpoints are resolved, never created; unresolved ones go to
    ``data.unresolved`` so drift between the stages is reported.
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
    A reference source as ``(label, key_property, key_value)``.

    Creature sources resolve to the ability named by ``part``; sections by
    id; equipment by name.  None if equipment does not resolve.
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
    Edges from list fields whose names resolve to nodes: creature
    defences and gear, spell class lists, poison types, background feats.
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
        for name in node.get("spell", {}).get("classes", []) or []:
            if mapper.lookup("class", name):
                mapper.edge("ON_SPELL_LIST", ("Section", "id"), node["id"],
                            ("Class", "name"), name)

    for item in mapper.document.get("equipment", []):
        # Nothing references the poison types, so this is their only edge.
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
    """
    Map a stage 1 document to graph batches.

    Args:
        document: What ``srd.load()`` returns.

    Returns:
        Every batch, plus unresolved references and warnings.

    Raises:
        ValueError: A stat block has no matching section.
        TypeError: A property is not a Neo4j value.
    """
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
