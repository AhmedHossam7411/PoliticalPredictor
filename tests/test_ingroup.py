"""Tests for the contextual in-group analysis (predictor.ingroup).

Run from the project folder:
    python -m unittest tests.test_ingroup -v
"""
from __future__ import annotations

import unittest

from predictor import ingroup as ig


def _one(result: dict) -> dict:
    """The single passage of a one-sentence text."""
    assert len(result["passages"]) == 1, result["passages"]
    return result["passages"][0]


def _group(result: dict, key: str) -> dict | None:
    return next((g for g in result["groups"] if g["key"] == key), None)


class Scenarios(unittest.TestCase):
    # Test 1 -- national identity
    def test_1_national_identity(self):
        r = ig.analyze("We must protect our sovereignty and defend our people.",
                       home="EG", role="President of Egypt", affiliations=["African Union", "BRICS"])
        p = _one(r)
        self.assertEqual(p["group"], "nation")
        self.assertIn(p["confidence"], ("high", "medium"))
        self.assertEqual(p["categories"], ["identification"])
        self.assertFalse(p["bias"])

    # Test 2 -- multinational coalition, at a BRICS summit
    def test_2_multinational_coalition(self):
        text = "We must strengthen our cooperation and defend our shared interests."
        r = ig.analyze(text, home="ZA", role="President of South Africa", affiliations=["BRICS", "African Union"],
                       setting={"event": "BRICS Summit", "host": "BRICS"})
        p = _one(r)
        self.assertEqual(p["group"], "org:BRICS")
        self.assertNotEqual(p["group"], "nation")
        self.assertEqual(r["setting"]["type"], "multilateral")
        # The setting points the multinational cue to BRICS; the cue itself comes from the words.
        self.assertTrue(any("cooperation" in w or "shared" in w for ref in p["refs"] for w in ref["why"]))

    def test_2b_multinational_without_setting_is_not_national(self):
        r = ig.analyze("We must strengthen our cooperation and defend our shared interests.", home="ZA")
        p = _one(r)
        self.assertNotEqual(p["group"], "nation")
        self.assertEqual(p["group"], "partnership")   # a coalition, but not named
        self.assertFalse(p["counted"])                # unnamed partnerships are not scored

    def test_2c_host_alone_does_not_assign(self):
        # The host organisation is not the referent of every "we".
        r = ig.analyze("We must act now.", setting={"event": "BRICS Summit", "host": "BRICS"})
        self.assertIsNone(_one(r)["group"])

    # Test 3 -- several groups in one speech
    def test_3_multiple_groups(self):
        text = ("We will protect our sovereignty and our people.\n\n"
                "In the African Union, we have built a common future. Our union must speak with one voice.\n\n"
                "We, the international community, must end this war. Our planet cannot wait.")
        r = ig.analyze(text, home="EG", role="President of Egypt", affiliations=["African Union", "BRICS"])
        by_sentence = {p["i"]: p["group"] for p in r["passages"]}
        self.assertEqual(by_sentence[0], "nation")
        self.assertEqual(by_sentence[1], "org:AU")
        self.assertEqual(by_sentence[2], "org:AU")
        self.assertEqual(by_sentence[3], "col:INTL")
        self.assertEqual(by_sentence[4], "col:INTL")
        self.assertEqual({g["key"] for g in r["groups"]}, {"nation", "org:AU", "col:INTL"})

    # Test 4 -- ordinary solidarity
    def test_4_solidarity_is_not_bias(self):
        r = ig.analyze("We are stronger when we cooperate.")
        p = _one(r)
        self.assertFalse(p["bias"])
        self.assertNotIn("superiority", p["categories"])
        r = ig.analyze("We are committed to building a stronger Africa together.", home="ZA",
                       affiliations=["African Union"])
        self.assertFalse(_one(r)["bias"])

    # Test 5 -- explicit preferential treatment
    def test_5_preference(self):
        r = ig.analyze("Our country's interests must always take priority over those of other nations.", home="US")
        p = _one(r)
        self.assertEqual(p["group"], "nation")
        self.assertIn("preference", p["categories"])
        self.assertTrue(p["bias"])

    # Test 6 -- quoted speech
    def test_6_quotation_not_attributed(self):
        r = ig.analyze('As one politician said, "They are our enemies."', home="EG")
        p = _one(r)
        self.assertEqual(p["voice"], "quoted")
        self.assertFalse(p["counted"])
        self.assertFalse(p["bias"])

    def test_6b_reported_speech_not_attributed(self):
        p = _one(ig.analyze("He told the crowd that they are our enemies.", home="EG"))
        self.assertEqual(p["voice"], "reported")
        self.assertFalse(p["bias"])

    # Test 7 -- organisation-specific analysis
    def test_7_separate_organisation_assessments(self):
        aff = ["African Union", "BRICS", "UN Security Council (permanent member)"]
        au = ("Our union must speak with one voice. Our union has grown stronger. We will deepen our integration. "
              "Our member states share one destiny. Our organisation will defend our common agenda. "
              "Our union's interests must take priority over those of other blocs.")
        brics = ("We must strengthen our cooperation. Our partnership is growing. Our shared interests are clear. "
                 "Our bloc will expand. We will deepen our cooperation in trade. Our grouping serves the Global South.")
        un = ("Our organisation was founded to save succeeding generations. Our charter must be respected. "
              "Our member states must uphold it. We will reform our council. Our institution must adapt. "
              "Our common agenda is peace.")
        results = [({"id": "a", "title": "AU summit"}, ig.analyze(au, home="ZA", affiliations=aff,
                                                                 setting={"event": "African Union Summit"})),
                   ({"id": "b", "title": "BRICS summit"}, ig.analyze(brics, home="ZA", affiliations=aff,
                                                                    setting={"event": "BRICS Summit"})),
                   ({"id": "c", "title": "UN"}, ig.analyze(un, home="ZA", affiliations=aff,
                                                          setting={"host": "United Nations General Assembly"}))]
        merged = ig.merge(results)
        groups = {g["key"]: g for g in merged["groups"]}
        for key in ("org:AU", "org:BRICS", "org:UN"):
            self.assertIn(key, groups)
            self.assertGreaterEqual(groups[key]["references"], ig.MIN_REFS)
            self.assertNotEqual(groups[key]["assessment"], "Insufficient evidence")
        # The preference sentence belongs to the AU only.
        self.assertEqual(groups["org:AU"]["counts"]["preference"], 1)
        self.assertEqual(groups["org:BRICS"]["counts"]["preference"], 0)
        self.assertEqual(groups["org:UN"]["counts"]["preference"], 0)
        self.assertGreater(groups["org:AU"]["share"], groups["org:BRICS"]["share"])
        # Each assessment keeps its own speeches and setting.
        self.assertEqual([s["title"] for s in groups["org:BRICS"]["speeches"]], ["BRICS summit"])

    # Test 8 -- ambiguous referent
    def test_8_ambiguous(self):
        p = _one(ig.analyze("We must act now."))
        self.assertIsNone(p["group"])
        self.assertFalse(p["counted"])
        self.assertEqual(ig.analyze("We must act now.")["ambiguous"], 1)


class Safeguards(unittest.TestCase):
    def test_negated_preference_is_set_aside(self):
        p = _one(ig.analyze("We do not put our national interests above those of other nations.", home="EG"))
        self.assertEqual(p["group"], "nation")
        self.assertFalse(p["bias"])
        self.assertTrue(p["negated"])

    def test_negation_elsewhere_keeps_the_label(self):
        p = _one(ig.analyze("We will never let our enemies win.", home="EG"))
        self.assertIn("hostility", p["rule_categories"])

    def test_denial_about_self_is_not_hostility(self):
        p = _one(ig.analyze("We are not terrorists.", home="EG"))
        self.assertNotIn("hostility", p["rule_categories"])

    def test_superiority(self):
        p = _one(ig.analyze("We are the greatest nation on earth.", home="US"))
        self.assertEqual(p["group"], "nation")
        self.assertIn("superiority", p["categories"])

    def test_factual_superlative_is_not_superiority(self):
        p = _one(ig.analyze("Our greatest strength is our people.", home="US"))
        self.assertNotIn("superiority", p["categories"])

    def test_differentiation(self):
        text = "Our nation believes in cooperation, whereas they seek confrontation."
        p = _one(ig.analyze(text, home="EG"))
        self.assertEqual(p["group"], "nation")
        self.assertIn("differentiation", p["categories"])

    def test_hypothetical_is_not_bias(self):
        p = _one(ig.analyze("If our nation were greater than all others, we would rule.", home="EG"))
        self.assertIn("hypothetical", p["modality"])
        self.assertFalse(p["bias"])

    def test_insufficient_evidence(self):
        r = ig.analyze("Our country's interests must always take priority over those of other nations.", home="US")
        self.assertEqual(_group(r, "nation")["assessment"], "Insufficient evidence")
        self.assertIsNone(_group(r, "nation")["share"])

    def test_groups_come_from_records(self):
        # Nothing hard-coded: any membership line becomes a candidate group.
        cands = ig.candidate_groups("", "EG", "President of Egypt",
                                    ["East Mediterranean Gas Forum (founding member)", "Non-Aligned Movement"],
                                    {"host_entity": None})
        names = {c["name"] for c in cands}
        self.assertIn("East Mediterranean Gas Forum", names)
        self.assertIn("Non-Aligned Movement", names)
        rel = next(c for c in cands if c["name"] == "East Mediterranean Gas Forum")["relation"]
        self.assertEqual(rel, "East Mediterranean Gas Forum (founding member)")
        r = ig.analyze("As members of the Non-Aligned Movement, we reject the logic of blocs.", home="EG",
                       affiliations=["Non-Aligned Movement"])
        self.assertEqual(_one(r)["group"], "org:non-aligned-movement")

    def test_stakeholder_records(self):
        home, role, aff = ig.speaker_records("ramaphosa")
        self.assertEqual(home, "ZA")
        cands = {c["key"] for c in ig.candidate_groups("", home, role, aff, {"host_entity": None})}
        self.assertTrue({"org:BRICS", "org:AU", "org:G20"} <= cands)

    def test_decisions_override_and_trace(self):
        r = ig.analyze("We must act now.", decisions=[{"sentence": 0, "group": "nation", "source": "person"}],
                       home="EG")
        p = _one(r)
        self.assertEqual(p["group"], "nation")
        self.assertEqual(p["source"], "person")
        self.assertEqual(p["confidence"], "reviewed")

    def test_arabic_basic(self):
        r = ig.analyze("يجب أن نحمي سيادة وطننا وحدود بلادنا.", home="EG")
        self.assertEqual(_one(r)["group"], "nation")
        p = _one(ig.analyze("قال أحدهم: «هم أعداؤنا».", home="EG"))
        self.assertFalse(p["counted"])

    def test_ai_cannot_overturn_structural_evidence(self):
        """Karnak may resolve ambiguous sentences, but not turn a quotation into the
        speaker's words or replace a group the rules resolved confidently."""
        from unittest import mock
        text = ('We must act now. As one politician said, "They are our enemies." '
                "Our country's interests must always take priority over those of other nations.")
        fake = {"s": [{"i": 0, "ref": "nation", "voice": "own", "cats": []},
                      {"i": 1, "ref": "nation", "voice": "own", "cats": ["HOST"]},
                      {"i": 2, "ref": "AMBIG", "voice": "own", "cats": ["PREF"]}]}
        base = {p["i"]: p for p in ig.analyze(text, home="EG")["passages"]}
        with mock.patch("predictor.llm.chat_json", return_value=(fake, "test")):
            out = ig.ai_check(text, home="EG")
        by = {p["i"]: p for p in out["result"]["passages"]}
        self.assertIsNone(base[0]["group"])
        self.assertEqual(by[0]["group"], "nation")           # ambiguous -> resolved by the AI
        self.assertEqual(by[0]["source"], "ai")
        self.assertEqual(by[1]["voice"], "quoted")           # the quotation is kept
        self.assertFalse(by[1]["counted"])
        self.assertEqual(by[2]["group"], "nation")           # a confident rules referent is kept
        self.assertIn("Karnak suggested", by[2]["note"])
        # A person's decision always wins over Karnak's.
        with mock.patch("predictor.llm.chat_json", return_value=(fake, "test")):
            out = ig.ai_check(text, decisions=[{"sentence": 0, "group": "ambiguous", "source": "person"}], home="EG")
        self.assertIsNone({p["i"]: p for p in out["result"]["passages"]}[0]["group"])

    def test_existing_igb_trait_unchanged(self):
        from predictor.lta import score_lta
        tr = score_lta("Our nation and our citizens defend the homeland against foreign threats.")["traits"]["IGB"]
        self.assertEqual(tr["kind"], "density")
        self.assertGreater(tr["count"], 0)


if __name__ == "__main__":
    unittest.main()
