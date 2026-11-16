import csv, os, tempfile, unittest
from chat2net.core import Network, read, detect, FormatError
from chat2net.cli import main

FX = os.path.join(os.path.dirname(__file__), "fixtures")
fx = lambda n: os.path.join(FX, n)
def net(name, **kw):
    return Network().extend(read(fx(name), **kw))
def E(n):
    return {(n.label[a], n.label[b]): dict(c) for (a, b), c in n.edges.items()}

class T(unittest.TestCase):
    def test_detect(self):
        self.assertEqual(detect(fx("telegram.json")), "telegram")
        self.assertEqual(detect(fx("tweets.js")), "x")
        self.assertEqual(detect(fx("video.info.json")), "youtube")
        self.assertEqual(detect(fx("posts.csv")), "csv")

    def test_telegram(self):
        n = net("telegram.json")
        e = E(n)
        self.assertEqual(e[("Ben", "Asha")], {"reply": 1})
        self.assertEqual(e[("Chitra", "Asha")], {"reply": 1})
        self.assertEqual(e[("Chitra", "dev_k")], {"mention": 1})
        self.assertEqual(e[("Ben", "City News")], {"forward": 1})
        self.assertEqual(e[("Asha", "Ben")], {"reply": 1})
        self.assertEqual(n.skipped_self, 1)
        self.assertEqual(len(e), 5)

    def test_x(self):
        e = E(net("tweets.js", owner="me"))
        self.assertEqual(e, {("me", "newsdesk"): {"repost": 1}, ("me", "ben"): {"reply": 1}, ("me", "Chitra"): {"mention": 1}})

    def test_youtube(self):
        e = E(net("video.info.json"))
        self.assertEqual(e[("@asha", "Channel X")], {"reply": 1})
        self.assertEqual(e[("@ben", "@asha")], {"reply": 1})
        self.assertEqual(e[("@chitra", "Channel X")], {"reply": 1})

    def test_csv_text(self):
        e = E(net("posts.csv"))
        self.assertEqual(e[("asha", "ben")], {"repost": 1})
        self.assertEqual(e[("ben", "asha")], {"mention": 1})
        self.assertEqual(e[("ben", "Chitra")], {"mention": 1})   # "Chitra" and "chitra" are one account; first spelling is the label
        self.assertEqual(e[("dev", "asha")], {"mention": 1})     # repeated mention in one post counts once
        self.assertEqual(len(e), 4)                  # e-mail address is not a mention

    def test_csv_pairs(self):
        e = E(net("pairs.tsv"))
        self.assertEqual(e, {("asha", "ben"): {"reply": 2}, ("ben", "asha"): {"mention": 1}})

    def test_filters(self):
        n = Network().extend(read(fx("telegram.json")), kinds={"reply"})
        self.assertTrue(all(set(c) == {"reply"} for c in n.edges.values()))
        from datetime import datetime
        n = Network().extend(read(fx("telegram.json")), since=datetime(2026, 10, 2))
        self.assertEqual(set(E(n)), {("Ben", "City News"), ("Asha", "Ben")})

    def test_anonymise(self):
        n = net("telegram.json"); n.anonymise("s")
        m = net("telegram.json"); m.anonymise("s")
        self.assertEqual(set(n.edges), set(m.edges))
        self.assertTrue(all(k.startswith("n_") for k in n.label))
        self.assertFalse(any("asha" in k for k in n.label))
        o = net("telegram.json"); o.anonymise("other")
        self.assertNotEqual(set(n.label), set(o.label))

    def test_cli(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(main([fx("telegram.json"), fx("posts.csv"), "-o", d, "--gexf"]), 0)
            rows = list(csv.DictReader(open(os.path.join(d, "edges.csv"), encoding="utf-8")))
            self.assertEqual(rows[0]["Type"], "Directed")
            self.assertEqual(sum(int(r["Weight"]) for r in rows), 9)
            nodes = list(csv.DictReader(open(os.path.join(d, "nodes.csv"), encoding="utf-8")))
            self.assertEqual({r["Id"] for r in nodes}, {r["Source"] for r in rows} | {r["Target"] for r in rows})
            import xml.dom.minidom as x
            g = x.parse(os.path.join(d, "network.gexf"))
            self.assertEqual(len(g.getElementsByTagName("edge")), len(rows))
            self.assertEqual(main([fx("posts.csv"), "-o", d, "--min-weight", "5"]), 1)
            self.assertEqual(main(["nope.json", "-o", d]), 2)

    def test_bad(self):
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            f.write('{"hello": 1}')
        with self.assertRaises(FormatError):
            detect(f.name)
        os.unlink(f.name)

if __name__ == "__main__":
    unittest.main()
