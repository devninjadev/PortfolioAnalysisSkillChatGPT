# evidence-first-portfolio-advisor 0.9.4

Install the skill ZIP from the GitHub release. Read SKILL.md for the complete workflow.

This version adds Alpaca Paper Trading as a read-only fallback after the original Alpaca connector, before existing later alternatives. App installation/authentication is separate from skill installation. Trading, order cancellation, account edits and paper-P/L substitution are outside this fallback.

See references/alpaca-connector-fallback.md for capability checks and actual connector provenance. The portfolio adapter supports only complete single-symbol daily bars and empty corporate-action intervals; nonempty actions and incomplete responses remain errors.
