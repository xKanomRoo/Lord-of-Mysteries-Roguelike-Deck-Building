"""Validate the shipped original mobile content contract without private references."""

import json
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]
CONTENT_PATH = ROOT / "mobile" / "data" / "content.json"
SCALAR_EFFECTS = {
    "damage", "block", "draw", "sanity_cost", "sanity", "heal", "energy",
    "attack_bonus", "poison", "weak", "vulnerable", "damage_if_poison",
    "damage_if_weak", "block_if_vulnerable", "draw_if_block", "sanity_if_poison",
}
BOOLEAN_EFFECTS = {"retain", "exhaust"}
CARD_FIELDS = {
    "id", "name", "cost", "type", "rarity", "pathway", "description",
} | SCALAR_EFFECTS | BOOLEAN_EFFECTS
RELIC_EFFECTS = {
    "max_hp", "start_block", "start_energy", "attack_bonus",
    "heal_after_combat", "sanity_after_combat", "draw_first_turn",
    "poison_start", "block_on_skill", "sanity_on_exhaust", "heal_on_kill",
}
EVENT_EFFECTS = {"hp", "sanity", "max_hp", "add_card", "remove_card", "gain_relic"}
ID_PATTERN = re.compile(r"^[a-z][a-z0-9_]{1,63}$")


def unique_json_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Repeated JSON key: {key}")
        result[key] = value
    return result


class MobileContentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.content = json.loads(
            CONTENT_PATH.read_text(encoding="utf-8"), object_pairs_hook=unique_json_object
        )
        cls.cards = {item["id"]: item for item in cls.content["cards"]}
        cls.relics = {item["id"]: item for item in cls.content["relics"]}

    def test_bundle_is_versioned_and_all_ids_are_unique(self):
        self.assertEqual(self.content["version"], 1)
        for field in ("cards", "pathways", "enemies", "events", "relics"):
            items = self.content[field]
            ids = [item["id"] for item in items]
            with self.subTest(field=field):
                self.assertEqual(len(ids), len(set(ids)))
                for item in items:
                    self.assertRegex(item["id"], ID_PATTERN)
                    self.assertTrue(item["name"].strip())
                    self.assertTrue(item["description"].strip())

    def test_pathways_have_playable_starters_and_distinct_identity(self):
        pathways = self.content["pathways"]
        self.assertEqual({p["id"] for p in pathways}, {"seer", "hunter", "apprentice"})
        self.assertEqual(len({tuple(p["deck"]) for p in pathways}), 3)
        self.assertEqual(len({p["starting_relic"] for p in pathways}), 3)
        for pathway in pathways:
            with self.subTest(pathway=pathway["id"]):
                self.assertEqual(len(pathway["deck"]), 12)
                self.assertIn(pathway["starting_relic"], self.relics)
                for card_id in pathway["deck"]:
                    self.assertIn(card_id, self.cards)
                    self.assertIn(self.cards[card_id]["pathway"], {"neutral", pathway["id"]})
                starter = [self.cards[card_id] for card_id in pathway["deck"]]
                self.assertTrue(any(c.get("damage", 0) > 0 for c in starter))
                self.assertTrue(any(c.get("block", 0) > 0 for c in starter))
                self.assertTrue(any(c["cost"] <= 1 for c in starter))

    def test_card_effect_contract_and_reward_pool_diversity(self):
        self.assertGreaterEqual(len(self.cards), 45)
        for pathway in ("neutral", "seer", "hunter", "apprentice"):
            pool = [c for c in self.cards.values() if c["pathway"] == pathway]
            with self.subTest(pathway=pathway):
                self.assertGreaterEqual(len(pool), 10)
                self.assertTrue(any(c["type"] == "attack" for c in pool))
                self.assertTrue(any(c["type"] == "skill" for c in pool))
                self.assertTrue(any(c["rarity"] == "rare" for c in pool))
        for card in self.cards.values():
            with self.subTest(card=card["id"]):
                self.assertFalse(set(card) - CARD_FIELDS)
                self.assertIn(card["type"], {"attack", "skill", "power"})
                self.assertIn(card["rarity"], {"basic", "uncommon", "rare"})
                self.assertIn(card["pathway"], {"neutral", "seer", "hunter", "apprentice"})
                self.assertIs(type(card["cost"]), int)
                self.assertLessEqual(0, card["cost"])
                self.assertLessEqual(card["cost"], 3)
                self.assertTrue(set(card) & SCALAR_EFFECTS)
                for field in SCALAR_EFFECTS & set(card):
                    self.assertIs(type(card[field]), int)
                    self.assertGreater(card[field], 0)
                    self.assertLessEqual(card[field], 30)
                for field in BOOLEAN_EFFECTS & set(card):
                    self.assertIs(type(card[field]), bool)

    def test_cards_are_mechanically_distinct_and_energy_cannot_recycle_freely(self):
        signatures = {}
        for card in self.cards.values():
            signature = tuple(sorted(
                (key, value) for key, value in card.items()
                if key in SCALAR_EFFECTS | BOOLEAN_EFFECTS | {"cost", "type"}
            ))
            self.assertNotIn(signature, signatures, f"Duplicate effects: {card['id']}")
            signatures[signature] = card["id"]
            if card.get("energy", 0) >= card["cost"] and card.get("energy", 0) > 0:
                self.assertTrue(card.get("exhaust"), card["id"])
            if card["cost"] == 0:
                self.assertTrue(
                    card.get("exhaust") or card.get("sanity_cost", 0) > 0,
                    f"Unpriced repeatable zero-cost card: {card['id']}",
                )
            if card.get("damage_if_poison") or card.get("damage_if_weak"):
                self.assertGreater(card.get("damage", 0), 0)
            if card.get("block_if_vulnerable"):
                self.assertGreater(card.get("block", 0), 0)

    def test_every_free_draw_card_exhausts_including_conditional_draw(self):
        # Sanity loss clamps at zero and is not an affordability requirement.
        # No zero-energy draw card may repeatedly recycle or trigger play relics.
        free_draw_cards = [
            card for card in self.cards.values()
            if card["cost"] == 0
            and card.get("draw", 0) + card.get("draw_if_block", 0) > 0
        ]
        self.assertTrue(free_draw_cards)
        for card in free_draw_cards:
            self.assertTrue(card.get("exhaust", False), card["id"])
        self.assertTrue(self.cards["cold_reading"]["exhaust"])

    def test_every_act_has_varied_normal_encounters_and_one_elite_and_boss(self):
        self.assertGreaterEqual(len(self.content["enemies"]), 18)
        for act in (1, 2, 3):
            enemies = [e for e in self.content["enemies"] if e["act"] == act]
            self.assertGreaterEqual(sum(e["tier"] == "normal" for e in enemies), 4)
            self.assertEqual(sum(e["tier"] == "elite" for e in enemies), 1)
            self.assertEqual(sum(e["tier"] == "boss" for e in enemies), 1)
            signatures = {tuple((i["kind"], i["value"]) for i in e["intents"]) for e in enemies}
            self.assertEqual(len(signatures), len(enemies))
        for enemy in self.content["enemies"]:
            self.assertIn(enemy["tier"], {"normal", "elite", "boss"})
            self.assertIn(enemy["act"], {1, 2, 3})
            self.assertIs(type(enemy["max_hp"]), int)
            self.assertLessEqual(20, enemy["max_hp"])
            self.assertLessEqual(enemy["max_hp"], 100)
            self.assertLessEqual(2, len(enemy["intents"]))
            self.assertLessEqual(len(enemy["intents"]), 6)
            for intent in enemy["intents"]:
                self.assertEqual(set(intent), {"kind", "value"})
                self.assertIn(intent["kind"], {"attack", "defend", "poison", "weaken"})
                self.assertIs(type(intent["value"]), int)
                self.assertLessEqual(1, intent["value"])
                self.assertLessEqual(intent["value"], 25)

    def test_events_offer_distinct_choices_with_resolvable_effects(self):
        self.assertGreaterEqual(len(self.content["events"]), 12)
        for event in self.content["events"]:
            with self.subTest(event=event["id"]):
                choices = event["choices"]
                self.assertEqual(len(choices), 3)
                self.assertEqual(len({c["id"] for c in choices}), len(choices))
                self.assertEqual(
                    len({json.dumps(c["effects"], sort_keys=True) for c in choices}), 3
                )
                for choice in choices:
                    self.assertTrue(choice["label"].strip())
                    self.assertTrue(choice["description"].strip())
                    effects = choice["effects"]
                    self.assertTrue(effects)
                    self.assertFalse(set(effects) - EVENT_EFFECTS)
                    for key in ("hp", "sanity", "max_hp"):
                        if key in effects:
                            self.assertIs(type(effects[key]), int)
                            self.assertNotEqual(effects[key], 0)
                    if "hp" in effects:
                        self.assertLessEqual(-20, effects["hp"])
                        self.assertLessEqual(effects["hp"], 20)
                    if "sanity" in effects:
                        self.assertLessEqual(-6, effects["sanity"])
                        self.assertLessEqual(effects["sanity"], 6)
                    if "max_hp" in effects:
                        self.assertLessEqual(1, effects["max_hp"])
                        self.assertLessEqual(effects["max_hp"], 10)
                    if "add_card" in effects:
                        self.assertIn(effects["add_card"], self.cards)
                    if "gain_relic" in effects:
                        self.assertIn(effects["gain_relic"], self.relics)
                    if "remove_card" in effects:
                        self.assertIn(effects["remove_card"], {"starting_attack", "starting_guard"})

    def test_relics_use_implemented_hooks_with_bounded_values(self):
        self.assertGreaterEqual(len(self.relics), 12)
        for relic in self.relics.values():
            self.assertEqual(set(relic), {"id", "name", "description", "effect", "value"})
            self.assertIn(relic["effect"], RELIC_EFFECTS)
            self.assertIs(type(relic["value"]), int)
            self.assertLessEqual(1, relic["value"])
            self.assertLessEqual(relic["value"], 10)
        self.assertTrue({"block_on_skill", "sanity_on_exhaust", "poison_start"} <=
                        {r["effect"] for r in self.relics.values()})

    def test_lore_is_provenance_and_original_rules_not_bundled_novel_text(self):
        metadata = self.content["metadata"]
        self.assertEqual(metadata["classification"], "original-adaptation")
        self.assertEqual({s["id"] for s in metadata["lore_sources"]}, {"lotm-zh", "coi-zh"})
        for source in metadata["lore_sources"]:
            for field in ("original_sha256", "normalized_sha256"):
                self.assertRegex(source[field], r"^[a-f0-9]{64}$")
            self.assertTrue(source["references"])
            for reference in source["references"]:
                self.assertNotIn("text", reference)
                self.assertNotIn("excerpt", reference)
                self.assertIs(type(reference["chapter_index"]), int)
                self.assertIs(type(reference["chunk_id"]), int)
                self.assertRegex(reference["chunk_sha256"], r"^[a-f0-9]{64}$")
                self.assertEqual(len(reference["lines"]), 2)
                self.assertLessEqual(reference["lines"][0], reference["lines"][1])
        self.assertLess(CONTENT_PATH.stat().st_size, 100_000)


if __name__ == "__main__":
    unittest.main()
