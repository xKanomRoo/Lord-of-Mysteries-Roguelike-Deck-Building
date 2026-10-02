extends SceneTree

const Rules = preload("res://scripts/game_engine.gd")
var assertions = 0
var failures = 0

func check(condition: bool, message: String) -> void:
	assertions += 1
	if not condition:
		failures += 1
		printerr("FAIL: " + message)

func fixture(hand: Array, player: Dictionary = {}, enemy: Dictionary = {}) -> Dictionary:
	var state = Rules.create_run(123)
	state.hand = hand.duplicate()
	state.player.merge(player, true)
	state.enemy.merge(enemy, true)
	return state

func legal_play(state: Dictionary) -> int:
	var playable = []
	for index in range(state.hand.size()):
		var card = Rules.get_card(state.hand[index])
		card.index = index
		if card.cost <= state.player.energy:
			playable.append(card)
	for card in playable:
		if card.get("damage", 0) > 0 and card.damage + state.powers.attack_bonus >= state.enemy.hp + state.enemy.block:
			return card.index
	for card in playable:
		if card.cost == 0:
			return card.index
	for card in playable:
		if card.type == "power" and state.turn < 3:
			return card.index
	if state.enemy.intent.kind == "attack" and state.player.block < state.enemy.intent.value:
		var best_guard = {}
		for card in playable:
			if card.get("block", 0) > 0 and (best_guard.is_empty() or card.block + card.get("damage", 0) > best_guard.block + best_guard.get("damage", 0)):
				best_guard = card
		if not best_guard.is_empty():
			return best_guard.index
	var best_attack = {}
	for card in playable:
		if card.get("damage", 0) > 0 and (best_attack.is_empty() or float(card.damage) / card.cost > float(best_attack.damage) / best_attack.cost):
			best_attack = card
	return best_attack.get("index", -1)

func expanded_checks() -> void:
	check(Rules.data().cards.size() == 54 and Rules.data().enemies.size() == 21 and Rules.data().events.size() == 12 and Rules.data().relics.size() == 12, "authored expansion contains54cards21enemies12events12relics")
	var decks = []
	for path in Rules.pathways():
		var run = Rules.create_run(123, path.id)
		check(run.pathway == path.id and run.deck.size() == 12 and run.relics == [path.starting_relic], "pathway has its own starterdeck/relic: " + path.id)
		check(Rules.validate_state(run) and Rules.decode_save(JSON.parse_string(JSON.stringify(Rules.make_save(run)))) == run, "pathway state/save validates: " + path.id)
		decks.append(run.deck)
	check(decks[0] != decks[1] and decks[1] != decks[2] and decks[0] != decks[2], "all3pathways provide different startingdecks")
	var state = fixture(["tracker_eye", "tracker_eye"])
	state.draw_pile = []
	state.discard_pile = []
	state.player.sanity = 0
	state = Rules.act(state, {"type":"PLAY_CARD", "index":0})
	state = Rules.act(state, {"type":"PLAY_CARD", "index":0})
	check(state.hand.is_empty() and state.exhaust_pile == ["tracker_eye", "tracker_eye"] and state.discard_pile.is_empty(), "Tracker Eye pair exhausts atzeroSanity insteadofrecyclingforever")
	state = Rules.create_run(123, "apprentice")
	state.deck = ["cold_reading", "etched_strike", "etched_strike", "paper_ward", "paper_ward"]
	state.hand = state.deck.duplicate()
	state.draw_pile = []
	state.discard_pile = []
	state.exhaust_pile = []
	state.player.sanity = 0
	state.player.block = 0
	check(Rules.validate_state(state), "freeColdReadingexploitfixtureconservesdeck+piles")
	state = Rules.act(state, {"type":"PLAY_CARD", "index":0})
	check(state.exhaust_pile == ["cold_reading"] and "cold_reading" not in state.hand and state.player.block == 2 and Rules.validate_state(state), "ColdReadingat0Sanitygrantsrelicblockonceandexhausts")
	state = Rules.act(state, {"type":"END_TURN"})
	check("cold_reading" not in state.hand and state.exhaust_pile == ["cold_reading"] and Rules.validate_state(state), "nextturncannotrecycleColdReadingtostackfreeblock")
	state = fixture(["etched_strike"], {"weak":1}, {"vulnerable":1})
	check(Rules.act(state, {"type":"PLAY_CARD", "index":0}).enemy.hp == 24, "Weak floors6to4 thenVulnerable floors4to6")
	state = fixture([], {"block":20}, {"poison":3, "intent":{"kind":"defend", "value":5}, "intent_index":2})
	var poisoned = Rules.act(state, {"type":"END_TURN"})
	check(poisoned.enemy.hp == 27 and poisoned.enemy.poison == 2 and poisoned.enemy.block == 5, "Poison ignoresfreshblock anddecaysone afterenemyturn")
	state.player.poison = 3
	poisoned = Rules.act(state, {"type":"END_TURN"})
	check(poisoned.player.hp == 67 and poisoned.player.poison == 2, "playerPoison ignoresblock atplayerturnend")
	state.enemy.hp = 2
	state.player.poison = 0
	check(Rules.act(state, {"type":"END_TURN"}).phase == "reward", "poisonkillingblowclosescombat beforedrawnextturn")
	var retained_id = ""
	for card in Rules.data().cards:
		if card.get("retain", false):
			retained_id = card.id
			break
	state = fixture([retained_id])
	check(retained_id in Rules.act(state, {"type":"END_TURN"}).hand, "Retain cardstaysinhand acrossendturn")
	state = Rules.create_run(123, "apprentice")
	state.hand = ["field_notes"]
	state.draw_pile = ["etched_strike", "paper_ward", "steady_breath"]
	state.discard_pile = []
	state.player.block = 0
	var notes = Rules.act(state, {"type":"PLAY_CARD", "index":0})
	check(notes.hand.size() == 1 and notes.player.block > 0, "conditionaldraw doesnotcount blockgrantedbyitscardorrelic")
	state.player.block = 1
	check(Rules.act(state, {"type":"PLAY_CARD", "index":0}).hand.size() == 2, "conditionaldraw rewardsblockpresentbeforeplay")
	state = fixture(["etched_strike"], {"hp":30, "sanity":3}, {"hp":1})
	state = Rules.act(state, {"type":"PLAY_CARD", "index":0})
	var old_deck = state.deck.duplicate()
	var skipped = Rules.act(state, {"type":"SKIP_REWARD"})
	check(skipped.phase == "route" and skipped.deck == old_deck and skipped.player.hp == 34 and skipped.player.sanity == 5, "skipreward keepsdeckthin andappliesrecovery")
	check(Rules.act(skipped, {"type":"CHOOSE_ROUTE", "route_id":"missing"}) == skipped, "invalidroute cannotadvance")
	# Exercise all36 authored event choices through the real dispatcher and save.
	for event in Rules.data().events:
		for choice in event.choices:
			state = Rules.create_run(123)
			state.encounter = (event.get("act", 1) - 1) * 4 + 1
			state.pending_enemy_id = ""
			Rules._start_encounter(state)
			state.phase = "event"
			state.enemy.hp = 0
			state.event_id = event.id
			state.player.hp = 40
			state.player.sanity = 5
			var before = state.duplicate(true)
			var chosen = Rules.act(state, {"type":"CHOOSE_EVENT", "choice_id":choice.id})
			if choice.effects.get("gain_relic", "") in state.relics:
				check(chosen == state, "ownedrelicchoice refusescost: " + event.id)
			else:
				check(chosen.phase == "combat" and chosen.encounter == state.encounter + 1, "eventchoice changesrunandadvances: %s/%s" % [event.id, choice.id])
				check(Rules.validate_state(chosen) and not Rules.make_save(chosen).is_empty(), "eventeffect stateisboundedandsavable: %s/%s" % [event.id, choice.id])
			check(state == before, "eventtransition preservesoldstate: " + event.id)
	state = Rules.create_run(123)
	var max_hp = state.player.max_hp
	Rules._gain_relic(state, "stone_amulet")
	Rules._gain_relic(state, "stone_amulet")
	check(state.player.max_hp == max_hp + 8 and state.relics.count("stone_amulet") == 1, "maxHP relicgrantsbonusonlyonce")
	for pathway in ["hunter", "apprentice"]:
		check_pathway_campaign(pathway)

func check_pathway_campaign(pathway: String) -> void:
	var run = Rules.create_run(123, pathway)
	var actions = 0
	while run.phase not in ["victory", "defeat"] and actions < 2500:
		match run.phase:
			"combat":
				var index = legal_play(run)
				run = Rules.act(run, {"type":"PLAY_CARD", "index":index} if index >= 0 else {"type":"END_TURN"})
			"reward":
				run = Rules.act(run, {"type":"CHOOSE_REWARD", "card_id":run.rewards[0]})
			"route":
				var route: Dictionary = run.route_options[0]
				for option in run.route_options:
					if option.kind == "rest":
						route = option
				run = Rules.act(run, {"type":"CHOOSE_ROUTE", "route_id":route.id})
			"event":
				run = Rules.act(run, {"type":"CHOOSE_EVENT", "choice_id":Rules.get_event(run.event_id).choices[-1].id})
			"rest": run = Rules.act(run, {"type":"REST", "option":"heal"})
			"relic": run = Rules.act(run, {"type":"CHOOSE_RELIC", "relic_id":run.relic_rewards[0]})
		check(Rules.validate_state(run), "%slegalcampaignstatevalidatstep%d" % [pathway, actions])
		check(Rules.decode_save(JSON.parse_string(JSON.stringify(Rules.make_save(run)))) == run, "%scampaignsaveroundtripatstep%d" % [pathway, actions])
		actions += 1
	check(run.phase == "victory" and run.encounter == 11 and run.player.hp > 0, "%scompletesall12combatsusinglegalactionsin%dsteps" % [pathway, actions])

func _initialize() -> void:
	expanded_checks()
	var start = Rules.create_run(123)
	check(start == Rules.create_run(123), "seed reproduces all state")
	check(start.hand == ["etched_strike", "spirit_lance", "etched_strike", "paper_ward", "etched_strike"], "seed123 matches JavaScript engine shuffle")
	check(start.rng == 3225291048, "unsigned xorshift matches JavaScript RNG")
	check(Rules.create_run(0).hand == ["etched_strike", "cold_reading", "etched_strike", "etched_strike", "paper_ward"], "zero seed fallback matches JavaScript")
	check(start.hand != Rules.create_run(789).hand, "different seed changes hand")
	check(Rules.validate_state(start), "fresh state validates")
	check(Rules.get_card("missing").is_empty(), "unknown card rejected")
	var state = fixture(["etched_strike", "paper_ward"])
	var old = state.duplicate(true)
	var next = Rules.act(state, {"type":"PLAY_CARD", "index":0})
	check(next.player.energy == 2 and next.enemy.hp == 24, "attack pays energy and damage")
	check(next.hand == ["paper_ward"] and next.discard_pile == ["etched_strike"], "played card leaves hand and discards")
	check(state == old, "transition does not mutate snapshot")
	state = fixture(["spirit_lance"], {"energy":1})
	for action in [{"type":"PLAY_CARD", "index":0}, {"type":"PLAY_CARD", "index":-1}, {"type":"PLAY_CARD", "index":0.5}, {"type":"PLAY_CARD", "index":true}, {"type":"PLAY_CARD", "index":4}, {"type":"CHOOSE_REWARD", "card_id":"moon_cut"}, {}, {"type":"UNKNOWN"}]:
		check(Rules.act(state, action) == state, "invalid or unaffordable action unchanged: %s" % str(action))
	state = fixture(["paper_ward"])
	next = Rules.act(Rules.act(state, {"type":"PLAY_CARD", "index":0}), {"type":"END_TURN"})
	check(next.player.hp == 70 and next.player.block == 0, "block absorbs attack then expires")
	check(next.player.energy == 3 and next.turn == 2 and next.hand.size() == 5, "turn refreshes energy and draws5")
	check(next.enemy.intent == {"kind":"attack", "value":7}, "next intent preview is truthful")
	state = fixture(["etched_strike"], {}, {"intent":{"kind":"defend", "value":8}, "intent_index":2})
	next = Rules.act(state, {"type":"END_TURN"})
	check(next.enemy.block == 8, "enemy announced defense applies")
	next.hand = ["etched_strike"]
	next = Rules.act(next, {"type":"PLAY_CARD", "index":0})
	check(next.enemy.hp == 30 and next.enemy.block == 2, "enemy defense blocks player attack")
	check(Rules.act(next, {"type":"END_TURN"}).enemy.block == 0, "enemy old defense expires")
	state = fixture(["cold_reading"])
	state.draw_pile = ["etched_strike"]
	state.discard_pile = ["paper_ward", "steady_breath"]
	next = Rules.act(state, {"type":"PLAY_CARD", "index":0})
	check(next.hand.size() == 2 and next.hand[0] == "etched_strike" and next.draw_pile.size() == 1, "draw crosses pile and reshuffles")
	check(next.discard_pile.is_empty() and next.exhaust_pile == ["cold_reading"] and next.player.sanity == 11, "resolving card exhausts after draw")
	check(next == Rules.act(state, {"type":"PLAY_CARD", "index":0}), "reshuffle deterministic")
	state.draw_pile = []
	state.discard_pile = []
	next = Rules.act(state, {"type":"PLAY_CARD", "index":0})
	check(next.hand.is_empty() and next.exhaust_pile == ["cold_reading"], "draw card cannot draw itself")
	state = fixture(["spirit_lance"], {"sanity":1, "block":20})
	next = Rules.act(state, {"type":"PLAY_CARD", "index":0})
	check(next.player.sanity == 0, "sanity clamps at zero")
	check(Rules.act(next, {"type":"END_TURN"}).player.hp == 67, "zero sanity damage ignores block")
	check(Rules.act(fixture(["steady_breath"], {"sanity":11}), {"type":"PLAY_CARD", "index":0}).player.sanity == 12, "sanity recover caps12")
	state = fixture(["sealed_oath", "etched_strike"])
	next = Rules.act(state, {"type":"PLAY_CARD", "index":0})
	check(next.exhaust_pile == ["sealed_oath"] and next.discard_pile.is_empty(), "power exhausts for encounter")
	check(Rules.act(next, {"type":"PLAY_CARD", "index":0}).enemy.hp == 22, "power adds attackdamage")
	state = fixture(["etched_strike"], {"hp":40, "sanity":4}, {"hp":6})
	next = Rules.act(state, {"type":"PLAY_CARD", "index":0})
	check(next.phase == "reward" and next.enemy.hp == 0 and next.rewards.size() == 3, "kill enters reward with3cards")
	check(Rules.act(next, {"type":"CHOOSE_REWARD", "card_id":"missing"}) == next, "invalid reward rejected")
	var advanced = Rules.act(next, {"type":"CHOOSE_REWARD", "card_id":next.rewards[0]})
	check(advanced.encounter == 0 and advanced.phase == "route" and advanced.deck.size() == 13, "reward opens route and joins deck")
	check(advanced.player.hp == 44 and advanced.player.sanity == 6, "reward heals4 andsanity2")
	advanced = Rules.act(advanced, {"type":"CHOOSE_ROUTE", "route_id":advanced.route_options[0].id})
	check(advanced.encounter == 1 and advanced.phase == "combat" and advanced.powers.attack_bonus == 0, "chosen route advances and resets powers")
	state = fixture([], {"hp":2, "block":0})
	next = Rules.act(state, {"type":"END_TURN"})
	check(next.phase == "defeat" and next.player.hp == 0 and Rules.act(next, {"type":"END_TURN"}) == next, "defeat stops future actions")
	# Full run uses only legal actions and validates/saves at every transition.
	state = Rules.create_run(123)
	var actions = 0
	var rewards_chosen = 0
	var preferences = ["moon_cut", "red_thread", "sealed_oath", "lantern_flare", "mirror_shield", "quiet_formula"]
	while state.phase not in ["victory", "defeat"] and actions < 2500:
		check(Rules.validate_state(state), "legal transition %d validates" % actions)
		var encoded = JSON.stringify(Rules.make_save(state))
		check(Rules.decode_save(JSON.parse_string(encoded)) == state, "save roundtrip at transition %d" % actions)
		if state.phase == "reward":
			var reward_id: String = state.rewards[0]
			for id in preferences:
				if id in state.rewards:
					reward_id = id
					break
			state = Rules.act(state, {"type":"CHOOSE_REWARD", "card_id":reward_id})
			rewards_chosen += 1
		elif state.phase == "route":
			var route: Dictionary = state.route_options[0]
			for option in state.route_options:
				if option.kind == "rest":
					route = option
			state = Rules.act(state, {"type":"CHOOSE_ROUTE", "route_id":route.id})
		elif state.phase == "rest":
			state = Rules.act(state, {"type":"REST", "option":"heal"})
		elif state.phase == "event":
			var choices: Array = Rules.get_event(state.event_id).choices
			state = Rules.act(state, {"type":"CHOOSE_EVENT", "choice_id":choices[-1].id})
		elif state.phase == "relic":
			state = Rules.act(state, {"type":"CHOOSE_RELIC", "relic_id":state.relic_rewards[0]})
		else:
			var index = legal_play(state)
			state = Rules.act(state, {"type":"PLAY_CARD", "index":index} if index >= 0 else {"type":"END_TURN"})
		actions += 1
	check(state.phase == "victory" and state.encounter == 11 and state.player.hp > 0 and rewards_chosen == 9, "legal full run wins all12encounters in%dactions" % actions)
	check(Rules.validate_state(state), "victory state validates")
	check(Rules.act(state, {"type":"END_TURN"}) == state, "victory stops actions")
	var valid = Rules.make_save(Rules.create_run(123))
	check(Rules.decode_save(valid) == Rules.create_run(123), "versioned save restores exact seeded state")
	for corruption in ["schema_version", "state_sha256", "deck", "hp", "intent", "unknown_field", "float_rng", "oversized_log", "wrong_type"]:
		var bad = valid.duplicate(true)
		match corruption:
			"schema_version": bad.schema_version = 3
			"state_sha256": bad.state_sha256 = "0".repeat(64)
			"deck": bad.state.deck.append("moon_cut")
			"hp": bad.state.player.hp = 999
			"intent": bad.state.enemy.intent.value = 999
			"unknown_field": bad.state.untrusted_instruction = "ignored data"
			"float_rng": bad.state.rng = 1.5
			"oversized_log": bad.state.log = ["x".repeat(1000)]
			"wrong_type": bad.state.player = []
		check(Rules.decode_save(bad).is_empty(), "corrupted/unsupported save rejected: " + corruption)
	check(Rules.decode_save({}).is_empty() and Rules.decode_save(null).is_empty(), "missing save rejected")
	print("Native engine: %d assertions, %d failures; legal complete seeded run: %d actions." % [assertions, failures, actions])
	quit(1 if failures > 0 else 0)
