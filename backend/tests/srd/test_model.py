from __future__ import annotations

from dnd_graph_rag.srd.model import add_page


class TestAddPage:
    def test_given_pages_when_a_page_is_added_then_they_stay_ascending_and_unique(self):
        # Given a block on pages 5 and 7
        pages = [5, 7]

        # When it is found on 6, then on 7 again
        add_page(pages, 6)
        add_page(pages, 7)

        # Then each page is listed once, in order
        assert pages == [5, 6, 7]
