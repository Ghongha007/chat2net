"""Command line for chat2net."""
from __future__ import annotations

import argparse
import os
import secrets
import sys

from . import __version__
from .core import KINDS, FormatError, Network, parse_time, read

EPILOG = """examples:
  chat2net result.json                     Telegram Desktop export of a group or channel
  chat2net twitter-archive/ --owner myname X archive folder (ego network of one account)
  chat2net video.info.json                 YouTube comments saved by yt-dlp --write-comments
  chat2net posts.csv --author-col user --text-col text
  chat2net pairs.csv --source-col from --target-col to
  chat2net a.json b.json --anonymise --gexf

Open edges.csv in Gephi with File > Import spreadsheet and choose "Edges table".
"""


def main(argv=None) -> int:
    p = argparse.ArgumentParser(
        prog="chat2net",
        description="Turn chat and social-media exports into network files (edges.csv, nodes.csv) for Gephi.",
        epilog=EPILOG, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("inputs", nargs="+", help="one or more export files (or an X archive folder)")
    p.add_argument("-o", "--out", default="network", help="output folder (default: ./network)")
    p.add_argument("-f", "--format", default="auto", choices=["auto", "telegram", "x", "youtube", "csv"])
    p.add_argument("--kinds", default=",".join(KINDS),
                   help="which interactions to keep, comma separated (default: %(default)s)")
    p.add_argument("--min-weight", type=int, default=1, metavar="N",
                   help="drop connections with fewer than N interactions")
    p.add_argument("--since", help="keep interactions on or after this date (YYYY-MM-DD)")
    p.add_argument("--until", help="keep interactions on or before this date (YYYY-MM-DD)")
    p.add_argument("--anonymise", action="store_true",
                   help="replace every account name with a salted hash before writing")
    p.add_argument("--salt", help="salt for --anonymise; reuse it to get the same ids across runs")
    p.add_argument("--gexf", action="store_true", help="also write network.gexf")
    p.add_argument("--case-sensitive", action="store_true", help="treat 'Name' and 'name' as different accounts")
    p.add_argument("--top", type=int, default=10, help="how many accounts to list in the summary")
    p.add_argument("--owner", help="X archive: the account's username, if account.js is missing")
    g = p.add_argument_group("CSV columns (guessed from the header if not given)")
    for name in ("source", "target", "author", "text", "time", "kind"):
        g.add_argument(f"--{name}-col", metavar="NAME")
    p.add_argument("--version", action="version", version=f"chat2net {__version__}")
    a = p.parse_args(argv)

    kinds = {k.strip().lower() for k in a.kinds.split(",") if k.strip()}
    bad = kinds - set(KINDS)
    if bad:
        p.error(f"unknown kind: {', '.join(sorted(bad))}. Choose from {', '.join(KINDS)}")
    since = parse_time(a.since) if a.since else None
    until = parse_time(a.until + " 23:59:59") if a.until else None
    if (a.since and not since) or (a.until and not until):
        p.error("dates must look like 2026-11-16")

    net = Network(case_sensitive=a.case_sensitive)
    opts = {k: getattr(a, k) for k in ("owner", "source_col", "target_col", "author_col",
                                         "text_col", "time_col", "kind_col")}
    for path in a.inputs:
        if not os.path.exists(path):
            print(f"chat2net: no such file: {path}", file=sys.stderr)
            return 2
        try:
            net.extend(read(path, a.format, **opts), kinds=kinds, since=since, until=until)
        except FormatError as e:
            print(f"chat2net: {path}: {e}", file=sys.stderr)
            return 2
    net.prune(a.min_weight)
    if not net.edges:
        print("chat2net: no interactions found (check --kinds, the dates, or the column names)", file=sys.stderr)
        return 1
    if a.anonymise:
        salt = a.salt or secrets.token_hex(16)
        net.anonymise(salt)
        if not a.salt:
            print("Names replaced with random ids. The salt was not saved, so ids will differ next run;\n"
                  "pass --salt to keep them stable.\n")
    print(net.summary(a.top))
    ep, np_ = net.write_csv(a.out)
    print(f"\nWrote {ep}\n      {np_}")
    if a.gexf:
        print(f"      {net.write_gexf(os.path.join(a.out, 'network.gexf'))}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
