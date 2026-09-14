# Notice

The software in this repository is licensed under the MIT License; see
[LICENSE.md](LICENSE.md). The game content is not, and this file says what it
is and what carrying it requires.

## The SRD, and what derives from it

`data/source/SRD_CC_v5.2.1.pdf` is published by Wizards of the Coast under the
Creative Commons Attribution 4.0 International License. Everything the
pipeline derives from it carries that same licence and the same attribution
requirement, which includes:

* `data/output/srd_hierarchy.json`, `.md` and `.anchors.json`
* `data/output/srd_embeddings.idx`
* the Neo4j graph a load writes, and any export of it
* the passages an answer quotes or cites

None of those files are committed here apart from the PDF itself, but they are
reproducible from it, and redistributing any of them carries this notice with
them.

## Required attribution

The SRD's own Legal Information section requires this statement, verbatim, in
any work that includes its material:

> This work includes material from the System Reference Document 5.2.1
> (“SRD 5.2.1”) by Wizards of the Coast LLC, available at
> https://www.dndbeyond.com/srd. The SRD 5.2.1 is licensed under the Creative
> Commons Attribution 4.0 International License, available at
> https://creativecommons.org/licenses/by/4.0/legalcode.

The same section asks that no other attribution to Wizards of the Coast or its
affiliates be included beyond the statement above. A work may state that it is
"compatible with fifth edition" or "5E compatible".

Section 5 of CC BY 4.0 carries a disclaimer of warranties and a limitation of
liability.

## In short

| | |
| --- | --- |
| The code | MIT, Mario Dias |
| The SRD PDF, and anything generated from it | CC BY 4.0, Wizards of the Coast LLC |
