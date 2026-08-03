"""Runs before any test module is collected.

test_verified_publish_contract.py installs a bare stub for genblaze_core (and
genblaze_s3) into sys.modules ONLY as a fallback "in a lightweight local test
environment where the optional Genblaze SDK extras are not installed" --
its own comment says to prefer the real modules when they're present.

But without this file, whether a test gets the real package or that stub
depends on pytest's alphabetical collection order: whichever test file
happens to import genblaze_core first wins for the rest of the session,
since every stub guard is `if "genblaze_core" not in sys.modules`. That's
fragile in a way that has nothing to do with whether the SDK is actually
installed -- add a new test file with a name that sorts before
"test_verified_publish_contract.py" and it silently gets the stub instead of
the real thing it needs.

Importing the real packages here, before collection starts, makes the
outcome deterministic and matches what the stub guards already say they
want: real SDK wins whenever it's installed; the stub only ever applies in
the lightweight environment the stub comments describe.
"""
import importlib

for _mod in ("genblaze_core", "genblaze_s3", "genblaze_gmicloud", "genblaze_elevenlabs"):
    try:
        importlib.import_module(_mod)
    except ImportError:
        pass
