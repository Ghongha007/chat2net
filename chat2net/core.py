"""chat2net: turn chat and social-media exports into network files for Gephi.

Every parser yields Interaction records: who acted, towards whom, how, and when.
Direction always runs from the account that acted to the account it acted on:
a reply points at the person replied to, a mention at the person mentioned,
a forward or repost at the original author.
"""
from __future__ import annotations

import csv
import hashlib
import json
import os
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable, Iterator, Optional
from xml.sax.saxutils import quoteattr

KINDS = ("reply", "mention", "forward", "repost")
MENTION_RE = re.compile(r"(?<![\w@])@([A-Za-z0-9_]{2,32})")
RT_RE = re.compile(r"^\s*RT @([A-Za-z0-9_]{1,32})\b")


@dataclass
class Interaction:
    source: str
    target: str
    kind: str
    when: Optional[datetime] = None


class FormatError(ValueError):
    """The input file is not in the format the parser expects."""


def parse_time(value) -> Optional[datetime]:
    """Best-effort timestamp parser. Returns a naive datetime, or None."""
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value, timezone.utc).replace(tzinfo=None)
    s = str(value).strip()
    if s.isdigit():
        n = int(s)
        return datetime.fromtimestamp(n / 1000 if n > 10**11 else n, timezone.utc).replace(tzinfo=None)
    for fmt in ("%a %b %d %H:%M:%S %z %Y",):
        try:
            return datetime.strptime(s, fmt).replace(tzinfo=None)
        except ValueError:
            pass
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        return None


# ---------------------------------------------------------------- Telegram

def _tg_text_mentions(msg: dict) -> list[str]:
    out = []
    ents = msg.get("text_entities")
    if ents is None and isinstance(msg.get("text"), list):
        ents = [e for e in msg["text"] if isinstance(e, dict)]
    for e in ents or []:
        if e.get("type") == "mention":
            out.append(str(e.get("text", "")).lstrip("@"))
    return [m for m in out if m]


def _tg_chat(chat: dict) -> Iterator[Interaction]:
    msgs = [m for m in chat.get("messages", []) if m.get("type") == "message"]
    author = {}
    for m in msgs:
        name = m.get("from") or m.get("from_id") or chat.get("name")
        if name:
            author[m.get("id")] = str(name)
    for m in msgs:
        src = author.get(m.get("id"))
        if not src:
            continue
        when = parse_time(m.get("date_unixtime") or m.get("date"))
        parent = author.get(m.get("reply_to_message_id"))
        if parent:
            yield Interaction(src, parent, "reply", when)
        fwd = m.get("forwarded_from")
        if fwd:
            yield Interaction(src, str(fwd), "forward", when)
        for name in _tg_text_mentions(m):
            yield Interaction(src, name, "mention", when)


def parse_telegram(path: str) -> Iterator[Interaction]:
    """Telegram Desktop export: result.json of one chat, or of a full account export."""
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, dict) and "messages" in data:
        yield from _tg_chat(data)
    elif isinstance(data, dict) and isinstance(data.get("chats"), dict):
        for chat in data["chats"].get("list", []):
            yield from _tg_chat(chat)
    else:
        raise FormatError("not a Telegram Desktop JSON export (no 'messages' or 'chats' key)")


# ---------------------------------------------------------------- X archive

def _load_ytd(path: str):
    """X archive .js files are JSON behind a 'window.YTD.x.part0 = ' prefix."""
    with open(path, encoding="utf-8") as f:
        raw = f.read()
    start = min((i for i in (raw.find("["), raw.find("{")) if i >= 0), default=-1)
    if start < 0:
        raise FormatError("no JSON found in file")
    return json.loads(raw[start:])


def parse_x_archive(path: str, owner: Optional[str] = None) -> Iterator[Interaction]:
    """tweets.js from a downloaded X (Twitter) archive.

    An archive holds one account's posts, so the result is that account's ego network.
    """
    if os.path.isdir(path):
        for cand in ("data/tweets.js", "tweets.js", "data/tweet.js"):
            if os.path.exists(os.path.join(path, cand)):
                path = os.path.join(path, cand)
                break
        else:
            raise FormatError("no tweets.js in this folder")
    if not owner:
        acc = os.path.join(os.path.dirname(path), "account.js")
        if os.path.exists(acc):
            try:
                owner = _load_ytd(acc)[0]["account"]["username"]
            except (KeyError, IndexError, TypeError, ValueError):
                owner = None
    owner = owner or "archive_owner"
    items = _load_ytd(path)
    if not isinstance(items, list):
        raise FormatError("tweets.js did not contain a list")
    for it in items:
        tw = it.get("tweet", it) if isinstance(it, dict) else None
        if not isinstance(tw, dict) or "full_text" not in tw and "text" not in tw:
            continue
        text = tw.get("full_text") or tw.get("text") or ""
        when = parse_time(tw.get("created_at"))
        rt = RT_RE.match(text)
        if rt:
            yield Interaction(owner, rt.group(1), "repost", when)
            continue
        reply_to = tw.get("in_reply_to_screen_name")
        if reply_to:
            yield Interaction(owner, reply_to, "reply", when)
        seen = {str(reply_to).lower()} if reply_to else set()
        for um in (tw.get("entities") or {}).get("user_mentions", []):
            name = um.get("screen_name")
            if name and name.lower() not in seen:
                seen.add(name.lower())
                yield Interaction(owner, name, "mention", when)


# ---------------------------------------------------------------- YouTube

def parse_youtube(path: str) -> Iterator[Interaction]:
    """A yt-dlp .info.json file saved with --write-comments."""
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    comments = data.get("comments") if isinstance(data, dict) else None
    if not isinstance(comments, list):
        raise FormatError("no 'comments' list; save with: yt-dlp --skip-download --write-comments URL")
    uploader = data.get("uploader") or data.get("channel") or "video_uploader"
    by_id = {c.get("id"): c.get("author") for c in comments}
    for c in comments:
        src = c.get("author")
        if not src:
            continue
        when = parse_time(c.get("timestamp"))
        parent = c.get("parent")
        if parent and parent != "root":
            tgt = by_id.get(parent)
            if tgt:
                yield Interaction(src, tgt, "reply", when)
        else:
            yield Interaction(src, uploader, "reply", when)
        for name in MENTION_RE.findall(c.get("text") or ""):
            yield Interaction(src, name, "mention", when)


# ---------------------------------------------------------------- CSV / TSV

def _pick(header: list[str], wanted: Optional[str], guesses: tuple[str, ...]) -> Optional[str]:
    low = {h.lower().strip(): h for h in header}
    if wanted:
        if wanted in header:
            return wanted
        if wanted.lower() in low:
            return low[wanted.lower()]
        raise FormatError(f"column '{wanted}' not found; columns are: {', '.join(header)}")
    for g in guesses:
        if g in low:
            return low[g]
    return None


def parse_table(path: str, source_col=None, target_col=None, author_col=None,
                text_col=None, time_col=None, kind_col=None) -> Iterator[Interaction]:
    """A CSV or TSV file, read in one of two ways.

    Pairs mode: one column for who acted and one for whom they acted on.
    Text mode: one column for the author and one for the post text; @mentions and
    'RT @name' are pulled out of the text.
    """
    with open(path, encoding="utf-8-sig", newline="") as f:
        sample = f.read(8192)
        f.seek(0)
        try:
            dialect = csv.Sniffer().sniff(sample, delimiters=",\t;|")
        except csv.Error:
            dialect = csv.excel_tab if path.lower().endswith((".tsv", ".tab")) else csv.excel
        rd = csv.DictReader(f, dialect=dialect)
        header = rd.fieldnames or []
        src = _pick(header, source_col, ("source", "from", "src", "sender"))
        tgt = _pick(header, target_col, ("target", "to", "dst", "recipient"))
        tcol = _pick(header, time_col, ("date", "time", "timestamp", "created_at", "datetime"))
        kcol = _pick(header, kind_col, ("kind", "interaction"))
        pairs = bool(src and tgt) and not (author_col or text_col)
        if not pairs:
            src = _pick(header, author_col, ("author", "username", "user", "screen_name", "from", "channel"))
            txt = _pick(header, text_col, ("text", "full_text", "tweet", "content", "message", "body"))
            if not (src and txt):
                raise FormatError(
                    "could not tell which columns to use. Give --source-col and --target-col, "
                    f"or --author-col and --text-col. Columns are: {', '.join(header)}")
        for row in rd:
            a = (row.get(src) or "").strip().lstrip("@")
            if not a:
                continue
            when = parse_time(row.get(tcol)) if tcol else None
            if pairs:
                b = (row.get(tgt) or "").strip().lstrip("@")
                kind = (row.get(kcol) or "").strip().lower() if kcol else ""
                if b:
                    yield Interaction(a, b, kind if kind in KINDS else "mention", when)
                continue
            text = row.get(txt) or ""
            rt = RT_RE.match(text)
            if rt:
                yield Interaction(a, rt.group(1), "repost", when)
                continue
            for name in dict.fromkeys(MENTION_RE.findall(text)):
                yield Interaction(a, name, "mention", when)


# ---------------------------------------------------------------- detection

def detect(path: str) -> str:
    if os.path.isdir(path):
        return "x"
    low = path.lower()
    if low.endswith((".csv", ".tsv", ".tab", ".txt")):
        return "csv"
    if low.endswith(".js"):
        return "x"
    with open(path, encoding="utf-8") as f:
        head = f.read(4096)
    if head.lstrip().startswith("window.YTD"):
        return "x"
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except ValueError as e:
        raise FormatError(f"cannot read this file as JSON or CSV: {e}") from None
    if isinstance(data, dict):
        if isinstance(data.get("comments"), list):
            return "youtube"
        if "messages" in data or "chats" in data:
            return "telegram"
    if isinstance(data, list) and data and isinstance(data[0], dict) and "tweet" in data[0]:
        return "x"
    raise FormatError("could not recognise this file; set --format telegram|x|youtube|csv")


def read(path: str, fmt: str = "auto", **opts) -> Iterator[Interaction]:
    fmt = detect(path) if fmt == "auto" else fmt
    if fmt == "telegram":
        return parse_telegram(path)
    if fmt == "x":
        return parse_x_archive(path, owner=opts.get("owner"))
    if fmt == "youtube":
        return parse_youtube(path)
    if fmt == "csv":
        keys = ("source_col", "target_col", "author_col", "text_col", "time_col", "kind_col")
        return parse_table(path, **{k: opts.get(k) for k in keys})
    raise FormatError(f"unknown format '{fmt}'")


# ---------------------------------------------------------------- graph

class Network:
    """A directed, weighted network built from interactions."""

    def __init__(self, case_sensitive: bool = False):
        self.case_sensitive = case_sensitive
        self.label: dict[str, str] = {}
        self.edges: dict[tuple[str, str], Counter] = defaultdict(Counter)
        self.first: dict[tuple[str, str], datetime] = {}
        self.last: dict[tuple[str, str], datetime] = {}
        self.skipped_self = 0
        self.total = 0

    def _key(self, name: str) -> str:
        name = " ".join(str(name).split())
        key = name if self.case_sensitive else name.lower()
        self.label.setdefault(key, name)
        return key

    def add(self, it: Interaction) -> None:
        if not it.source or not it.target:
            return
        a, b = self._key(it.source), self._key(it.target)
        if a == b:
            self.skipped_self += 1
            return
        self.total += 1
        self.edges[(a, b)][it.kind] += 1
        if it.when:
            k = (a, b)
            if k not in self.first or it.when < self.first[k]:
                self.first[k] = it.when
            if k not in self.last or it.when > self.last[k]:
                self.last[k] = it.when

    def extend(self, items: Iterable[Interaction], kinds=None, since=None, until=None) -> "Network":
        for it in items:
            if kinds and it.kind not in kinds:
                continue
            if it.when and ((since and it.when < since) or (until and it.when > until)):
                continue
            if (since or until) and it.when is None:
                continue
            self.add(it)
        return self

    def prune(self, min_weight: int = 1) -> None:
        if min_weight > 1:
            self.edges = defaultdict(Counter, {k: v for k, v in self.edges.items()
                                               if sum(v.values()) >= min_weight})

    def anonymise(self, salt: str) -> None:
        """Replace every name with a salted hash. Without the salt the names cannot be recovered by lookup."""
        def h(key: str) -> str:
            return "n_" + hashlib.sha256((salt + "\0" + key).encode("utf-8")).hexdigest()[:10]
        m = {k: h(k) for k in self.label}
        self.label = {m[k]: m[k] for k in self.label}
        self.edges = defaultdict(Counter, {(m[a], m[b]): c for (a, b), c in self.edges.items()})
        self.first = {(m[a], m[b]): v for (a, b), v in self.first.items()}
        self.last = {(m[a], m[b]): v for (a, b), v in self.last.items()}

    def node_stats(self) -> dict[str, dict]:
        st: dict[str, dict] = {}
        for (a, b), c in self.edges.items():
            w = sum(c.values())
            for n in (a, b):
                st.setdefault(n, {"in": 0, "out": 0, "in_from": 0, "out_to": 0})
            st[a]["out"] += w
            st[a]["out_to"] += 1
            st[b]["in"] += w
            st[b]["in_from"] += 1
        return st

    def summary(self, top: int = 10) -> str:
        st = self.node_stats()
        n, m = len(st), len(self.edges)
        mutual = sum(1 for (a, b) in self.edges if (b, a) in self.edges) // 2
        kinds = Counter()
        for c in self.edges.values():
            kinds.update(c)
        lines = [f"{n:,} accounts, {m:,} connections, {self.total:,} interactions"]
        if kinds:
            names = {"reply": "replies", "mention": "mentions", "forward": "forwards", "repost": "reposts"}
            lines.append("  " + ", ".join(f"{kinds[k]:,} {names[k]}" for k in KINDS if kinds[k]))
        if m:
            lines.append(f"  pairs that interact in both directions: {mutual:,}")
        if self.skipped_self:
            lines.append(f"  self-interactions left out: {self.skipped_self:,}")
        if st:
            lines.append("Accounts that received the most (interactions, distinct senders, name):")
            for k, v in sorted(st.items(), key=lambda kv: (-kv[1]["in"], kv[0]))[:top]:
                if v["in"]:
                    lines.append(f"  {v['in']:>6,}  {v['in_from']:>5,}  {self.label.get(k, k)}")
        return "\n".join(lines)

    # ------------------------------------------------------------ writers

    def write_csv(self, outdir: str) -> tuple[str, str]:
        os.makedirs(outdir, exist_ok=True)
        ep, np_ = os.path.join(outdir, "edges.csv"), os.path.join(outdir, "nodes.csv")
        with open(ep, "w", encoding="utf-8", newline="") as f:
            w = csv.writer(f)
            w.writerow(["Source", "Target", "Type", "Weight", "Replies", "Mentions", "Forwards", "Reposts", "First", "Last"])
            for (a, b), c in sorted(self.edges.items(), key=lambda kv: (-sum(kv[1].values()), kv[0])):
                k = (a, b)
                w.writerow([a, b, "Directed", sum(c.values()), c["reply"], c["mention"], c["forward"], c["repost"],
                            self.first[k].isoformat(sep=" ") if k in self.first else "",
                            self.last[k].isoformat(sep=" ") if k in self.last else ""])
        st = self.node_stats()
        with open(np_, "w", encoding="utf-8", newline="") as f:
            w = csv.writer(f)
            w.writerow(["Id", "Label", "Received", "Sent", "ReceivedFrom", "SentTo"])
            for k, v in sorted(st.items(), key=lambda kv: (-kv[1]["in"], kv[0])):
                w.writerow([k, self.label.get(k, k), v["in"], v["out"], v["in_from"], v["out_to"]])
        return ep, np_

    def write_gexf(self, path: str) -> str:
        st = self.node_stats()
        ids = {k: str(i) for i, k in enumerate(sorted(st))}
        out = ['<?xml version="1.0" encoding="UTF-8"?>',
               '<gexf xmlns="http://gexf.net/1.3" version="1.3">',
               '<meta><creator>chat2net</creator></meta>',
               '<graph defaultedgetype="directed" mode="static">', '<nodes>']
        for k, i in ids.items():
            out.append(f'<node id="{i}" label={quoteattr(self.label.get(k, k))}/>')
        out.append('</nodes>')
        out.append('<edges>')
        for n, ((a, b), c) in enumerate(sorted(self.edges.items())):
            out.append(f'<edge id="{n}" source="{ids[a]}" target="{ids[b]}" weight="{sum(c.values())}"/>')
        out += ['</edges>', '</graph>', '</gexf>']
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write("\n".join(out) + "\n")
        return path


__all__ = ["Interaction", "Network", "FormatError", "read", "detect", "parse_time",
           "parse_telegram", "parse_x_archive", "parse_youtube", "parse_table"]
