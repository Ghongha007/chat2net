# chat2net

Turn a chat or social-media export into a network you can open in Gephi.

You have a Telegram group export, a spreadsheet of posts, or the comments under a video, and you want to know who talks to whom. `chat2net` reads the file and writes two tables: `edges.csv` (who interacted with whom, and how often) and `nodes.csv` (one row per account).

- One command, no configuration for the common formats.
- No dependencies. It needs only Python 3.9 or newer.
- Works offline. Nothing is uploaded anywhere.
- `--anonymise` replaces every name with a salted hash, so you can share a network without sharing who is in it.

```
$ chat2net examples/telegram_sample.json
5 accounts, 5 connections, 5 interactions
  3 replies, 1 mentions, 1 forwards
  pairs that interact in both directions: 1
  self-interactions left out: 1
Accounts that received the most (interactions, distinct senders, name):
       2      2  Asha
       1      1  Ben
       1      1  City News
       1      1  dev_k

Wrote network/edges.csv
      network/nodes.csv
```

## Install

```
git clone https://github.com/Ghongha007/chat2net.git
cd chat2net
pip install .
```

Or run it without installing: `python3 -m chat2net <file>` from inside the folder.

## What it reads

| Source | How to get the file | What becomes a connection |
|---|---|---|
| **Telegram** | Telegram Desktop: open the chat, menu, *Export chat history*, format *JSON*. Gives `result.json`. | replies, forwards, @mentions |
| **X (Twitter) archive** | *Settings > Your account > Download an archive of your data*. Point at the folder or at `data/tweets.js`. | replies, reposts, @mentions |
| **YouTube comments** | `yt-dlp --skip-download --write-comments URL` gives `<title>.info.json`. | replies to a comment, @handle mentions; top-level comments point at the uploader |
| **Any CSV or TSV of posts** | A table with an author column and a text column. | `RT @name` and @mentions found in the text |
| **Any CSV or TSV of pairs** | A table with a "from" column and a "to" column. | one interaction per row |

The format is detected from the file. Use `--format` if detection gets it wrong.

An X archive contains one account's posts, so it gives that account's own network (an "ego network"), not a whole conversation. For a wider picture, use a CSV of posts from many accounts.

## Direction

Every connection points **from the account that acted to the account it acted on**:

- a reply points at the person replied to
- a mention points at the person mentioned
- a forward or repost points at the original author

So an account with many incoming connections is one that others respond to, name, or pass along.

## Output

`edges.csv`

| Column | Meaning |
|---|---|
| Source, Target | the two accounts |
| Type | always `Directed` (Gephi reads this column) |
| Weight | total interactions from Source to Target |
| Replies, Mentions, Forwards, Reposts | the same total, split by kind |
| First, Last | time of the first and last interaction, when the export has times |

`nodes.csv` has `Id`, `Label`, and four counts: interactions received and sent, and how many distinct accounts they came from or went to.

`--gexf` also writes `network.gexf`, which Gephi opens directly.

## Open it in Gephi

1. *File > Import spreadsheet...* and choose `edges.csv`. Gephi should recognise it as an **Edges table**.
2. Optional: import `nodes.csv` the same way as a **Nodes table**, and choose *Append to existing workspace*.
3. In *Layout*, choose **ForceAtlas 2** and press *Run*. Press *Stop* when it settles.
4. In *Statistics*, run **Modularity**. In *Appearance*, colour nodes by *Modularity Class*.
5. In *Appearance*, size nodes by **Degree**.

## Options

```
-o, --out DIR        output folder (default: ./network)
-f, --format         auto, telegram, x, youtube, csv
--kinds              keep only some interactions, e.g. --kinds reply,mention
--min-weight N       drop connections with fewer than N interactions
--since, --until     keep a date range (YYYY-MM-DD)
--anonymise          replace names with salted hashes
--salt TEXT          reuse a salt so the same account gets the same id across runs
--gexf               also write network.gexf
--case-sensitive     treat "Name" and "name" as different accounts
--top N              how many accounts to list in the summary
--owner NAME         X archive: the account's username if account.js is missing
--source-col, --target-col, --author-col, --text-col, --time-col, --kind-col
```

Several files can be combined into one network: `chat2net groupA.json groupB.json`.

## Limits you should know about

- **A cluster is a lead, not proof.** Accounts land close together because they interact. That can mean coordination. It can also mean they are colleagues, rivals, or fans of the same team. Read the posts before drawing a conclusion.
- **Telegram names are display names.** Two people with the same display name are merged into one account, and one person who changes their name appears twice. Mentions use @usernames, which are a different identifier from display names, so a mentioned account and the same person's messages may appear as two nodes.
- **Names differing only in capital letters are merged** unless you pass `--case-sensitive`.
- **In a CSV of pairs, each row counts as one interaction.** An existing weight column is not read.
- **Self-replies are left out** and counted in the summary.
- The X archive and Telegram export formats are not formally documented and can change. The parsers were written against the formats as of November 2026. The YouTube parser has been checked against real `yt-dlp` output (300 comments, counts verified independently). The Telegram and X parsers have been tested only on small hand-made sample files, not on real exports. If a file fails, please open an issue with the structure (not the content) of the file.

## Use it responsibly

- Use exports you are entitled to hold: your own archive, a public channel or group, or data shared with you with consent.
- A group export contains other people's messages and names. Store it carefully and delete it when the work is done.
- Use `--anonymise` before sharing a network outside your team, and remember that the shape of a small network can identify people even without names.
- This tool does not collect data from any platform. It only reads files you already have.

## Tests

```
python3 -m unittest discover -s tests
```

## Related

- [india-osint](https://github.com/Ghongha007/india-osint): public records and open data for investigating stories in India
- [ai-for-osint](https://github.com/Ghongha007/ai-for-osint): AI tools for investigators, with where each runs and its known limits
- [osint-skills](https://github.com/Ghongha007/osint-skills): agent skills for verification, geolocation, chronolocation and fact-checking
- [verify-mcp](https://github.com/Ghongha007/verify-mcp): an MCP server with keyless, read-only verification lookups
- [osint-visuals](https://github.com/Ghongha007/osint-visuals): agent skills for evidence graphics: ship and flight tracks, shadow diagrams, 3D scenes, satellite before/after and scroll stories

## Licence

MIT. Made by [OSINT JOURNO](https://github.com/OSINT-JOURNO).
