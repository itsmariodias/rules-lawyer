"""
Turn the SRD's cross-references into graph edges, and its glossary into nodes.

The book marks every cross-reference typographically: a spell or magic item
is printed in italics (*Dispel Magic*), a creature in bold (**Treant**).  The
layout pass preserves that as markdown emphasis, which makes the references
recoverable — but only if they are resolved against the entities that were
actually extracted.  Italic is also used for ordinary emphasis and for book
titles, so a span becomes an edge only when it names something known.

Conditions, actions and areas of effect are not marked up.  They are matched
instead on the phrasing the rules always use — "the Prone condition", "the
Utilize action", "a 20-foot Cone" — which is what keeps common words like
"Cover" or "Attack" from matching as bare nouns.

Edges say *references*, never *imposes*.  Typography records that two things
are mentioned together; whether a creature inflicts the Poisoned condition or
is immune to it is a question about the sentence, not about the markup.
"""

from __future__ import annotations

import re

# The glossary tags its own entries: "Blinded [Condition]", "Dash [Action]".
_GLOSSARY_TAG_RE = re.compile(r"^(.*?)\s*\[(.+?)\]\s*$")

# Emphasis spans, as the layout pass writes them.
_ITALIC_RE = re.compile(r"(?<!\*)_([^_\n]+?)_(?!\*)")
_BOLD_RE = re.compile(r"\*\*([^*\n]+?)\*\*")

# Areas of effect are always sized: "a 20-foot-radius Sphere", "a 60-foot Cone".
_AREA_RE = re.compile(
    r"\d+-foot[\w-]*\s+(Cone|Cube|Cylinder|Emanation|Line|Sphere)\b"
)

# Glossary tags that have a dependable phrasing to match on in running text.
MATCHABLE_TERM_TYPES = {"condition", "action", "area of effect", "damage type"}


def _slug(tag: str) -> str:
    return tag.strip().lower()


# ---------------------------------------------------------------------------
# Glossary
# ---------------------------------------------------------------------------

def extract_glossary(nodes) -> list[dict]:
    """
    Read the Rules Glossary into typed term records.

    The book does the typing itself, bracketed after the term, so a condition
    is a condition because the SRD says so rather than because of a list kept
    here.  Untagged entries are plain definitions.
    """
    glossary: list[dict] = []
    for node in nodes:
        if not node.pop("_is_glossary", False):
            continue
        m = _GLOSSARY_TAG_RE.match(node["heading"])
        term = (m.group(1) if m else node["heading"]).strip()
        term_type = _slug(m.group(2)) if m else "definition"

        node["term"] = term
        node["term_type"] = term_type
        node["entity_type"] = "glossary_term"

        glossary.append({
            "name": term,
            "term_type": term_type,
            "description": node["content"],
            "section_id": node["id"],
            "source": {k: node["source"][k]
                       for k in ("pdf", "page_start", "page_end")},
        })
    return glossary


def mark_glossary_nodes(nodes) -> None:
    """Flag the children of "Rules Definitions" so they can be read as terms."""
    for node in nodes:
        if node["heading"] == "Rules Definitions":
            for child in node["subsections"]:
                child["_is_glossary"] = True


# ---------------------------------------------------------------------------
# Name resolution
# ---------------------------------------------------------------------------

_TRAILING_PUNCT = " .,;:!?’'\"()"


def normalise(name: str) -> str:
    """Strip emphasis and trailing punctuation from a captured span."""
    return re.sub(r"[*_]+", "", name).strip(_TRAILING_PUNCT).strip()


class NameIndex:
    """
    Resolve a captured span to a known entity name.

    The book pluralises references freely ("two **Ghasts**"), so a lookup
    falls back to the singular.  Matching is case-insensitive because a few
    references appear mid-sentence in lower case.
    """

    def __init__(self, names) -> None:
        self._by_key = {n.lower(): n for n in names}

    def resolve(self, span: str) -> str | None:
        key = normalise(span).lower()
        if not key:
            return None
        if key in self._by_key:
            return self._by_key[key]
        for suffix, cut in (("ies", 3), ("es", 2), ("s", 1)):
            if key.endswith(suffix):
                stem = key[:-cut]
                if suffix == "ies":
                    stem += "y"
                if stem in self._by_key:
                    return self._by_key[stem]
        return None


# ---------------------------------------------------------------------------
# Reference scanning
# ---------------------------------------------------------------------------

# The separators a list of names is written with.  The longest first, so
# ", and " is one boundary rather than a comma and a stray "and".
_NAME_SPLIT_RE = re.compile(r",\s+(?:and|or)\s+|,\s+|\s+and\s+|\s+or\s+")


class ReferenceScanner:
    """Finds every resolvable cross-reference in a piece of SRD text."""

    def __init__(self, spells, magic_items, creatures, glossary) -> None:
        self.spells = NameIndex(spells)
        self.magic_items = NameIndex(magic_items)
        self.creatures = NameIndex(creatures)

        self.terms: dict[str, list[str]] = {}
        for entry in glossary:
            if entry["term_type"] in MATCHABLE_TERM_TYPES:
                self.terms.setdefault(entry["term_type"], []).append(entry["name"])

        self._condition_re = self._phrase_re(self.terms.get("condition", []), "condition")
        self._action_re = self._phrase_re(self.terms.get("action", []), "action")
        self._damage_re = self._phrase_re(self.terms.get("damage type", []), "damage")

    @staticmethod
    def _phrase_re(names: list[str], noun: str) -> re.Pattern | None:
        """
        The phrasing the rules always use, for one name or for a list of them.

        The book routinely names several at once — "the Deafened and
        Frightened conditions", "Bludgeoning, Piercing, and Slashing damage"
        — and a pattern built for a single name before a singular noun reads
        none of them: 43 such phrases across conditions, actions and damage
        types went unlinked, which is how the Tarrasque came to reference no
        condition at all.

        A list is read generously here, *or* included, because these are
        mentions: the text does name every one of them.  Whether a condition
        is inflicted rather than mentioned is a separate and stricter
        question, answered by ``mechanics.conditions_imposed``.
        """
        if not names:
            return None
        alternatives = "|".join(re.escape(n) for n in sorted(names, key=len, reverse=True))
        one = f"(?:{alternatives})"
        return re.compile(
            rf"\b({one}(?:(?:,|\s+and|\s+or)\s+{one})*)\s+{noun}s?\b")

    def scan(self, text: str) -> list[tuple[str, str]]:
        """Return (target_type, name) pairs, deduplicated, in a stable order."""
        found: list[tuple[str, str]] = []

        for m in _ITALIC_RE.finditer(text):
            span = m.group(1)
            name = self.spells.resolve(span)
            if name:
                found.append(("spell", name))
                continue
            name = self.magic_items.resolve(span)
            if name:
                found.append(("magic_item", name))

        for m in _BOLD_RE.finditer(text):
            name = self.creatures.resolve(m.group(1))
            if name:
                found.append(("creature", name))

        for kind, pattern in (("condition", self._condition_re),
                              ("action", self._action_re),
                              ("damage_type", self._damage_re)):
            if pattern:
                found += [(kind, name) for m in pattern.finditer(text)
                          for name in _NAME_SPLIT_RE.split(m.group(1))]
        found += [("area_of_effect", m.group(1)) for m in _AREA_RE.finditer(text)]

        return list(dict.fromkeys(found))


# ---------------------------------------------------------------------------
# Edge building
# ---------------------------------------------------------------------------

def _edges(scanner: ReferenceScanner, text: str, source: dict,
           imposed: list[str] | None = None) -> list[dict]:
    """
    Turn one piece of text into edges.

    A condition the caller has determined is actually inflicted gets the
    stronger ``imposes_condition`` relation; everything else stays a mention.
    """
    imposed = set(imposed or ())
    edges = []
    for kind, name in scanner.scan(text or ""):
        relation = f"references_{kind}"
        if kind == "condition" and name in imposed:
            relation = "imposes_condition"
        edges.append({"source": source,
                      "target": {"type": kind, "name": name},
                      "relation": relation})
    return edges


CREATURE_PARTS = ("traits", "actions", "bonus_actions", "reactions", "legendary_actions")


def extract_references(nodes, creatures, equipment, glossary) -> list[dict]:
    """
    Build the reference edges for the whole document.

    Sections, creature stat blocks and equipment descriptions are all scanned,
    so a spell is linked from the monster that casts it, the item that casts
    it and the rule that mentions it alike.
    """
    spells = [n["heading"] for n in nodes if n.get("entity_type") == "spell"]
    magic_items = [n["heading"] for n in nodes if n.get("entity_type") == "magic_item"]
    scanner = ReferenceScanner(
        spells, magic_items, [c["name"] for c in creatures], glossary
    )

    edges: list[dict] = []

    for node in nodes:
        edges += _edges(scanner, node["content"], {
            "type": node.get("entity_type", "rule"),
            "id": node["id"],
            "name": node["heading"],
        }, (node.get("spell") or {}).get("conditions_imposed"))

    for creature in creatures:
        for part in CREATURE_PARTS:
            for entry in creature.get(part, []):
                edges += _edges(scanner, entry.get("description") or "", {
                    "type": "creature",
                    "name": creature["name"],
                    "part": f"{part}/{entry.get('name')}",
                }, entry.get("conditions_imposed"))

    for item in equipment:
        # Gear and poisons print their rules as a section of their own, which
        # the loop above has already scanned.  Scanning the description too
        # would emit every edge twice, once under each identity.
        if item.get("description") and not item.get("section_id"):
            edges += _edges(scanner, item["description"], {
                "type": item["kind"], "name": item["name"],
            })

    return edges
