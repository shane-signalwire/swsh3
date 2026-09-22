"""Make the suite independent of the terminal it is run from.

Rich decides on colour and wrap width from the environment as well as from the
destination, and Typer's ``CliRunner`` captures whatever it emits. A developer
shell exporting ``FORCE_COLOR`` therefore turns rendered output into escape
sequences, and a narrow window wraps a ``--help`` table mid-word so that
asserting on a flag name fails. Neither is a bug in ``sw``; between them they
failed about fifty tests on one machine and none on another.

These are set at **import** time rather than in a fixture. ``swsh.ui`` builds
its ``Console`` at module scope, so by the time a fixture runs, the test module
has already imported it and the decision is made. conftest is imported before
any test module, which is the only hook early enough.
"""

from __future__ import annotations

import os

# Everything Rich consults for colour, plus the two that set the wrap width.
for _forced in ("FORCE_COLOR", "CLICOLOR_FORCE", "CLICOLOR", "COLORTERM"):
    os.environ.pop(_forced, None)
# Belt as well as braces: `_autoinstall_completion` reads the streams rather
# than `prompts.interactive()`, so a test patching that cannot reach it — but a
# suite that appends to the developer's own ~/.zshrc once has earned a second
# lock on the door.
os.environ["SWSH_NO_COMPLETION_INSTALL"] = "1"
os.environ["NO_COLOR"] = "1"
os.environ["TERM"] = "dumb"
# Wide enough that no help table wraps a flag or a field name.
os.environ["COLUMNS"] = "200"
os.environ["LINES"] = "50"
