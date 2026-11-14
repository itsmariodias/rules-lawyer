"""The book's closed vocabularies: what a section, condition, item or attack can be.

``StrEnum``s: each member is its own string, so the JSON holds the same values
and a member compares equal to the text the book prints.
"""

from __future__ import annotations

from enum import StrEnum


class EntityType(StrEnum):
    """What a section is: ``rule`` unless its blocks or a record say otherwise."""

    RULE = "rule"
    FRONT_MATTER = "front_matter"
    SPELL = "spell"
    MAGIC_ITEM = "magic_item"
    CREATURE = "creature"
    CREATURE_GROUP = "creature_group"
    GLOSSARY_TERM = "glossary_term"
    ENVIRONMENTAL_EFFECT = "environmental_effect"
    TRAP = "trap"
    CONTAGION = "contagion"
    CLASS = "class"
    SUBCLASS = "subclass"
    CLASS_FEATURE = "class_feature"
    ORIGIN = "origin"
    FEAT = "feat"
    EQUIPMENT = "equipment"


class Condition(StrEnum):
    """The fifteen conditions (Rules Glossary)."""

    BLINDED = "Blinded"
    CHARMED = "Charmed"
    DEAFENED = "Deafened"
    EXHAUSTION = "Exhaustion"
    FRIGHTENED = "Frightened"
    GRAPPLED = "Grappled"
    INCAPACITATED = "Incapacitated"
    INVISIBLE = "Invisible"
    PARALYZED = "Paralyzed"
    PETRIFIED = "Petrified"
    POISONED = "Poisoned"
    PRONE = "Prone"
    RESTRAINED = "Restrained"
    STUNNED = "Stunned"
    UNCONSCIOUS = "Unconscious"


class Ability(StrEnum):
    """The six abilities, as saving throws name them."""

    STRENGTH = "Strength"
    DEXTERITY = "Dexterity"
    CONSTITUTION = "Constitution"
    INTELLIGENCE = "Intelligence"
    WISDOM = "Wisdom"
    CHARISMA = "Charisma"


class DamageType(StrEnum):
    """The thirteen damage types (the Damage Types table, page 180)."""

    ACID = "Acid"
    BLUDGEONING = "Bludgeoning"
    COLD = "Cold"
    FIRE = "Fire"
    FORCE = "Force"
    LIGHTNING = "Lightning"
    NECROTIC = "Necrotic"
    PIERCING = "Piercing"
    POISON = "Poison"
    PSYCHIC = "Psychic"
    RADIANT = "Radiant"
    SLASHING = "Slashing"
    THUNDER = "Thunder"


class Action(StrEnum):
    """The twelve actions (Rules Glossary, "[Action]")."""

    ATTACK = "Attack"
    DASH = "Dash"
    DISENGAGE = "Disengage"
    DODGE = "Dodge"
    HELP = "Help"
    HIDE = "Hide"
    INFLUENCE = "Influence"
    MAGIC = "Magic"
    READY = "Ready"
    SEARCH = "Search"
    STUDY = "Study"
    UTILIZE = "Utilize"


class AreaOfEffect(StrEnum):
    """The six areas of effect (Rules Glossary, "[Area of Effect]")."""

    CONE = "Cone"
    CUBE = "Cube"
    CYLINDER = "Cylinder"
    EMANATION = "Emanation"
    LINE = "Line"
    SPHERE = "Sphere"


class TermType(StrEnum):
    """What a glossary term is: its heading's tag ("Prone [Condition]"), a definition if it has
    none, or one of the types defined in a passage rather than a heading of their own."""

    DEFINITION = "definition"
    CONDITION = "condition"
    ACTION = "action"
    AREA_OF_EFFECT = "area of effect"
    HAZARD = "hazard"
    ATTITUDE = "attitude"
    DAMAGE_TYPE = "damage type"
    POISON_TYPE = "poison type"


class ItemKind(StrEnum):
    """What an equipment record is."""

    WEAPON = "weapon"
    ARMOR = "armor"
    GEAR = "gear"
    POISON = "poison"


class Rarity(StrEnum):
    """A magic item's rarity, as its subtitle prints it."""

    COMMON = "Common"
    UNCOMMON = "Uncommon"
    RARE = "Rare"
    VERY_RARE = "Very Rare"
    LEGENDARY = "Legendary"
    ARTIFACT = "Artifact"
    VARIES = "Rarity Varies"


class Coin(StrEnum):
    """The coins (the Coin Values table, page 89)."""

    CP = "CP"
    SP = "SP"
    EP = "EP"
    GP = "GP"
    PP = "PP"

    @property
    def in_gold(self) -> float:
        """The coin's value in gold pieces."""
        return {"CP": 0.01, "SP": 0.1, "EP": 0.5, "GP": 1.0, "PP": 10.0}[self.value]


class AttackKind(StrEnum):
    """An attack roll's kind: "Melee or Ranged Attack Roll" is ``melee_or_ranged``."""

    MELEE = "melee"
    RANGED = "ranged"
    MELEE_OR_RANGED = "melee_or_ranged"


class UsesType(StrEnum):
    """How an entry's use is limited: "(Recharge 5–6)", "(2/Day)", or otherwise."""

    RECHARGE = "recharge"
    PER_DAY = "per_day"
    OTHER = "other"


class StatPart(StrEnum):
    """A stat block's sections, by their printed titles."""

    TRAITS = "Traits"
    ACTIONS = "Actions"
    BONUS_ACTIONS = "Bonus Actions"
    REACTIONS = "Reactions"
    LEGENDARY_ACTIONS = "Legendary Actions"

    @property
    def field(self) -> str:
        """The creature record's field for this section ("bonus_actions")."""
        return self.value.lower().replace(" ", "_")


class Target(StrEnum):
    """What a cross-reference points at."""

    SPELL = "spell"
    MAGIC_ITEM = "magic_item"
    CREATURE = "creature"
    CONDITION = "condition"
    ACTION = "action"
    DAMAGE_TYPE = "damage_type"
    AREA_OF_EFFECT = "area_of_effect"
    TABLE = "table"

    @property
    def relation(self) -> str:
        """The edge's relation when the text mentions the target ("references_spell")."""
        return f"references_{self.value}"


def alternatives(vocabulary: type[StrEnum]) -> str:
    """A regex alternation of a vocabulary's values, longest first ("Very Rare" before "Rare")."""
    return "|".join(sorted((member.value for member in vocabulary), key=len, reverse=True))
