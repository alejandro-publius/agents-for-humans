"""Last Elevator dispatch package: Block F, standalone and offline.

Models propose, code decides. Nothing in this package calls AWS, BART, or
the network; every make target that would needs credentials and has a
--dry-run that is the only mode exercised here.
"""

__version__ = "0.1.0"
