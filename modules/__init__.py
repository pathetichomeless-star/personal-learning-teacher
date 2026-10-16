"""Product modules (pure logic): intent routing, memory, adapters, knowledge.

Boundary rules (docs/architecture/data-ownership.md):
* `modules/intent` decides; the gateway executes.
* `modules/memory` owns preferences only — never course progress.
* `modules/adapters` translate external systems (read-only in the MVP).
None of these modules import the gateway or the audio plane.
"""