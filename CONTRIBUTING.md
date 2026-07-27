# Contributing

Contributions are welcome, especially integrations, evidence gates, failure fixtures,
and checks that make the automation ledger harder to fool.

## Ground rules

1. Label evidence precisely: `synthetic`, `dry-run`, `supervised hardware`, or
   `independently reproduced hardware`.
2. Do not promote an instrument, protocol, or vision benchmark beyond the strongest
   evidence checked into the repository.
3. Keep proposal separate from permission. A model output cannot bypass deterministic
   safety, assay-QC, or physical-state gates.
4. Keep actuation out of this package. Instrument movement belongs behind the arming and
   confirmation boundaries in the relevant controller repository.
5. Add a failing test for any corrected overclaim, stale run-card path, unsafe skip, or
   provenance inconsistency.

## Development

```bash
python -m venv .venv
.venv/bin/pip install -e '.[dev]'
.venv/bin/pytest -q
.venv/bin/ruff check autonomous_lab tests
```

Tracked Python, Markdown, TOML, and YAML text must remain ASCII-only because CI enforces
portable run cards and logs.

## Hardware evidence

A hardware-validation contribution should include:

- exact instrument and connection path
- code or run card used
- success and failure counts
- operator confirmation boundary
- raw log, image, or run-folder reference where it can be shared safely
- what was not tested
- the smallest claim the evidence supports

When evidence cannot be published, keep the claim narrow and describe what the repository
can check versus what still depends on operator testimony.
