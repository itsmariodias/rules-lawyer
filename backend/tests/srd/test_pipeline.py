from __future__ import annotations

import re

import pytest

from dnd_graph_rag.srd import pipeline


class TestStripMarkup:
    def test_given_emphasis_when_stripped_then_only_the_words_remain(self):
        # Given a heading carrying bold and italic markers
        # When it is stripped
        # Then the heading is the words it printed
        assert pipeline.strip_markup("**_Fireball_**") == "Fireball"


class TestCleanContent:
    def test_given_page_markers_when_cleaned_then_they_are_gone(self):
        # Given content interrupted by a page marker
        text = "First half.\n\n<!-- PAGE:12 -->\n\nSecond half."

        # When it is cleaned
        cleaned = pipeline.clean_content(text)

        # Then the marker is gone and the blank lines it left are collapsed
        assert cleaned == "First half.\n\nSecond half."


class TestBuildPageIndex:
    def test_given_markers_when_indexed_then_each_offset_names_its_page(self):
        # Given markdown carrying two page markers
        markdown = "intro\n<!-- PAGE:1 -->\nfirst\n<!-- PAGE:2 -->\nsecond"

        # When the index is built
        index = pipeline.build_page_index(markdown)

        # Then each entry is the marker's offset and the page it opens
        assert [page for _, page in index] == [1, 2]
        assert index[0][0] == markdown.index("<!-- PAGE:1 -->")


class TestPageAt:
    def test_given_an_offset_inside_a_page_when_asked_then_that_page_answers(self):
        # Given an index of two pages
        index = [(0, 1), (100, 2)]

        # When an offset inside the second is looked up
        # Then the page that contains it is returned
        assert pipeline.page_at(index, 150) == 2

    def test_given_an_offset_on_a_boundary_when_asked_then_the_page_it_opens_answers(self):
        # Given the same index
        index = [(0, 1), (100, 2)]

        # When the marker's own offset is looked up
        # Then it belongs to the page it opens
        assert pipeline.page_at(index, 100) == 2

    def test_given_an_offset_before_any_marker_when_asked_then_it_is_page_one(self):
        # Given an index whose first marker is not at the start
        index = [(50, 3)]

        # When an earlier offset is looked up
        # Then the front of the book answers rather than an error
        assert pipeline.page_at(index, 10) == 1


class TestFirstHeadingLevel:
    def test_given_a_body_when_asked_then_the_shallowest_level_answers(self):
        # Given a body opening on a level-three heading
        body = "### A\n\ntext\n\n#### B\n\ntext"

        # When the first level at or below two is looked for
        # Then the shallowest one present is found
        assert pipeline.first_heading_level(body, 2) == 3

    def test_given_only_deeper_headings_than_the_maximum_when_asked_then_none_answers(self):
        # Given a body whose only headings are stat block sections
        body = "###### Actions\n\ntext"

        # When the first heading level is looked for
        # Then nothing is found, so they stay part of their parent's prose
        assert pipeline.first_heading_level(body, 1) is None


class TestSplitOnLevel:
    def test_given_two_headings_when_split_then_each_carries_its_own_body(self):
        # Given two sections at the same level
        body = "## First\n\nOne.\n\n## Second\n\nTwo."

        # When the body is split on that level
        parts = pipeline.split_on_level(body, 2)

        # Then each heading takes only its own prose
        assert [heading for heading, _, _, _ in parts] == ["First", "Second"]
        assert parts[0][1].strip() == "One."

    def test_given_a_deeper_heading_when_split_then_it_stays_inside_its_parent(self):
        # Given a section with a child heading
        body = "## First\n\nOne.\n\n### Child\n\nDeeper."

        # When the body is split on the parent's level
        parts = pipeline.split_on_level(body, 2)

        # Then the child went with its parent rather than becoming a sibling
        assert len(parts) == 1
        assert "### Child" in parts[0][1]


class TestDirectContent:
    def test_given_a_child_heading_when_read_then_only_the_prose_above_it_is_taken(self):
        # Given a body whose prose is followed by a child section
        body = "\n\nIntro.\n\n### Child\n\nDeeper."

        # When the direct content is read
        # Then the child's prose is not the parent's
        assert pipeline.direct_content(body, 3) == "Intro."

    def test_given_no_children_when_read_then_the_whole_body_is_taken(self):
        # Given a leaf section
        # When the direct content is read
        # Then all of it belongs to that section
        assert pipeline.direct_content("\n\nAll of it.\n", None) == "All of it."


class TestBuildTree:
    @pytest.fixture
    def markdown(self) -> str:
        return ("<!-- PAGE:1 -->\n# Spells\n\nIntro.\n\n## Fireball\n\n"
                "It explodes.\n\n<!-- PAGE:2 -->\n## Cure Wounds\n\nIt heals.\n")

    def test_given_markdown_when_built_then_ids_are_dotted_and_positional(self, markdown):
        # Given markdown with one section and two subsections
        # When the tree is built
        tree = pipeline.build_tree(markdown,
                                   pipeline.build_page_index(markdown),
                                   "SRD.pdf")

        # Then the dotted id says where the node sits in the book
        assert tree[0]["id"] == "1"
        assert [n["id"] for n in tree[0]["subsections"]] == ["1.1", "1.2"]

    def test_given_a_parent_when_built_then_it_keeps_only_its_own_prose(self, markdown):
        # Given the same markdown
        # When the tree is built
        tree = pipeline.build_tree(markdown,
                                   pipeline.build_page_index(markdown),
                                   "SRD.pdf")

        # Then the parent's content stops where its first child begins
        assert tree[0]["content"] == "Intro."

    def test_given_a_node_when_built_then_its_offsets_slice_the_markdown_back(
            self, markdown):
        # Given the same markdown
        # When the tree is built
        tree = pipeline.build_tree(markdown,
                                   pipeline.build_page_index(markdown),
                                   "SRD.pdf")

        # Then slicing at a node's offsets returns that node's own passage
        source = tree[0]["subsections"][0]["source"]
        sliced = markdown[source["char_start"]:source["char_end"]]
        assert sliced.startswith("## Fireball")
        assert "It explodes." in sliced

    def test_given_a_node_after_a_page_marker_when_built_then_it_claims_that_page(
            self, markdown):
        # Given a subsection printed on the second page
        # When the tree is built
        tree = pipeline.build_tree(markdown,
                                   pipeline.build_page_index(markdown),
                                   "SRD.pdf")

        # Then the page range comes from the markers it sits between
        assert tree[0]["subsections"][1]["source"]["page_start"] == 2

    def test_given_no_headings_at_all_when_built_then_the_tree_is_empty(self):
        # Given markdown with no headings
        # When the tree is built
        # Then no node is invented for the prose
        assert pipeline.build_tree("Just prose.", [], "SRD.pdf") == []


class TestParseNamedEntries:
    def test_given_bold_italic_names_when_split_then_each_becomes_an_entry(self):
        # Given the form the book uses for a trait or an effect
        content = ("Preamble.\n\n**_Multiattack._** Twice.\n\n"
                   "**_Bite._** It bites.")

        # When the entries are parsed
        preamble, entries = pipeline.parse_named_entries(content)

        # Then the prose above the first name stays a preamble
        assert preamble == "Preamble."
        assert [e["name"] for e in entries] == ["Multiattack", "Bite"]

    def test_given_bold_names_only_when_split_then_they_are_used_instead(self):
        # Given the bold form, which spell fields use
        content = "**Casting Time.** Action\n\n**Range.** 150 feet"

        # When the entries are parsed
        _, entries = pipeline.parse_named_entries(content)

        # Then the fallback form was read
        assert [e["name"] for e in entries] == ["Casting Time", "Range"]

    def test_given_no_named_entries_when_split_then_it_is_all_preamble(self):
        # Given plain prose
        # When the entries are parsed
        preamble, entries = pipeline.parse_named_entries("Just prose.")

        # Then nothing was split out of it
        assert (preamble, entries) == ("Just prose.", [])


class TestParseSpellSubtitle:
    def test_given_a_levelled_spell_when_parsed_then_level_school_and_classes_are_read(self):
        # Given a spell subtitle as the book prints one
        # When it is parsed
        parsed = pipeline.parse_spell_subtitle("_Level 5 Abjuration (Druid, Cleric)_")

        # Then all three parts are split out
        assert parsed == {"level": 5, "school": "Abjuration",
                          "classes": ["Druid", "Cleric"]}

    def test_given_a_cantrip_when_parsed_then_its_level_is_zero(self):
        # Given a cantrip, whose subtitle names no level
        # When it is parsed
        parsed = pipeline.parse_spell_subtitle("_Evocation Cantrip (Wizard)_")

        # Then it is levelled zero, so levels stay comparable
        assert parsed["level"] == 0
        assert parsed["school"] == "Evocation"

    def test_given_no_class_list_when_parsed_then_the_list_is_empty(self):
        # Given a subtitle with no parenthesised classes
        # When it is parsed
        # Then no classes are invented
        assert pipeline.parse_spell_subtitle("_Level 1 Evocation_")["classes"] == []

    def test_given_a_line_that_is_not_a_subtitle_when_parsed_then_nothing_is_read(self):
        # Given ordinary prose
        # When it is parsed as a subtitle
        # Then nothing is claimed
        assert pipeline.parse_spell_subtitle("It explodes.") is None


class TestParseSpellFields:
    def test_given_all_four_fields_when_parsed_then_each_is_read(self):
        # Given a spell's field block
        content = ("**Casting Time:** Action\n**Range:** 150 feet\n"
                   "**Components:** V, S, M (a ball of bat guano)\n"
                   "**Duration:** Instantaneous")

        # When the fields are parsed
        fields = pipeline.parse_spell_fields(content)

        # Then each is available on its own
        assert fields["casting_time"] == "Action"
        assert fields["range"] == "150 feet"
        assert fields["duration"] == "Instantaneous"

    def test_given_a_ritual_when_parsed_then_it_is_lifted_out_of_the_casting_time(self):
        # Given a spell that can be cast as a ritual
        content = "**Casting Time:** Action or Ritual"

        # When the fields are parsed
        fields = pipeline.parse_spell_fields(content)

        # Then the marker became a property and the time is the time
        assert fields["ritual"] is True
        assert fields["casting_time"] == "Action"

    def test_given_concentration_when_parsed_then_it_is_lifted_out_of_the_duration(self):
        # Given a concentration spell
        content = "**Duration:** Concentration, up to 1 minute"

        # When the fields are parsed
        fields = pipeline.parse_spell_fields(content)

        # Then the flag is separate from the duration it qualified
        assert fields["concentration"] is True
        assert fields["duration"] == "up to 1 minute"

    def test_given_components_when_parsed_then_the_letters_become_flags(self):
        # Given a components line
        content = "**Components:** V, S, M (a bit of fleece)"

        # When the fields are parsed
        components = pipeline.parse_spell_fields(content)["components"]

        # Then each letter is its own property, with the material beside them
        assert components["verbal"] is True
        assert components["somatic"] is True
        assert components["material"] == "a bit of fleece"

    def test_given_a_priced_material_when_parsed_then_the_cost_is_read(self):
        # Given a material with a price
        content = "**Components:** V, S, M (a pearl worth 100+ GP)"

        # When the fields are parsed
        components = pipeline.parse_spell_fields(content)["components"]

        # Then the price is a number the graph can filter on
        assert components["material_cost_gp"] == 100

    def test_given_a_price_that_leads_the_noun_when_parsed_then_it_is_still_read(self):
        """Create Undead writes "one 150+ GP black onyx stone"."""
        # Given the material written the other way round
        content = "**Components:** V, S, M (one 150+ GP black onyx stone)"

        # When the fields are parsed
        components = pipeline.parse_spell_fields(content)["components"]

        # Then the unusual phrasing is read the same way
        assert components["material_cost_gp"] == 150

    def test_given_a_consumed_material_when_parsed_then_it_is_flagged(self):
        # Given a material the spell consumes
        content = "**Components:** V, S, M (a diamond, which the spell consumes)"

        # When the fields are parsed
        components = pipeline.parse_spell_fields(content)["components"]

        # Then the flag says so
        assert components["material_consumed"] is True

    def test_given_the_singular_label_when_parsed_then_it_is_accepted(self):
        """The book writes "Component:" as often as "Components:"."""
        # Given the singular spelling
        content = "**Component:** V"

        # When the fields are parsed
        # Then it is read as the same field
        assert pipeline.parse_spell_fields(content)["components"]["verbal"] is True


class TestParseItemSubtitle:
    def test_given_a_full_subtitle_when_parsed_then_every_part_is_read(self):
        # Given the most detailed form the book prints
        text = "_Weapon (Any Sword), Rare (Requires Attunement by a Druid)_"

        # When it is parsed
        parsed = pipeline.parse_item_subtitle(text)

        # Then the category, subtype, rarity and attunement are split out
        assert parsed["category"] == "Weapon"
        assert parsed["subtype"] == "Any Sword"
        assert parsed["rarity"] == "Rare"
        assert parsed["requires_attunement"] is True
        assert parsed["attunement_requirement"] == "a Druid"

    def test_given_attunement_with_no_requirement_when_parsed_then_only_the_flag_is_set(self):
        # Given an item that anyone may attune to
        # When it is parsed
        parsed = pipeline.parse_item_subtitle("_Wondrous Item, Uncommon "
                                              "(Requires Attunement)_")

        # Then no requirement is invented
        assert parsed["requires_attunement"] is True
        assert parsed["attunement_requirement"] is None

    def test_given_a_line_that_names_no_category_when_parsed_then_nothing_is_read(self):
        # Given a line that is not an item subtitle
        # When it is parsed
        # Then it is refused rather than half-read
        assert pipeline.parse_item_subtitle("It explodes.") is None


class TestLeadingSubtitle:
    def test_given_an_italic_opening_line_when_read_then_it_is_the_subtitle(self):
        # Given content opening on an italic line
        content = "_Level 3 Evocation (Wizard)_\n\n**Casting Time:** Action"

        # When the subtitle is read
        # Then the italic line is returned without its markers
        assert pipeline.leading_subtitle(content) == "Level 3 Evocation (Wizard)"

    def test_given_prose_first_when_read_then_there_is_no_subtitle(self):
        # Given content opening on ordinary prose
        # When the subtitle is read
        # Then nothing is claimed
        assert pipeline.leading_subtitle("It explodes.\n\n_Later italics_") is None


class TestWalk:
    def test_given_a_nested_tree_when_walked_then_every_node_is_visited_once(self):
        # Given a tree two levels deep
        tree = [{"heading": "A", "subsections": [
            {"heading": "A.1", "subsections": [
                {"heading": "A.1.1", "subsections": []}]}]},
            {"heading": "B", "subsections": []}]

        # When it is walked
        headings = [n["heading"] for n in pipeline.walk(tree)]

        # Then parents come before their children, in order
        assert headings == ["A", "A.1", "A.1.1", "B"]


class TestCountNodes:
    def test_given_a_nested_tree_when_counted_then_every_node_counts(self):
        # Given a tree of four nodes
        tree = [{"subsections": [{"subsections": [{"subsections": []}]}]},
                {"subsections": []}]

        # When they are counted
        # Then the count is of the whole tree, not of its roots
        assert pipeline.count_nodes(tree) == 4


class TestTypeEntrySets:
    def test_given_a_heading_that_nests_its_entries_when_typed_then_children_are_typed(self):
        # Given "Example Traps", which nests the traps it introduces
        tree = [{"heading": "Toolbox", "subsections": [
            {"heading": "Example Traps", "entity_type": "rule", "subsections": [
                {"heading": "Hidden Pit", "entity_type": "rule",
                 "subsections": []}]}]}]

        # When the entry sets are typed
        pipeline._type_entry_sets(tree)

        # Then the entries are typed and the introducing heading is not
        toolbox = tree[0]["subsections"]
        assert toolbox[0]["subsections"][0]["entity_type"] == "trap"
        assert toolbox[0]["entity_type"] == "rule"

    def test_given_a_heading_printed_beside_its_entries_when_typed_then_siblings_are_typed(self):
        """"Example Contagions" is printed at the same level as its entries."""
        # Given the sibling shape
        tree = [{"heading": "Toolbox", "subsections": [
            {"heading": "Example Contagions", "entity_type": "rule",
             "subsections": []},
            {"heading": "Cackle Fever", "entity_type": "rule",
             "subsections": []}]}]

        # When the entry sets are typed
        pipeline._type_entry_sets(tree)

        # Then the following siblings are the entries
        assert tree[0]["subsections"][1]["entity_type"] == "contagion"


def _node(heading: str, entity_type: str = "rule", creatures=(), content: str = "",
          subsections=()) -> dict:
    node = {"heading": heading, "entity_type": entity_type, "content": content,
            "subsections": list(subsections)}
    if creatures:
        node["creatures"] = list(creatures)
    return node


class TestMarkGroups:
    def test_given_a_spell_printing_a_stat_block_when_marked_then_it_stays_a_spell(self):
        """Regression: Find Steed and three other spells became creature groups."""
        # Given a spell whose summoned creature's stat block is its child
        tree = [_node("Spells", subsections=[
            _node("Spell Descriptions", subsections=[
                _node("Find Steed", "spell", subsections=[
                    _node("Otherworldly Steed",
                          creatures=["Otherworldly Steed"])])])])]

        # When groups are marked
        pipeline._mark_groups(tree)

        # Then the stat block is a creature, and nothing above it is a group
        spells = tree[0]
        descriptions = spells["subsections"][0]
        spell = descriptions["subsections"][0]
        assert spell["subsections"][0]["entity_type"] == "creature"
        assert spell["entity_type"] == "spell"
        assert descriptions["entity_type"] == "rule"
        assert spells["entity_type"] == "rule"
        assert "members" not in spell

    def test_given_a_monster_chapter_when_marked_then_its_sections_are_groups(self):
        # Given a monster heading holding two stat blocks
        tree = [_node("Monsters A–Z", subsections=[
            _node("Black Dragons", subsections=[
                _node("Adult Black Dragon", creatures=["Adult Black Dragon"]),
                _node("Young Black Dragon", creatures=["Young Black Dragon"])])])]

        # When groups are marked
        pipeline._mark_groups(tree)

        # Then the heading is a group of both, and each stat block a creature
        dragons = tree[0]["subsections"][0]
        assert dragons["entity_type"] == "creature_group"
        assert dragons["members"] == ["Adult Black Dragon", "Young Black Dragon"]
        assert [c["entity_type"] for c in dragons["subsections"]] == [
            "creature", "creature"]

    def test_given_a_monster_chapter_when_marked_then_the_chapter_is_no_group(self):
        """Regression: "Monsters A–Z" and "Animals" were creature groups."""
        # Given a monster chapter holding a monster entry
        tree = [_node("Animals", subsections=[
            _node("Ape", creatures=["Ape"])])]

        # When groups are marked
        pipeline._mark_groups(tree)

        # Then the chapter holding the entries is not itself a group
        assert tree[0]["entity_type"] == "rule"
        assert "members" not in tree[0]


class TestAnnotateSubtree:
    def test_given_a_table_inside_a_spell_when_typed_then_it_is_not_a_spell(self):
        """Regression: Teleportation Outcome and seven other tables were spells."""
        # Given a spell with a table printed as its own subsection
        spell = _node("Teleport", content="_Level 7 Conjuration (Wizard)_\n\nText.",
                      subsections=[_node("Teleportation Outcome",
                                         content="| Roll | Result |")])

        # When the subtree is typed
        pipeline._annotate_subtree(spell, "rule")

        # Then the spell is a spell and its table keeps the default
        assert spell["entity_type"] == "spell"
        assert spell["subsections"][0]["entity_type"] == "rule"


class TestAnnotate:
    def test_given_a_chapter_of_entities_when_typed_then_position_types_nothing(self):
        """Regression: every heading and table under "Classes" was a class_feature."""
        # Given the Classes chapter, with a class, a feature and a spell list
        tree = [_node("Classes", subsections=[
            _node("Bard", subsections=[
                _node("Level 1: Bardic Inspiration"),
                _node("Bard Spell List")])])]
        for node in pipeline.walk(tree):
            node.update(id="6", source={"char_start": 0, "char_end": 0})

        # When the tree is annotated
        pipeline.annotate(tree, [])

        # Then everything is a rule until a record says otherwise
        assert {n["entity_type"] for n in pipeline.walk(tree)} == {"rule"}


class TestTypeFromRecords:
    @staticmethod
    def nodes() -> list[dict]:
        return [dict(_node(heading), id=node_id) for node_id, heading in [
            ("6.1", "Barbarian"), ("6.1.1", "Becoming a Barbarian …"),
            ("6.1.2.1", "Level 1: Rage"), ("6.1.3", "Path of the Berserker"),
            ("6.1.3.1", "Level 3: Frenzy"), ("7.1", "Acolyte"),
            ("8.1", "Alert"), ("9.5.1", "Acid (25 GP)"), ("12.6.3.1", "Torpor"),
            ("10.3.1", "Acid Splash")]]

    def test_given_extracted_records_when_typed_then_their_sections_take_their_kind(self):
        # Given sections and the records extracted from them
        nodes = self.nodes()
        nodes[-1]["entity_type"] = "spell"
        classes = [{"section_id": "6.1",
                    "features": [{"section_id": "6.1.2.1"}],
                    "subclasses": [{"section_id": "6.1.3",
                                    "features": [{"section_id": "6.1.3.1"}]}]}]
        origins = [{"section_id": "7.1"}]
        feats = [{"section_id": "8.1"}]
        equipment = [{"section_id": "9.5.1"}, {"section_id": "12.6.3.1"},
                     {"name": "Longsword"}, {"section_id": "10.3.1"}]

        # When sections are typed from the records
        pipeline.type_from_records(nodes, classes, origins, feats, equipment)

        # Then each named section is its record's kind, the rest stay rules,
        # and a type the book already printed is kept
        assert {n["heading"]: n["entity_type"] for n in nodes} == {
            "Barbarian": "class", "Becoming a Barbarian …": "rule",
            "Level 1: Rage": "class_feature", "Path of the Berserker": "subclass",
            "Level 3: Frenzy": "class_feature", "Acolyte": "origin",
            "Alert": "feat", "Acid (25 GP)": "equipment", "Torpor": "equipment",
            "Acid Splash": "spell"}


class TestPageRange:
    def test_given_a_range_holding_an_earlier_page_when_asked_then_it_is_included(self):
        """A float placed back in its section can bring its page with it."""
        # Given markers for pages 5, 4 (a moved table) and 5 again
        page_index = [(0, 5), (100, 4), (200, 5)]

        # When the range spanning all three is asked for
        # Then it starts on the moved table's page
        assert pipeline.page_range(page_index, 50, 250) == (4, 5)

    def test_given_a_range_inside_one_page_when_asked_then_it_is_that_page(self):
        # Given two pages
        page_index = [(0, 1), (100, 2)]

        # When a range inside the first is asked for
        # Then only that page is claimed
        assert pipeline.page_range(page_index, 10, 90) == (1, 1)


class TestParseStatBlockIndex:
    def test_given_the_index_when_parsed_then_each_entry_names_a_page(self):
        # Given the index section and the page the monsters begin on
        tree = [
            {"heading": "Index of Stat Blocks",
             "content": "Aboleth.......350\nGoblin.......362",
             "source": {"page_start": 12, "page_end": 12}, "subsections": []},
            {"heading": "Monsters", "source": {"page_start": 300,
                                               "page_end": 364},
             "content": "", "subsections": []},
        ]

        # When the index is parsed
        index = pipeline.parse_stat_block_index(tree)

        # Then each creature is paired with the page it is printed on
        assert index == {"Aboleth": 350, "Goblin": 362}

    def test_given_contents_lines_bleeding_in_when_parsed_then_they_are_dropped(self):
        """The index shares its first page with the table of contents."""
        # Given an index polluted by contents entries pointing at the front
        tree = [
            {"heading": "Index of Stat Blocks",
             "content": "Playing the Game.......12\nAboleth.......350",
             "source": {"page_start": 12, "page_end": 12}, "subsections": []},
            {"heading": "Monsters", "source": {"page_start": 300,
                                               "page_end": 364},
             "content": "", "subsections": []},
        ]

        # When the index is parsed
        index = pipeline.parse_stat_block_index(tree)

        # Then only entries in the monster pages survive
        assert index == {"Aboleth": 350}

    def test_given_no_index_section_when_parsed_then_nothing_comes_back(self):
        # Given a tree with no index
        # When it is parsed
        # Then the answer is empty rather than an error
        assert pipeline.parse_stat_block_index([]) == {}


class TestSectionBoxes:
    @pytest.fixture
    def anchors(self) -> list[dict]:
        """Three anchors in document order."""
        return [
            {"start": 0, "end": 100, "boxes": [{"page": 1, "y0": 10}]},
            {"start": 100, "end": 200, "boxes": [{"page": 1, "y0": 30}]},
            {"start": 200, "end": 300, "boxes": [{"page": 2, "y0": 10}]},
        ]

    def test_given_a_range_inside_one_part_when_asked_then_only_its_boxes_come_back(
            self, anchors):
        # Given a range wholly inside the second part
        # When the boxes are collected
        boxes = pipeline.section_boxes(anchors, 120, 180)

        # Then only that part's geometry is returned
        assert boxes == [{"page": 1, "y0": 30}]

    def test_given_a_range_spanning_two_parts_when_asked_then_both_are_included(
            self, anchors):
        # Given a range crossing a part boundary
        # When the boxes are collected
        boxes = pipeline.section_boxes(anchors, 50, 150)

        # Then the run of overlapping parts is contiguous and complete
        assert boxes == [{"page": 1, "y0": 10}, {"page": 1, "y0": 30}]

    def test_given_a_range_crossing_a_page_when_asked_then_both_pages_appear(
            self, anchors):
        # Given a range reaching into the next page
        # When the boxes are collected
        boxes = pipeline.section_boxes(anchors, 150, 250)

        # Then the geometry names both pages
        assert {box["page"] for box in boxes} == {1, 2}

    def test_given_a_range_past_the_end_when_asked_then_nothing_comes_back(
            self, anchors):
        # Given a range beyond every anchor
        # When the boxes are collected
        # Then no geometry is invented for it
        assert pipeline.section_boxes(anchors, 500, 600) == []

    def test_given_no_anchors_at_all_when_asked_then_it_is_not_an_error(self):
        # Given an empty anchor list
        # When the boxes are collected
        # Then the citation still resolves, just without geometry
        assert pipeline.section_boxes([], 0, 100) == []


class TestCheckAnchors:
    def test_given_agreeing_geometry_when_checked_then_nothing_is_reported(self):
        # Given a section whose boxes sit on the page it claims
        tree = [{"id": "1", "heading": "A", "subsections": [],
                 "source": {"char_start": 0, "char_end": 100,
                            "page_start": 1, "page_end": 1}}]
        anchors = [{"start": 0, "end": 100, "boxes": [{"page": 1}]}]

        # When the anchors are checked
        report = pipeline.check_anchors(tree, anchors)

        # Then there is nothing to report
        assert report["sections_without_geometry"] == []
        assert report["sections_with_misplaced_geometry"] == []

    def test_given_a_section_with_no_geometry_when_checked_then_it_is_named(self):
        # Given a section no line accounts for
        tree = [{"id": "1", "heading": "A", "subsections": [],
                 "source": {"char_start": 500, "char_end": 600,
                            "page_start": 1, "page_end": 1}}]

        # When the anchors are checked
        report = pipeline.check_anchors(tree, [])

        # Then the section is reported by id
        assert report["sections_without_geometry"] == ["1"]

    def test_given_geometry_on_the_wrong_page_when_checked_then_it_is_reported(self):
        # Given boxes on a page the section does not claim
        tree = [{"id": "1", "heading": "A", "subsections": [],
                 "source": {"char_start": 0, "char_end": 100,
                            "page_start": 1, "page_end": 1}}]
        anchors = [{"start": 0, "end": 100, "boxes": [{"page": 7}]}]

        # When the anchors are checked
        report = pipeline.check_anchors(tree, anchors)

        # Then the disagreement is reported with both sides of it
        misplaced, = report["sections_with_misplaced_geometry"]
        assert misplaced["pages"] == [7]
        assert misplaced["claimed"] == [1, 1]


class TestLoad:
    def test_given_no_artifact_when_loaded_then_the_failure_names_the_path(
            self, tmp_path):
        # Given a path nothing has been written to
        missing = tmp_path / "srd_hierarchy.json"

        # When it is loaded
        # Then the error says what is missing rather than failing obscurely
        with pytest.raises(FileNotFoundError, match="srd_hierarchy.json"):
            pipeline.load(missing)


class TestTheRealArtifact:
    def test_given_the_artifact_when_read_then_its_counts_match_its_collections(
            self, document):
        # Given the artifact on disk
        counts = document["meta"]["counts"]

        # When the counts are compared with the collections beside them
        # Then the metadata describes what is actually there
        assert counts["sections"] == pipeline.count_nodes(document["sections"])
        assert counts["creatures"] == len(document["creatures"])
        assert counts["equipment"] == len(document["equipment"])
        assert counts["glossary"] == len(document["glossary"])

    def test_given_the_artifact_when_read_then_spells_and_items_are_what_their_subtitles_say(
            self, document):
        # Given every section in the tree
        nodes = list(pipeline.walk(document["sections"]))

        # When types are compared with the subtitles the book prints
        # Then a section is a spell or magic item exactly when it has one
        for node in nodes:
            assert (node["entity_type"] == "spell") == bool(node.get("spell")), node["id"]
            assert (node["entity_type"] == "magic_item") == bool(node.get("item")), node["id"]

    def test_given_the_artifact_when_read_then_every_section_is_typed(self, document):
        # Given every node in the tree
        # When their entity types are read
        typed = [n for n in pipeline.walk(document["sections"])
                 if n.get("entity_type")]

        # Then not one of them was left untyped
        assert len(typed) == counts_of(document)

    def test_given_the_artifact_when_read_then_every_offset_slices_real_text(
            self, document, markdown):
        # Given the markdown the offsets were measured against
        # When each section's own heading is sliced out at its offsets
        for node in pipeline.walk(document["sections"]):
            source = node["source"]
            sliced = markdown[source["char_start"]:source["char_end"]]

            # Then the slice opens on that section's heading
            assert pipeline.strip_markup(sliced.split("\n")[0].lstrip("# ")) \
                == node["heading"]

    def test_given_the_artifact_when_validated_then_the_book_agreed_with_itself(
            self, document):
        # Given the validation report the run wrote
        validation = document["validation"]

        # When its independent cross-checks are read
        # Then the book's own index reconciled against what was extracted
        assert validation["missing_from_extraction"] == []
        assert validation["page_mismatches"] == []
        assert validation["duplicate_names"] == []
        # And every average equals the average of its own dice, and every
        # attack bonus an ability modifier plus the proficiency bonus
        assert validation["damage_average_mismatches"] == []
        assert validation["attack_bonus_mismatches"] == []
        # And every section's geometry falls on the pages it claims
        assert validation["sections_without_geometry"] == []
        assert validation["sections_with_misplaced_geometry"] == []

    def test_given_the_artifact_when_read_then_the_four_poison_types_are_there(
            self, document):
        # Given the glossary's poison types
        types = {t["name"]: t for t in document["glossary"]
                 if t["term_type"] == "poison type"}

        # When they are compared with the poisons that name them
        poisons = [e for e in document["equipment"] if e["kind"] == "poison"]

        # Then all four are defined, and every poison resolves to one
        assert set(types) == {"Contact", "Ingested", "Inhaled", "Injury"}
        assert all(t["description"] and t["section_id"] == "12.6"
                   for t in types.values())
        assert poisons and all(p["poison_type"] in types for p in poisons)

    def test_given_the_artifact_when_read_then_the_toolbox_entry_sets_are_typed(
            self, document):
        # Given the counts the run recorded
        counts = document["meta"]["counts"]["entity_types"]

        # When the tree is grouped by entity type
        by_type = {}
        for node in pipeline.walk(document["sections"]):
            by_type.setdefault(node["entity_type"], []).append(node["heading"])

        # Then each closed set is typed, and its introducing heading is not
        assert counts["environmental_effect"] == 9
        assert counts["trap"] == 8
        assert counts["contagion"] == 3
        assert by_type["contagion"] == ["Cackle Fever", "Sewer Plague",
                                        "Sight Rot"]
        assert "Extreme Cold" in by_type["environmental_effect"]
        assert "Hidden Pit" in by_type["trap"]
        assert "Example Contagions" not in by_type["contagion"]
        assert "Environmental Effects" not in by_type["environmental_effect"]


    def test_given_the_artifact_when_read_then_no_heading_is_left_inside_prose(
            self, document):
        """Regression: 26 captions such as "Core Bard Traits" were literal text."""
        # Given every section
        # When its prose is searched for heading markup
        stranded = [n["id"] for n in pipeline.walk(document["sections"])
                    if re.search(r"(?m)^#{1,5} ", n["content"])]

        # Then every heading became a section
        assert stranded == []

    def test_given_the_artifact_when_read_then_a_feature_keeps_the_rules_after_its_table(
            self, document):
        """Regression: Rage's rules were the content of "Barbarian Features"."""
        # Given the sections by heading
        nodes = {n["heading"]: n for n in pipeline.walk(document["sections"])}

        # When the feature and the table printed inside it are read
        rage = nodes["Level 1: Rage"]
        table = nodes["Barbarian Features"]

        # Then the feature has its own rules, the table only rows, and the
        # table sits under the section that introduces it
        assert "Rage lasts until the end of your next turn" in rage["content"]
        assert table["content"].lstrip().startswith("|")
        assert "Rage lasts" not in table["content"]
        assert any(c["heading"] == "Barbarian Features"
                   for c in nodes["Barbarian Class Features"]["subsections"])

    def test_given_the_artifact_when_read_then_tables_sit_with_the_text_naming_them(
            self, document):
        """Regression: the Weapons table was under Vex, Travel Terrain under
        Creating a Background."""
        # Given each section's parent
        parent = {c["id"]: n for n in pipeline.walk(document["sections"])
                  for c in n["subsections"]}
        nodes = list(pipeline.walk(document["sections"]))

        # When the tables named by a section are located
        placed = {(n["heading"], parent[n["id"]]["heading"]) for n in nodes
                  if n["id"] in parent and n["content"].lstrip().startswith("|")}

        # Then each is a child of the section that refers to it
        assert {("Weapons", "Weapons"), ("Armor", "Armor"),
                ("Adventuring Gear", "Adventuring Gear"),
                ("Travel Terrain", "Travel Pace"),
                ("Apparatus of the Crab Levers", "Apparatus of the Crab"),
                ("Starting Equipment at Higher Levels", "Starting Equipment"),
                } <= placed

    def test_given_the_artifact_when_read_then_records_and_types_agree_both_ways(
            self, document):
        """A type comes from evidence, not the chapter it is printed in."""
        # Given the sections the extracted records name
        named = {"class": {c["section_id"] for c in document["classes"]},
                 "subclass": {s["section_id"] for c in document["classes"]
                              for s in c["subclasses"]},
                 "origin": {r["section_id"] for r in
                            document["species"] + document["backgrounds"]},
                 "feat": {f["section_id"] for f in document["feats"]},
                 "equipment": {e["section_id"] for e in document["equipment"]
                               if e.get("section_id")}}
        features = {f["section_id"] for c in document["classes"]
                    for f in c["features"] + [f for s in c["subclasses"]
                                              for f in s.get("features", [])]}

        # When the tree is grouped by type
        by_type: dict[str, set[str]] = {}
        for node in pipeline.walk(document["sections"]):
            by_type.setdefault(node["entity_type"], set()).add(node["id"])

        # Then a section has a record's type exactly when a record names it,
        # and the only class features beyond the recorded ones are options
        for kind, ids in named.items():
            assert by_type[kind] == ids, kind
        assert features <= by_type["class_feature"]
        assert len(by_type["class_feature"] - features) == 38  # 10 Metamagic, 28 Invocations

    def test_given_the_artifact_when_read_then_no_chapter_is_typed_as_an_entity(
            self, document):
        """Regression: "Monsters A–Z" and "Animals" were creature groups."""
        # Given the top-level sections
        # When their types are read
        types = {n["heading"]: n["entity_type"] for n in document["sections"]}

        # Then each is front matter or rules
        assert set(types.values()) == {"front_matter", "rule"}

    def test_given_the_artifact_when_read_then_proficiency_bonuses_follow_the_rule(
            self, document):
        """The bonus is +2 at level 1 and rises by one every four levels."""
        # Given every class's progression
        for klass in document["classes"]:
            # When each level's bonus is read
            # Then it is the one the rules give that level
            assert [(r["level"], r.get("proficiency_bonus"))
                    for r in klass["progression"]] == [
                (level, 2 + (level - 1) // 4) for level in range(1, 21)
            ], klass["name"]


def counts_of(document: dict) -> int:
    return document["meta"]["counts"]["sections"]
