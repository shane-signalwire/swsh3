#!/usr/bin/env python3
"""Ask a space's SIP edges whether they are still talking to this address.

CLAUDE.md says to rule out the source-address block before changing any code
when a registration stops working, and until now it shipped no way to do that.
This is that way.

Repeated failed REGISTERs get the source address blocked, and the block is
**per transport**: UDP stops answering while TCP keeps returning
`200 Keepalive`, or one edge answers and the other accepts the connection and
returns nothing. Either shape is indistinguishable from "the stack cannot
register" if the only thing you can see is the error your own client printed.

One OPTIONS per edge per transport, and that is deliberate — looping is what
causes the block, so a diagnostic that retried would deepen the hole it is
reporting on. Nothing here authenticates: an OPTIONS needs no credentials, and
sending one with credentials is how a diagnostic becomes another failed
attempt. No project token is read and no account is created.

    python scripts/probe_sip_edges.py acme-7f3c1a2b9d04.sip.signalwire.com

The domain is the one on the project's SIP profile - `sw sipprofile get`, or
the `identity` line that `y` copies out of the cockpit. It is never derived
from the space host; see "The SIP domain is read, never derived".
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from swsh.softphone import edge_report


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("domain", help="the project's SIP domain")
    parser.add_argument("--timeout", type=float, default=4.0,
                        help="seconds to wait per probe (default: 4)")
    args = parser.parse_args()
    for line in asyncio.run(edge_report(args.domain, timeout=args.timeout)):
        print(line)


if __name__ == "__main__":
    main()
