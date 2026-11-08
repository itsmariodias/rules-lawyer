"""
Shared fixtures.  Tests needing the artifact, vectors, an API key or Neo4j skip
without them.
"""

from __future__ import annotations

import json

import pytest

from dnd_graph_rag.config import (anchors_path_for, get_settings,
                                  markdown_path_for)


@pytest.fixture(scope="session")
def document() -> dict:
    """The real artifact; skips if it has not been generated."""
    from dnd_graph_rag.srd import load

    settings = get_settings()
    if not settings.output_path.exists():
        pytest.skip(f"no artifact at {settings.output_path}; run srd-parse")
    return load(settings.output_path)


@pytest.fixture(scope="session")
def graph_session():
    """A Neo4j session; skips if the database is not up."""
    from dnd_graph_rag.graph.loader import session

    try:
        with session() as open_session:
            open_session.run("RETURN 1").consume()
            yield open_session
    except Exception as exc:  # any of the driver's connection failures
        pytest.skip(f"Neo4j unavailable: {exc}")


@pytest.fixture
def tiny_document() -> dict:
    """
    A hand-built document covering the mapper's awkward cases: a stat block
    folding into its section, an ability referenced by ``part``, a damage list,
    a two-part weapon range, a resources map, and a magic item name printed
    twice.
    """
    return {
        "meta": {"counts": {}},
        "sections": [
            {
                "id": "1", "heading": "Monsters", "content": "",
                "entity_type": "creature_group",
                "source": {"page_start": 1, "page_end": 2,
                           "char_start": 0, "char_end": 99},
                "subsections": [
                    {"id": "1.1", "heading": "Goblin", "content": "A goblin.",
                     "entity_type": "creature",
                     "source": {"page_start": 1, "page_end": 1,
                                "char_start": 10, "char_end": 50},
                     "subsections": []},
                ],
            },
            {
                "id": "2", "heading": "Fireball", "content": "It explodes.",
                "entity_type": "spell",
                "source": {"page_start": 3, "page_end": 3,
                           "char_start": 100, "char_end": 200},
                "spell": {
                    "level": 3, "school": "Evocation", "classes": ["Wizard"],
                    "ritual": False, "concentration": False,
                    "casting_time": "Action", "range": "150 feet",
                    "duration": "Instantaneous",
                    "components": {"verbal": True, "somatic": True,
                                   "material": "bat guano",
                                   "material_cost_gp": None,
                                   "material_consumed": False},
                    "damage": [{"average": 28, "dice": "8d6", "type": "Fire"}],
                    "saving_throw": "Dexterity",
                },
                "subsections": [],
            },
            {"id": "5", "heading": "Serpent Venom (200 GP)",
             "content": "_Injury Poison_\n\nA creature subjected to…",
             "entity_type": "rule",
             "source": {"page_start": 197, "page_end": 197,
                        "char_start": 500, "char_end": 560},
             "subsections": []},
            {"id": "3", "heading": "Deck of Illusions", "content": "A table.",
             "entity_type": "magic_item",
             "source": {"page_start": 4, "page_end": 4,
                        "char_start": 300, "char_end": 310},
             "subsections": []},
            {"id": "4", "heading": "Deck of Illusions", "content": "The item.",
             "entity_type": "magic_item",
             "source": {"page_start": 4, "page_end": 4,
                        "char_start": 320, "char_end": 400},
             "item": {"category": "Wondrous Item", "subtype": None,
                      "rarity": "Uncommon", "requires_attunement": False,
                      "attunement_requirement": None},
             "subsections": []},
        ],
        "creatures": [
            {
                "name": "Goblin", "entity_type": "creature",
                "type": "Small Fey", "alignment": "Chaotic Evil",
                "ac": 15, "cr": "1/4", "xp": 50,
                "hp": {"average": 10, "formula": "3d6", "calculated": 10,
                       "valid": True},
                "speed": {"walk": 30, "climb": 20},
                "abilities": {ability: {"score": 10, "modifier": 0, "save": 0}
                              for ability in ("str", "dex", "con",
                                              "int", "wis", "cha")},
                "immunities": ["Fire"],
                "condition_immunities": ["Charmed"],
                "gear": ["Dagger"],
                "warnings": [],
                "actions": [
                    {"name": "Bite", "description": "It bites.",
                     "attack": {"kind": "melee", "bonus": 4, "reach_ft": 5},
                     "damage": [{"average": 5, "dice": "1d6+2",
                                 "type": "Piercing"}],
                     "outcomes": {"hit": {"text": "5 Piercing damage"}}},
                    {"name": "Sling", "description": "It slings.",
                     "attack": {"kind": "ranged", "bonus": 4,
                                "range_ft": {"normal": 30, "long": 120}}},
                ],
            },
        ],
        "equipment": [
            {"name": "Serpent Venom", "kind": "poison", "category": "Poison",
             "poison_type": "Injury", "cost": "200 GP", "cost_gp": 200.0,
             "section_id": "5",
             "description": "_Injury Poison_\n\nA creature subjected to…",
             "source": {"page_start": 197, "page_end": 197}},
            {"name": "Dagger", "kind": "weapon", "category": "Simple Melee",
             "damage": {"dice": "1d4", "type": "Piercing"},
             "properties": ["Finesse", "Light"], "cost": "2 GP",
             "cost_gp": 2.0, "weight_lb": 1.0,
             "source": {"page_start": 91, "page_end": 91}},
        ],
        "classes": [
            {"name": "Wizard", "section_id": "1",
             "hit_point_die": "D6 per Wizard level",
             "source": {"page_start": 70, "page_end": 70},
             "progression": [{"level": 1, "proficiency_bonus": 2,
                              "features": ["Spellcasting"],
                              "resources": {"Cantrips": "3",
                                            "Prepared Spells": "4"}}],
             "features": [{"level": 1, "name": "Spellcasting",
                           "subclass": None, "description": "You cast.",
                           "section_id": "1.1"}],
             "subclasses": []},
        ],
        "species": [], "backgrounds": [], "feats": [],
        "glossary": [
            {"name": "Fire", "term_type": "damage type",
             "description": "Burns.", "section_id": "9",
             "source": {"page_start": 176, "page_end": 176}},
            {"name": "Charmed", "term_type": "condition",
             "description": "Charmed.", "section_id": "9",
             "source": {"page_start": 176, "page_end": 176}},
            {"name": "Injury", "term_type": "poison type",
             "description": "Injury poison can be applied as a Bonus Action…",
             "section_id": "9",
             "source": {"page_start": 197, "page_end": 197}},
        ],
        "references": [
            {"source": {"type": "creature", "name": "Goblin",
                        "part": "actions/Bite"},
             "target": {"type": "condition", "name": "Charmed"},
             "relation": "imposes_condition"},
            {"source": {"type": "spell", "id": "2", "name": "Fireball"},
             "target": {"type": "damage_type", "name": "Fire"},
             "relation": "references_damage_type"},
            {"source": {"type": "rule", "id": "1", "name": "Monsters"},
             "target": {"type": "condition", "name": "Nonexistent"},
             "relation": "references_condition"},
        ],
        "validation": {},
    }


@pytest.fixture(scope="session")
def anchors() -> list[dict]:
    """The anchors file; skips if it has not been generated."""
    path = anchors_path_for(markdown_path_for(get_settings().output_path))
    if not path.exists():
        pytest.skip(f"no anchors at {path}; re-run srd-parse")
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture(scope="session")
def markdown() -> str:
    """The stage 1 markdown; skips if it has not been generated."""
    path = markdown_path_for(get_settings().output_path)
    if not path.exists():
        pytest.skip(f"no markdown at {path}; run srd-parse")
    return path.read_text(encoding="utf-8")


@pytest.fixture(scope="session")
def vectors():
    """The embeddings file; skips if it is absent."""
    from dnd_graph_rag.graph import embeddings

    path = get_settings().embeddings_path
    if not path.exists():
        pytest.skip(f"no embeddings at {path}; run srd-embed")
    return embeddings.read(path)


@pytest.fixture
def embedding_key():
    """Skips without a live API key, which embedding a query needs."""
    if get_settings().embedding.google_api_key is None:
        pytest.skip("no GOOGLE_API_KEY; a query cannot be embedded")


@pytest.fixture(scope="module")
def graph(graph_session):
    """A session on a loaded graph; skips if Neo4j is down or empty."""
    if graph_session.run("MATCH (n:Section) RETURN count(n)").single()[0] == 0:
        pytest.skip("graph is empty; run srd-graph-load")
    return graph_session


@pytest.fixture
def settings_env(monkeypatch):
    """
    Set environment variables for one test, clearing the ``get_settings`` cache
    either side.
    """
    def apply(**environment: str):
        for name, value in environment.items():
            monkeypatch.setenv(name, value)
        get_settings.cache_clear()
        return get_settings()

    yield apply
    get_settings.cache_clear()


@pytest.fixture
def stub_model(settings_env):
    """
    Use the scripted model for one test.  Clears the ``build_agent`` cache
    either side, since it would otherwise hand back an agent built with the
    other model.
    """
    from dnd_graph_rag.chat.agent import build_agent

    build_agent.cache_clear()
    yield settings_env(CHAT_STUB="1")
    build_agent.cache_clear()


@pytest.fixture
def saver():
    """An in-memory checkpointer."""
    from langgraph.checkpoint.memory import InMemorySaver

    return InMemorySaver()


@pytest.fixture
def store():
    """An in-memory pin and title store."""
    from langgraph.store.memory import InMemoryStore

    return InMemoryStore()
