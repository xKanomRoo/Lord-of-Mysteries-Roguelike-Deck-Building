extends RefCounted
## Original deterministic deckbuilding rules. Authored content is loaded as data.

const SAVE_VERSION = 2
const ENGINE_ID = "beyond-gray-fog-godot-v2"
const MAX_SAVE_BYTES = 65536
const MAX_DECK = 32
const STATUS_KEYS = ["poison", "weak", "vulnerable"]
static var _content: Dictionary = {}

static func data() -> Dictionary:
	if _content.is_empty():
		var parsed = JSON.parse_string(FileAccess.get_file_as_string("res://data/content.json"))
		if typeof(parsed) != TYPE_DICTIONARY:
			push_error("Original game content is missing or invalid.")
			return {}
		_content = _normalize_numbers(parsed)
		for field in ["cards", "pathways", "enemies", "events", "relics"]:
			var lookup = {}
			for item in _content[field]:
				lookup[item.id] = item
			_content[field + "_by_id"] = lookup
	return _content

static func get_card(id: String) -> Dictionary:
	return data().cards_by_id.get(id, {}).duplicate(true)

static func pathways() -> Array:
	return data().pathways.duplicate(true)

static func get_relic(id: String) -> Dictionary:
	return data().relics_by_id.get(id, {}).duplicate(true)

static func get_event(id: String) -> Dictionary:
	return data().events_by_id.get(id, {}).duplicate(true)

static func _log(state: Dictionary, message: String) -> void:
	state.log.append(message)
	if state.log.size() > 40:
		state.log.pop_front()

static func _random(state: Dictionary) -> float:
	var value: int = int(state.rng) & 0xffffffff
	value = (value ^ (value << 13)) & 0xffffffff
	value = (value ^ (value >> 17)) & 0xffffffff
	value = (value ^ (value << 5)) & 0xffffffff
	state.rng = value
	return float(value) / 4294967296.0

static func _shuffle(state: Dictionary, source: Array) -> Array:
	var result = source.duplicate()
	for index in range(result.size() - 1, 0, -1):
		var other = int(floor(_random(state) * (index + 1)))
		var previous = result[index]
		result[index] = result[other]
		result[other] = previous
	return result

static func _draw(state: Dictionary, count: int) -> void:
	for _index in range(count):
		if state.draw_pile.is_empty():
			if state.discard_pile.is_empty():
				break
			state.draw_pile = _shuffle(state, state.discard_pile)
			state.discard_pile = []
			_log(state, "The discard pile returns to the draw pile.")
		state.hand.append(state.draw_pile.pop_back())

static func _relic_value(state: Dictionary, effect: String) -> int:
	var total = 0
	for id in state.relics:
		var relic: Dictionary = data().relics_by_id[id]
		if relic.effect == effect:
			total += relic.value
	return total

static func _gain_relic(state: Dictionary, id: String) -> void:
	if not data().relics_by_id.has(id) or id in state.relics:
		return
	state.relics.append(id)
	var relic: Dictionary = data().relics_by_id[id]
	if relic.effect == "max_hp":
		state.player.max_hp = mini(140, state.player.max_hp + relic.value)
		state.player.hp = mini(state.player.max_hp, state.player.hp + relic.value)
	_log(state, "Relic acquired: %s." % relic.name)

static func _act_number(state: Dictionary) -> int:
	return int(state.encounter / 4) + 1

static func _enemy_pool(state: Dictionary, tier: String) -> Array:
	var ids = []
	for enemy in data().enemies:
		if enemy.act == _act_number(state) and enemy.tier == tier:
			ids.append(enemy.id)
	return ids

static func _start_encounter(state: Dictionary) -> void:
	var tier = "boss" if state.encounter % 4 == 3 else "elite" if state.encounter % 4 == 2 else "normal"
	var id: String = state.pending_enemy_id
	if id.is_empty():
		var pool = _enemy_pool(state, tier)
		id = pool[int(floor(_random(state) * pool.size()))]
	var template: Dictionary = data().enemies_by_id[id]
	state.phase = "combat"
	state.turn = 1
	state.enemy = {"id":id, "name":template.name, "description":template.description, "hp":template.max_hp, "max_hp":template.max_hp, "block":0, "intent_index":0, "intent":template.intents[0].duplicate(true), "poison":mini(20, _relic_value(state, "poison_start")), "weak":0, "vulnerable":0}
	state.player.block = _relic_value(state, "start_block")
	state.player.energy = mini(10, state.player.max_energy + _relic_value(state, "start_energy"))
	for status in STATUS_KEYS:
		state.player[status] = 0
	state.powers = {"attack_bonus":mini(30, _relic_value(state, "attack_bonus"))}
	state.draw_pile = _shuffle(state, state.deck)
	state.hand = []
	state.discard_pile = []
	state.exhaust_pile = []
	state.rewards = []
	state.route_options = []
	state.relic_rewards = []
	state.event_id = ""
	state.pending_enemy_id = ""
	_log(state, "Act %d / encounter %d: %s." % [_act_number(state), state.encounter + 1, template.name])
	_draw(state, 5 + _relic_value(state, "draw_first_turn"))

static func create_run(seed_value: int = 123, pathway: String = "seer") -> Dictionary:
	if not data().pathways_by_id.has(pathway):
		pathway = "seer"
	var path: Dictionary = data().pathways_by_id[pathway]
	var numeric_seed = seed_value & 0xffffffff
	var state = {
		"phase":"combat", "seed":numeric_seed, "rng":numeric_seed if numeric_seed != 0 else 0x9e3779b9, "encounter":0, "pathway":pathway, "turn":1,
		"player":{"hp":70, "max_hp":70, "block":0, "energy":3, "max_energy":3, "sanity":12, "max_sanity":12, "poison":0, "weak":0, "vulnerable":0},
		"enemy":{}, "deck":path.deck.duplicate(), "draw_pile":[], "hand":[], "discard_pile":[], "exhaust_pile":[], "powers":{"attack_bonus":0}, "rewards":[], "relics":[], "relic_rewards":[], "route_options":[], "event_id":"", "pending_enemy_id":"ink_witness", "log":[],
	}
	_gain_relic(state, path.starting_relic)
	_start_encounter(state)
	return state

static func _reward_pool(state: Dictionary) -> Array:
	var ids = []
	for card in data().cards:
		if card.rarity != "basic" and card.get("pathway", "neutral") in ["neutral", state.pathway]:
			ids.append(card.id)
	return ids

static func _finish_encounter(state: Dictionary) -> void:
	if state.enemy.hp > 0:
		return
	state.enemy.hp = 0
	state.player.hp = mini(state.player.max_hp, state.player.hp + _relic_value(state, "heal_after_combat") + _relic_value(state, "heal_on_kill"))
	state.player.sanity = mini(state.player.max_sanity, state.player.sanity + _relic_value(state, "sanity_after_combat"))
	_log(state, "%s is defeated." % state.enemy.name)
	if state.encounter == 11:
		state.phase = "victory"
		state.rewards = []
		_log(state, "Three acts crossed. You write your own ending.")
	elif state.encounter % 4 == 3:
		state.phase = "relic"
		var available = []
		for relic in data().relics:
			if relic.id not in state.relics:
				available.append(relic.id)
		state.relic_rewards = _shuffle(state, available).slice(0, 3)
		_log(state, "Choose one relic before the next act.")
	else:
		state.phase = "reward"
		state.rewards = _shuffle(state, _reward_pool(state)).slice(0, 3)
		_log(state, "Choose a card. Recover 4 health and 2 sanity.")

static func _attack_damage(base: int, attacker: Dictionary, target: Dictionary) -> int:
	var damage = base
	if attacker.weak > 0:
		damage = int(floor(damage * 0.75))
	if target.vulnerable > 0:
		damage = int(floor(damage * 1.5))
	return maxi(0, damage)

static func _damage(target: Dictionary, amount: int) -> int:
	var blocked = mini(target.block, amount)
	target.block -= blocked
	target.hp = maxi(0, target.hp - amount + blocked)
	return amount - blocked

static func _play_card(state: Dictionary, index: int) -> Dictionary:
	var next = state.duplicate(true)
	var card: Dictionary = data().cards_by_id[next.hand[index]]
	var had_block: bool = next.player.block > 0
	next.player.energy = mini(10, next.player.energy - card.cost + card.get("energy", 0))
	next.hand.remove_at(index)
	next.player.sanity = clampi(next.player.sanity - card.get("sanity_cost", 0) + card.get("sanity", 0), 0, next.player.max_sanity)
	next.player.hp = mini(next.player.max_hp, next.player.hp + card.get("heal", 0))
	next.player.block = mini(999, next.player.block + card.get("block", 0) + (card.get("block_if_vulnerable", 0) if next.enemy.vulnerable > 0 else 0))
	if card.type == "skill":
		next.player.block = mini(999, next.player.block + _relic_value(next, "block_on_skill"))
	next.powers.attack_bonus = mini(30, next.powers.attack_bonus + card.get("attack_bonus", 0))
	for status in STATUS_KEYS:
		next.enemy[status] = mini(20, next.enemy[status] + card.get(status, 0))
	if next.enemy.poison > 0:
		next.player.sanity = mini(next.player.max_sanity, next.player.sanity + card.get("sanity_if_poison", 0))
	if card.get("exhaust", false):
		next.player.sanity = mini(next.player.max_sanity, next.player.sanity + _relic_value(next, "sanity_on_exhaust"))
	if card.get("damage", 0) > 0:
		var bonus = card.get("damage_if_poison", 0) if next.enemy.poison > 0 else 0
		bonus += card.get("damage_if_weak", 0) if next.enemy.weak > 0 else 0
		var damage = _attack_damage(card.damage + next.powers.attack_bonus + bonus, next.player, next.enemy)
		var dealt = _damage(next.enemy, damage)
		_log(next, "%s: %d damage%s." % [card.name, dealt, " (%d blocked)" % (damage - dealt) if damage > dealt else ""])
	else:
		_log(next, "%s played." % card.name)
	_finish_encounter(next)
	if next.phase == "combat":
		_draw(next, card.get("draw", 0) + (card.get("draw_if_block", 0) if had_block else 0))
	if card.get("exhaust", false):
		next.exhaust_pile.append(card.id)
	else:
		next.discard_pile.append(card.id)
	return next

static func _poison_tick(state: Dictionary, target: Dictionary, name: String) -> void:
	if target.poison > 0:
		target.hp = maxi(0, target.hp - target.poison)
		_log(state, "%s: %d poison damage, ignoring block." % [name, target.poison])
		target.poison -= 1

static func _end_turn(state: Dictionary) -> Dictionary:
	var next = state.duplicate(true)
	var retained = []
	for id in next.hand:
		if data().cards_by_id[id].get("retain", false):
			retained.append(id)
		else:
			next.discard_pile.append(id)
	next.hand = retained
	next.enemy.block = 0
	if next.player.sanity == 0:
		next.player.hp = maxi(0, next.player.hp - 3)
		_log(next, "Mental strain: lose 3 health, ignoring block.")
	_poison_tick(next, next.player, "You")
	next.player.weak = maxi(0, next.player.weak - 1)
	next.enemy.vulnerable = maxi(0, next.enemy.vulnerable - 1)
	if next.player.hp > 0:
		var intent: Dictionary = next.enemy.intent
		match intent.kind:
			"attack":
				var damage = _attack_damage(intent.value, next.enemy, next.player)
				var dealt = _damage(next.player, damage)
				_log(next, "%s attacks: %d damage%s." % [next.enemy.name, dealt, " (%d blocked)" % (damage - dealt) if damage > dealt else ""])
			"defend":
				next.enemy.block = intent.value
				_log(next, "%s gains %d block." % [next.enemy.name, intent.value])
			"poison":
				next.player.poison = mini(20, next.player.poison + intent.value)
				_log(next, "%s applies %d poison." % [next.enemy.name, intent.value])
			"weaken":
				next.player.weak = mini(20, next.player.weak + intent.value)
				_log(next, "%s applies %d Weak." % [next.enemy.name, intent.value])
	if next.player.hp == 0:
		next.phase = "defeat"
		_log(next, "The archive closes around you.")
		return next
	next.enemy.weak = maxi(0, next.enemy.weak - 1)
	next.player.vulnerable = maxi(0, next.player.vulnerable - 1)
	_poison_tick(next, next.enemy, next.enemy.name)
	_finish_encounter(next)
	if next.phase != "combat":
		return next
	var template: Dictionary = data().enemies_by_id[next.enemy.id]
	next.enemy.intent_index = (next.enemy.intent_index + 1) % template.intents.size()
	next.enemy.intent = template.intents[next.enemy.intent_index].duplicate(true)
	next.turn += 1
	next.player.block = 0
	next.player.energy = next.player.max_energy
	_draw(next, 5)
	return next

static func _route(id: String, kind: String, label: String, description: String, enemy_id: String = "", event_id: String = "") -> Dictionary:
	return {"id":id, "kind":kind, "label":label, "description":description, "enemy_id":enemy_id, "event_id":event_id}

static func _make_route(state: Dictionary) -> void:
	state.phase = "route"
	state.rewards = []
	state.route_options = []
	match state.encounter % 4:
		0:
			var options = _shuffle(state, _enemy_pool(state, "normal")).slice(0, 2)
			for id in options:
				var enemy: Dictionary = data().enemies_by_id[id]
				state.route_options.append(_route("hunt_" + id, "combat", enemy.name, "Choose your next opponent. " + enemy.description, id))
		1:
			var events = []
			for event in data().events:
				if event.get("act", _act_number(state)) == _act_number(state):
					events.append(event.id)
			var event_id: String = events[int(floor(_random(state) * events.size()))]
			state.route_options = [_route("event", "event", data().events_by_id[event_id].name, "Take a risk for a lasting change to your deck.", "", event_id), _route("rest", "rest", "A room of quiet candles", "Recover health or steady your sanity before the elite.")]
		2:
			var boss_id: String = _enemy_pool(state, "boss")[0]
			state.route_options = [_route("rest", "rest", "Prepare for the act boss", "Choose healing or meditation before the final confrontation."), _route("press_on", "combat", "Press onward", "Keep your wounds and face the boss immediately.", boss_id)]
	_log(state, "The route forks. Choose what comes next.")

static func _advance_encounter(state: Dictionary, enemy_id: String = "") -> void:
	state.encounter += 1
	state.pending_enemy_id = enemy_id
	_start_encounter(state)

static func _event_choice(state: Dictionary, choice: Dictionary) -> void:
	var effects: Dictionary = choice.effects
	state.player.max_hp = clampi(state.player.max_hp + effects.get("max_hp", 0), 30, 140)
	state.player.hp = clampi(state.player.hp + effects.get("hp", 0), 0, state.player.max_hp)
	state.player.sanity = clampi(state.player.sanity + effects.get("sanity", 0), 0, state.player.max_sanity)
	if effects.has("add_card") and state.deck.size() < MAX_DECK:
		state.deck.append(effects.add_card)
	if effects.has("remove_card") and state.deck.size() > 5:
		var preferred = "etched_strike" if effects.remove_card == "starting_attack" else "paper_ward"
		var remove_index = state.deck.find(preferred)
		if remove_index < 0:
			for index in range(state.deck.size()):
				var card: Dictionary = data().cards_by_id[state.deck[index]]
				if card.rarity == "basic" and card.type == ("attack" if effects.remove_card == "starting_attack" else "skill"):
					remove_index = index
					break
		if remove_index >= 0:
			state.deck.remove_at(remove_index)
	if effects.has("gain_relic"):
		_gain_relic(state, effects.gain_relic)
	_log(state, "%s: %s" % [choice.label, choice.description])
	state.draw_pile = state.deck.duplicate()
	state.hand = []
	state.discard_pile = []
	state.exhaust_pile = []
	state.event_id = ""
	if state.player.hp == 0:
		state.phase = "defeat"
		_log(state, "The price was more than you could bear.")
	else:
		_advance_encounter(state)

static func act(state: Dictionary, action: Dictionary) -> Dictionary:
	if state.is_empty():
		return state
	var kind = action.get("type", "")
	if state.phase == "combat":
		if kind == "PLAY_CARD":
			var index = action.get("index", -1)
			if typeof(index) != TYPE_INT or index < 0 or index >= state.hand.size():
				return state
			var card: Dictionary = get_card(state.hand[index])
			if card.is_empty() or card.cost > state.player.energy:
				return state
			return _play_card(state, index)
		if kind == "END_TURN":
			return _end_turn(state)
	if state.phase == "reward" and kind == "CHOOSE_REWARD" and action.get("card_id", "") in state.rewards and state.deck.size() < MAX_DECK:
		var next = state.duplicate(true)
		var id: String = action.card_id
		next.deck.append(id)
		# The newly acquired card is inert until the next encounter.
		next.draw_pile.append(id)
		next.player.hp = mini(next.player.max_hp, next.player.hp + 4)
		next.player.sanity = mini(next.player.max_sanity, next.player.sanity + 2)
		_log(next, "%s joins your deck." % get_card(id).name)
		_make_route(next)
		return next
	if state.phase == "reward" and kind == "SKIP_REWARD":
		var next = state.duplicate(true)
		next.player.hp = mini(next.player.max_hp, next.player.hp + 4)
		next.player.sanity = mini(next.player.max_sanity, next.player.sanity + 2)
		_log(next, "You leave the card behind and keep the deck focused.")
		_make_route(next)
		return next
	if state.phase == "route" and kind == "CHOOSE_ROUTE":
		for route in state.route_options:
			if route.id == action.get("route_id", ""):
				var next = state.duplicate(true)
				next.route_options = []
				if route.kind == "combat":
					_advance_encounter(next, route.enemy_id)
				elif route.kind == "event":
					next.phase = "event"
					next.event_id = route.event_id
				else:
					next.phase = "rest"
				_log(next, route.label)
				return next
	if state.phase == "event" and kind == "CHOOSE_EVENT":
		for choice in get_event(state.event_id).choices:
			if choice.id == action.get("choice_id", ""):
				if choice.effects.get("gain_relic", "") in state.relics:
					return state
				var next = state.duplicate(true)
				_event_choice(next, choice)
				return next
	if state.phase == "rest" and kind == "REST" and action.get("option", "") in ["heal", "meditate"]:
		var next = state.duplicate(true)
		if action.option == "heal":
			next.player.hp = mini(next.player.max_hp, next.player.hp + 22)
			next.player.sanity = mini(next.player.max_sanity, next.player.sanity + 2)
			_log(next, "Rest: recover 22 health and 2 sanity.")
		else:
			next.player.hp = mini(next.player.max_hp, next.player.hp + 6)
			next.player.sanity = next.player.max_sanity
			_log(next, "Meditation: recover 6 health and all sanity.")
		_advance_encounter(next)
		return next
	if state.phase == "relic" and kind == "CHOOSE_RELIC" and action.get("relic_id", "") in state.relic_rewards:
		var next = state.duplicate(true)
		_gain_relic(next, action.relic_id)
		next.player.hp = mini(next.player.max_hp, next.player.hp + 12)
		next.player.sanity = mini(next.player.max_sanity, next.player.sanity + 4)
		_advance_encounter(next)
		return next
	return state

static func _integer(value: Variant, minimum: int, maximum: int) -> bool:
	return (typeof(value) == TYPE_INT or typeof(value) == TYPE_FLOAT) and is_finite(float(value)) and float(value) == floor(float(value)) and value >= minimum and value <= maximum

static func _exact_keys(value: Variant, keys: Array) -> bool:
	if typeof(value) != TYPE_DICTIONARY or value.size() != keys.size():
		return false
	for key in keys:
		if not value.has(key):
			return false
	return true

static func _counts(ids: Array) -> Dictionary:
	var counts = {}
	for id in ids:
		counts[id] = counts.get(id, 0) + 1
	return counts

static func _ids(value: Variant, lookup: Dictionary, maximum: int) -> bool:
	if typeof(value) != TYPE_ARRAY or value.size() > maximum:
		return false
	for id in value:
		if typeof(id) != TYPE_STRING or not lookup.has(id):
			return false
	return true

static func validate_state(value: Variant) -> bool:
	if not _exact_keys(value, ["phase", "seed", "rng", "encounter", "pathway", "turn", "player", "enemy", "deck", "draw_pile", "hand", "discard_pile", "exhaust_pile", "powers", "rewards", "relics", "relic_rewards", "route_options", "event_id", "pending_enemy_id", "log"]):
		return false
	if value.phase not in ["combat", "reward", "route", "event", "rest", "relic", "victory", "defeat"] or not _integer(value.seed, 0, 0xffffffff) or not _integer(value.rng, 1, 0xffffffff) or not _integer(value.encounter, 0, 11) or not _integer(value.turn, 1, 10000) or typeof(value.pathway) != TYPE_STRING or not data().pathways_by_id.has(value.pathway) or value.pending_enemy_id != "":
		return false
	if not _exact_keys(value.player, ["hp", "max_hp", "block", "energy", "max_energy", "sanity", "max_sanity", "poison", "weak", "vulnerable"]) or not _exact_keys(value.powers, ["attack_bonus"]):
		return false
	var player: Dictionary = value.player
	if not _integer(player.max_hp, 30, 140) or player.max_energy != 3 or player.max_sanity != 12 or not _integer(player.hp, 0, player.max_hp) or not _integer(player.block, 0, 999) or not _integer(player.energy, 0, 10) or not _integer(player.sanity, 0, 12) or not _integer(value.powers.attack_bonus, 0, 30):
		return false
	if not _exact_keys(value.enemy, ["id", "name", "description", "hp", "max_hp", "block", "intent_index", "intent", "poison", "weak", "vulnerable"]) or typeof(value.enemy.id) != TYPE_STRING or not data().enemies_by_id.has(value.enemy.id):
		return false
	var template: Dictionary = data().enemies_by_id[value.enemy.id]
	var enemy: Dictionary = value.enemy
	if enemy.name != template.name or enemy.description != template.description or enemy.max_hp != template.max_hp or not _integer(enemy.hp, 0, template.max_hp) or not _integer(enemy.block, 0, 100) or not _integer(enemy.intent_index, 0, template.intents.size() - 1) or enemy.intent != template.intents[int(enemy.intent_index)]:
		return false
	if template.act != _act_number(value):
		return false
	for status in STATUS_KEYS:
		if not _integer(player[status], 0, 20) or not _integer(enemy[status], 0, 20):
			return false
	var pile = []
	for field in ["deck", "draw_pile", "hand", "discard_pile", "exhaust_pile", "rewards"]:
		if not _ids(value[field], data().cards_by_id, MAX_DECK):
			return false
		if field not in ["deck", "rewards"]:
			pile.append_array(value[field])
	if value.deck.size() < 5 or _counts(pile) != _counts(value.deck):
		return false
	if not _ids(value.relics, data().relics_by_id, 12) or _counts(value.relics).size() != value.relics.size() or not _ids(value.relic_rewards, data().relics_by_id, 3):
		return false
	if typeof(value.log) != TYPE_ARRAY or value.log.size() < 1 or value.log.size() > 40:
		return false
	for entry in value.log:
		if typeof(entry) != TYPE_STRING or entry.length() > 512:
			return false
	if typeof(value.route_options) != TYPE_ARRAY or value.route_options.size() > 2 or typeof(value.event_id) != TYPE_STRING:
		return false
	for route in value.route_options:
		if not _exact_keys(route, ["id", "kind", "label", "description", "enemy_id", "event_id"]):
			return false
		for key in route:
			if typeof(route[key]) != TYPE_STRING or route[key].length() > 512:
				return false
		if route.kind not in ["combat", "event", "rest"] or (route.kind == "combat" and not data().enemies_by_id.has(route.enemy_id)) or (route.kind == "event" and not data().events_by_id.has(route.event_id)):
			return false
	if value.phase != "route" and not value.route_options.is_empty():
		return false
	if value.phase != "relic" and not value.relic_rewards.is_empty():
		return false
	if value.phase != "reward" and not value.rewards.is_empty():
		return false
	if value.phase != "event" and value.event_id != "":
		return false
	if value.phase == "combat":
		return player.hp > 0 and enemy.hp > 0
	if value.phase == "defeat":
		return player.hp == 0
	if player.hp <= 0 or enemy.hp != 0:
		return false
	match value.phase:
		"victory": return value.encounter == 11
		"reward": return value.encounter % 4 != 3 and value.rewards.size() == 3 and _counts(value.rewards).size() == 3
		"route": return value.encounter % 4 != 3 and not value.route_options.is_empty()
		"event": return value.encounter % 4 == 1 and data().events_by_id.has(value.event_id)
		"rest": return value.encounter % 4 in [1, 2]
		"relic": return value.encounter % 4 == 3 and value.encounter < 11 and value.relic_rewards.size() > 0 and _counts(value.relic_rewards).size() == value.relic_rewards.size()
	return false

static func make_save(state: Dictionary) -> Dictionary:
	if not validate_state(state):
		return {}
	return {"schema_version":SAVE_VERSION, "engine":ENGINE_ID, "state":state.duplicate(true), "state_sha256":JSON.stringify(state).sha256_text()}

static func _normalize_numbers(value: Variant, depth: int = 0) -> Variant:
	if depth > 8:
		return value
	if typeof(value) == TYPE_FLOAT and is_finite(value) and value == floor(value):
		return int(value)
	if typeof(value) == TYPE_ARRAY:
		var result = []
		for child in value:
			result.append(_normalize_numbers(child, depth + 1))
		return result
	if typeof(value) == TYPE_DICTIONARY:
		var result = {}
		for key in value:
			result[key] = _normalize_numbers(value[key], depth + 1)
		return result
	return value

static func decode_save(envelope: Variant) -> Dictionary:
	if not _exact_keys(envelope, ["schema_version", "engine", "state", "state_sha256"]) or envelope.schema_version != SAVE_VERSION or envelope.engine != ENGINE_ID or typeof(envelope.state_sha256) != TYPE_STRING or typeof(envelope.state) != TYPE_DICTIONARY:
		return {}
	var normalized: Dictionary = _normalize_numbers(envelope.state)
	if not validate_state(normalized) or JSON.stringify(envelope).to_utf8_buffer().size() > MAX_SAVE_BYTES or JSON.stringify(normalized).sha256_text() != envelope.state_sha256:
		return {}
	return normalized
