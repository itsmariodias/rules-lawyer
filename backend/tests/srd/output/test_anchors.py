from __future__ import annotations

from rules_lawyer.srd.model import Box, Paragraph, Run, Section, Source
from rules_lawyer.srd.output.anchors import anchors, misplaced

RAGE = Box(28, 313.5, 223.1, 382.7, 235.6)


class TestAnchors:
    def test_given_parts_when_anchored_then_each_with_boxes_keeps_its_span(self):
        # Given a heading with its line's box, and a float's heading, which has none
        heading = Section("6.1.3.1", "Level 1: Rage", 4, [], [], Source(28, 28), boxes=[RAGE])
        float_heading = Section("6.1.3.2", "Barbarian Features", 4, [], [], Source(28, 28))

        # When anchored
        found = anchors([(100, 120, heading), (122, 145, float_heading)])

        # Then only the part with boxes is an anchor, its boxes as plain data
        assert found == [{"start": 100, "end": 120,
                          "boxes": [{"page": 28, "x0": 313.5, "y0": 223.1, "x1": 382.7, "y1": 235.6}]}]


class TestMisplaced:
    def test_given_boxes_within_and_outside_a_sections_pages_when_checked_then_only_outside_is_reported(self):
        # Given two sections on page 28: one boxed there, one boxed on page 30
        rage = Section("1", "Level 1: Rage", 4, [Paragraph([Run("Rage.")], [28])], [], Source(28, 28, 0, 20))
        other = Section("2", "Level 2: Danger Sense", 4, [], [], Source(28, 28, 22, 40))
        found = anchors([(0, 20, Section("x", "", 1, [], [], Source(28, 28), boxes=[RAGE])),
                         (22, 40, Section("y", "", 1, [], [], Source(30, 30), boxes=[Box(30, 1, 2, 3, 4)]))])

        # When checked
        # Then the second is reported with the page its boxes are on
        assert misplaced([rage, other], found) == [
            "Anchors: 2 Level 2: Danger Sense has boxes on pages [30], outside 28-28"]

    def test_given_a_section_with_no_boxes_when_checked_then_it_is_reported(self):
        # Given a section whose span has no anchor
        section = Section("1", "Legal Information", 1, [], [], Source(1, 1, 0, 20))

        # When checked
        # Then it is reported
        assert misplaced([section], []) == ["Anchors: 1 Legal Information has no boxes"]
