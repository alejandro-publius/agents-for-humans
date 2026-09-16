The dispatch package's versions of four scripts this repository already had. The repository's own
`scripts/demo_one.py`, `red_team.py`, `secret_scan.py` and `verify_claims.py` are unchanged and are what
`make demo-one`, `make red-team`, `make secret-scan` and `make verify-claims` run. These four are the
package's, kept so the package's own tests under `tests/dispatch/` exercise the code they were written
for; `scripts/verify_claims.py` merges the package's claim rows, so both tables run from one entry point.
