extends Control
## Native Control UI. Every graphic below is authored procedural geometry.

const EngineRules = preload("res://scripts/game_engine.gd")
const CloudAdapter = preload("res://scripts/cloud_save.gd")
const INK = Color("071312")
const PANEL = Color("112624")
const GREEN = Color("9dd8ba")
const GOLD = Color("d6b676")
const TEXT = Color("e8ece0")
const MUTED = Color("9eafa5")
const RED = Color("ec998a")
const SAVE_PATH = "user://progress-v1.json"
var state: Dictionary = {}
var shell: VBoxContainer
var cloud: Node
var cloud_dialog: AcceptDialog
var cloud_status: Label
var cloud_email: LineEdit
var cloud_password: LineEdit
var cloud_snapshot: Dictionary = {}
var restore_confirmation: ConfirmationDialog
var status_message = "Your run is saved on this device after every action."
var local_save_ok = false
var cloud_busy = false

class Atmosphere extends Control:
	func _draw() -> void:
		draw_rect(Rect2(Vector2.ZERO, size), Color("071312"))
		var center = Vector2(size.x * 0.52, size.y * 0.39)
		for index in range(9, 0, -1):
			draw_circle(center, 30.0 + index * 36.0, Color(0.18, 0.40, 0.32, 0.018))
		for index in range(34):
			var point = Vector2(fmod(index * 211.0 + 79.0, size.x), fmod(index * 97.0 + 37.0, size.y))
			draw_circle(point, 1.0 + float(index % 3) * 0.35, Color(0.75, 0.72, 0.48, 0.18))
		draw_line(Vector2(24, 16), Vector2(size.x - 24, 16), Color(0.70, 0.62, 0.37, 0.30), 1)
		draw_line(Vector2(24, size.y - 16), Vector2(size.x - 24, size.y - 16), Color(0.70, 0.62, 0.37, 0.30), 1)

class Sigil extends Control:
	var kind = "skill"
	func _draw() -> void:
		var center = size * 0.5
		var radius = minf(size.x, size.y) * 0.35
		var color = Color("d6b676") if kind == "power" else Color("ec998a") if kind == "attack" else Color("9dd8ba")
		draw_arc(center, radius, 0, TAU, 48, Color(color, 0.30), 1.5, true)
		draw_arc(center, radius * 0.72, 0, TAU, 40, Color(color, 0.20), 1.0, true)
		if kind == "attack":
			draw_line(center + Vector2(-radius * 0.45, radius * 0.60), center + Vector2(radius * 0.45, -radius * 0.60), color, 3, true)
			draw_line(center + Vector2(-radius * 0.36, radius * 0.05), center + Vector2(radius * 0.17, radius * 0.38), color, 3, true)
		elif kind == "power":
			for index in range(6):
				var direction = Vector2.from_angle(index * TAU / 6)
				draw_line(center + direction * radius * 0.35, center + direction * radius * 0.82, color, 2, true)
			draw_circle(center, radius * 0.21, Color(color, 0.50))
		else:
			var points = PackedVector2Array([center + Vector2(0, -radius * 0.70), center + Vector2(radius * 0.48, -radius * 0.35), center + Vector2(radius * 0.38, radius * 0.37), center + Vector2(0, radius * 0.70), center + Vector2(-radius * 0.38, radius * 0.37), center + Vector2(-radius * 0.48, -radius * 0.35), center + Vector2(0, -radius * 0.70)])
			draw_polyline(points, color, 2.5, true)

class EnemyPortrait extends Control:
	var encounter = 0
	func _draw() -> void:
		var center = Vector2(size.x * 0.5, size.y * 0.50)
		var radius = minf(size.x * 0.25, size.y * 0.40)
		var glow = Color("9dd8ba") if encounter == 0 else Color("d6b676") if encounter == 1 else Color("bca6dc")
		for index in range(6, 0, -1):
			draw_circle(center, radius + index * 6, Color(glow, 0.020))
		draw_arc(center, radius + 8, 0, TAU, 80, Color(glow, 0.35), 1.5, true)
		draw_arc(center, radius + 18, 0.3, 5.6, 70, Color(glow, 0.19), 1, true)
		for index in range(12):
			var direction = Vector2.from_angle(index * TAU / 12)
			draw_line(center + direction * (radius + 12), center + direction * (radius + 20), Color(glow, 0.60), 1.5, true)
		var cloak = PackedVector2Array([center + Vector2(-radius * 0.75, radius * 0.83), center + Vector2(-radius * 0.47, -radius * 0.1), center + Vector2(-radius * 0.30, -radius * 0.60), center + Vector2(0, -radius * 0.85), center + Vector2(radius * 0.30, -radius * 0.60), center + Vector2(radius * 0.47, -radius * 0.1), center + Vector2(radius * 0.75, radius * 0.83)])
		draw_colored_polygon(cloak, Color("172d2b"))
		draw_polyline(cloak, Color(glow, 0.70), 2, true)
		draw_line(center + Vector2(-radius * 0.2, -radius * 0.30), center + Vector2(radius * 0.2, -radius * 0.30), glow, 3, true)
		if encounter == 1:
			draw_arc(center + Vector2(0, radius * 0.35), radius * 0.2, PI, TAU, 24, glow, 2, true)
			draw_line(center + Vector2(-radius * 0.2, radius * 0.35), center + Vector2(radius * 0.2, radius * 0.35), glow, 2, true)
		elif encounter == 2:
			for index in range(3):
				draw_line(center + Vector2(-radius * 0.24, radius * (0.12 + index * 0.14)), center + Vector2(radius * 0.24, radius * (0.12 + index * 0.14)), Color(glow, 0.65), 2, true)
		else:
			draw_circle(center + Vector2(0, radius * 0.28), radius * 0.10, glow)

func _ready() -> void:
	_setup_theme()
	var background = Atmosphere.new()
	background.name = "Atmosphere"
	background.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	background.mouse_filter = Control.MOUSE_FILTER_IGNORE
	background.resized.connect(background.queue_redraw)
	add_child(background)
	var margin = MarginContainer.new()
	margin.name = "SafeFrame"
	margin.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	for side in ["left", "top", "right", "bottom"]:
		margin.add_theme_constant_override("margin_" + side, 20 if side in ["top", "bottom"] else 24)
	add_child(margin)
	shell = VBoxContainer.new()
	shell.add_theme_constant_override("separation", 10)
	margin.add_child(shell)
	state = _read_local()
	if state.is_empty():
		state = EngineRules.create_run(123)
	else:
		status_message = "Resumed your saved run. Play offline whenever you like."
	_save_local()
	cloud = CloudAdapter.new()
	cloud.name = "CloudSave"
	add_child(cloud)
	cloud.result.connect(_cloud_result)
	cloud.configure_from_file()
	_render()

func _notification(what: int) -> void:
	if what == NOTIFICATION_APPLICATION_PAUSED and not state.is_empty():
		_save_local()

func _setup_theme() -> void:
	var ui_theme = Theme.new()
	ui_theme.default_font_size = 22
	ui_theme.set_color("font_color", "Label", TEXT)
	ui_theme.set_color("font_color", "Button", TEXT)
	ui_theme.set_color("font_disabled_color", "Button", MUTED)
	ui_theme.set_color("font_color", "LineEdit", TEXT)
	ui_theme.set_stylebox("normal", "Button", _box(PANEL, Color("45635a"), 12, 1))
	ui_theme.set_stylebox("hover", "Button", _box(Color("244337"), GREEN, 12, 2))
	ui_theme.set_stylebox("pressed", "Button", _box(Color("325a43"), GOLD, 12, 2))
	ui_theme.set_stylebox("focus", "Button", _box(Color(0, 0, 0, 0), GOLD, 12, 2))
	ui_theme.set_stylebox("disabled", "Button", _box(Color("152522"), Color("304239"), 12, 1))
	ui_theme.set_stylebox("normal", "LineEdit", _box(INK, Color("45635a"), 8, 1))
	ui_theme.set_stylebox("focus", "LineEdit", _box(INK, GOLD, 8, 2))
	ui_theme.set_stylebox("panel", "AcceptDialog", _box(INK, GOLD, 16, 2))
	ui_theme.set_color("title_color", "Window", TEXT)
	theme = ui_theme

func _box(fill: Color, edge: Color, radius: int = 12, border: int = 1) -> StyleBoxFlat:
	var style = StyleBoxFlat.new()
	style.bg_color = fill
	style.border_color = edge
	style.set_border_width_all(border)
	style.set_corner_radius_all(radius)
	style.content_margin_left = 16
	style.content_margin_right = 16
	style.content_margin_top = 10
	style.content_margin_bottom = 10
	return style

func _label(text_value: String, font_size: int = 22, color: Color = TEXT) -> Label:
	var label = Label.new()
	label.text = text_value
	label.add_theme_font_size_override("font_size", font_size)
	label.add_theme_color_override("font_color", color)
	label.mouse_filter = Control.MOUSE_FILTER_IGNORE
	return label

func _button(text_value: String, callback: Callable, width: int = 140) -> Button:
	var button = Button.new()
	button.text = text_value
	button.custom_minimum_size = Vector2(width, 72)
	button.pressed.connect(callback)
	return button

func _render() -> void:
	for child in shell.get_children():
		shell.remove_child(child)
		child.queue_free()
	_render_header()
	_render_stats()
	_render_encounter()
	_render_cards()
	_render_footer()

func _render_header() -> void:
	var row = HBoxContainer.new()
	row.add_theme_constant_override("separation", 12)
	shell.add_child(row)
	var title = VBoxContainer.new()
	title.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	row.add_child(title)
	title.add_child(_label("BEYOND THE GRAY FOG", 29, GOLD))
	var path: Dictionary = EngineRules.data().pathways_by_id[state.pathway]
	title.add_child(_label("%s  /  ACT %d  /  %d OF 12  /  SEED %d" % [path.name.to_upper(), int(state.encounter / 4) + 1, state.encounter + 1, state.seed], 16, MUTED))
	var deck_button = _button("Deck %d" % state.deck.size(), _show_deck, 130)
	deck_button.name = "DeckButton"
	row.add_child(deck_button)
	var relic_button = _button("Relics %d" % state.relics.size(), _show_relics, 125)
	relic_button.name = "RelicsButton"
	row.add_child(relic_button)
	var cloud_button = _button("Cloud", _show_cloud, 116)
	cloud_button.name = "CloudButton"
	row.add_child(cloud_button)
	var new_button = _button("New run", _confirm_new_run, 144)
	new_button.name = "NewRun"
	row.add_child(new_button)

func _render_stats() -> void:
	var row = HBoxContainer.new()
	row.add_theme_constant_override("separation", 12)
	shell.add_child(row)
	var stats = [
		["HEALTH", "%d / %d" % [state.player.hp, state.player.max_hp], RED],
		["SANITY", "%d / %d" % [state.player.sanity, state.player.max_sanity], GREEN],
		["ENERGY", "%d / %d" % [state.player.energy, state.player.max_energy], GOLD],
		["BLOCK", str(state.player.block), GREEN],
	]
	for stat in stats:
		var panel = PanelContainer.new()
		panel.size_flags_horizontal = Control.SIZE_EXPAND_FILL
		panel.add_theme_stylebox_override("panel", _box(Color("10221f"), Color("2e4b3e"), 10))
		row.add_child(panel)
		var content = HBoxContainer.new()
		content.add_theme_constant_override("separation", 20)
		panel.add_child(content)
		var name_label = _label(stat[0], 17, MUTED)
		name_label.size_flags_horizontal = Control.SIZE_EXPAND_FILL
		content.add_child(name_label)
		content.add_child(_label(stat[1], 26, stat[2]))

func _render_encounter() -> void:
	var panel = PanelContainer.new()
	panel.name = "Encounter"
	panel.custom_minimum_size.y = 166
	panel.size_flags_vertical = Control.SIZE_EXPAND_FILL
	panel.add_theme_stylebox_override("panel", _box(Color(0.055, 0.11, 0.105, 0.92), Color("2e4b3e"), 16))
	shell.add_child(panel)
	var row = HBoxContainer.new()
	row.add_theme_constant_override("separation", 20)
	panel.add_child(row)
	var left = VBoxContainer.new()
	left.custom_minimum_size.x = 300
	left.alignment = BoxContainer.ALIGNMENT_CENTER
	row.add_child(left)
	left.add_child(_label("TURN %d" % state.turn, 17, MUTED))
	left.add_child(_label(state.enemy.name, 26, GOLD))
	var description = _label(state.enemy.description, 17, MUTED)
	description.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	description.custom_minimum_size.x = 300
	left.add_child(description)
	var player_status = _status_text(state.player)
	if not player_status.is_empty():
		left.add_child(_label("YOU: " + player_status, 16, RED))
	var portrait = EnemyPortrait.new()
	portrait.name = "EnemyPortrait"
	portrait.encounter = int(state.encounter / 4)
	portrait.custom_minimum_size = Vector2(210, 130)
	portrait.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	portrait.mouse_filter = Control.MOUSE_FILTER_IGNORE
	portrait.resized.connect(portrait.queue_redraw)
	row.add_child(portrait)
	var right = VBoxContainer.new()
	right.custom_minimum_size.x = 290
	right.alignment = BoxContainer.ALIGNMENT_CENTER
	row.add_child(right)
	var hp_label = _label("%d / %d HP    |    %d BLOCK" % [state.enemy.hp, state.enemy.max_hp, state.enemy.block], 23, TEXT)
	right.add_child(hp_label)
	var bar = ProgressBar.new()
	bar.custom_minimum_size.y = 12
	bar.max_value = state.enemy.max_hp
	bar.value = state.enemy.hp
	bar.show_percentage = false
	bar.add_theme_stylebox_override("background", _box(INK, INK, 6, 0))
	bar.add_theme_stylebox_override("fill", _box(RED, RED, 6, 0))
	right.add_child(bar)
	if state.phase == "combat":
		var attack = state.enemy.intent.kind == "attack"
		var intent_name = {"attack":"ATTACK", "defend":"BLOCK", "poison":"POISON", "weaken":"WEAK"}[state.enemy.intent.kind]
		right.add_child(_label("NEXT: %s %d" % [intent_name, state.enemy.intent.value], 25, RED if attack else GREEN))
		var predicted = EngineRules._attack_damage(state.enemy.intent.value, state.enemy, state.player)
		var advice = "After your block: %d damage" % maxi(0, predicted - state.player.block) if attack else "Poison bypasses block; Weak lowers attacks" if state.enemy.intent.kind in ["poison", "weaken"] else "Defense lasts through your next turn"
		var advice_label = _label(advice, 16, MUTED)
		advice_label.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
		right.add_child(advice_label)
		var enemy_status = _status_text(state.enemy)
		if not enemy_status.is_empty():
			right.add_child(_label(enemy_status, 16, GREEN))
		if state.player.sanity == 0:
			right.add_child(_label("Zero sanity: also lose 3 HP", 18, RED))
	else:
		var phase_names = {"reward":"ENCOUNTER CLEARED", "route":"THE ROUTE FORKS", "event":"A STRANGE ENCOUNTER", "rest":"A MOMENT OF QUIET", "relic":"THE ACT IS CLEARED", "victory":"YOUR OWN ENDING", "defeat":"THE ARCHIVE CLOSES"}
		right.add_child(_label(phase_names[state.phase], 24, GOLD))
		right.add_child(_label("Choose what comes next below" if state.phase not in ["victory", "defeat"] else "A new run waits beyond the fog", 17, MUTED))

func _status_text(target: Dictionary) -> String:
	var labels = []
	for key in ["poison", "weak", "vulnerable"]:
		if target[key] > 0:
			labels.append("%s %d" % [key.capitalize(), target[key]])
	return " · ".join(labels)

func _render_cards() -> void:
	if state.phase in ["route", "event", "rest", "relic"]:
		_render_decisions()
		return
	var heading = HBoxContainer.new()
	shell.add_child(heading)
	var instruction = "YOUR HAND  /  TAP A CARD TO PLAY" if state.phase == "combat" else "CHOOSE ONE  /  THEN RECOVER 4 HP + 2 SANITY" if state.phase == "reward" else "RUN COMPLETE"
	var title = _label(instruction, 17, GREEN)
	title.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	heading.add_child(title)
	heading.add_child(_label("DRAW %d  ·  DISCARD %d  ·  EXHAUST %d" % [state.draw_pile.size(), state.discard_pile.size(), state.exhaust_pile.size()], 17, MUTED))
	if state.phase in ["victory", "defeat"]:
		var ending = PanelContainer.new()
		ending.custom_minimum_size.y = 230
		ending.add_theme_stylebox_override("panel", _box(PANEL, GOLD, 12))
		shell.add_child(ending)
		var content = VBoxContainer.new()
		content.alignment = BoxContainer.ALIGNMENT_CENTER
		ending.add_child(content)
		var text_value = "You leave the archive with your own ending." if state.phase == "victory" else "The ink settles. Your next attempt may tell a different story."
		var message = _label(text_value, 30, GOLD)
		message.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
		content.add_child(message)
		var restart = _button("Begin a new run", _new_run, 230)
		restart.name = "Restart"
		restart.size_flags_horizontal = Control.SIZE_SHRINK_CENTER
		content.add_child(restart)
		return
	var scroll = ScrollContainer.new()
	scroll.name = "HandScroll"
	scroll.custom_minimum_size.y = 242
	scroll.horizontal_scroll_mode = ScrollContainer.SCROLL_MODE_AUTO
	scroll.vertical_scroll_mode = ScrollContainer.SCROLL_MODE_DISABLED
	shell.add_child(scroll)
	var row = HBoxContainer.new()
	row.name = "Cards"
	row.add_theme_constant_override("separation", 12)
	row.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	scroll.add_child(row)
	var ids: Array = state.hand if state.phase == "combat" else state.rewards
	for index in range(ids.size()):
		var card: Dictionary = EngineRules.get_card(ids[index])
		var button = Button.new()
		button.name = "Card%d" % index
		button.custom_minimum_size = Vector2(224 if state.phase == "combat" else 300, 228)
		button.size_flags_horizontal = Control.SIZE_EXPAND_FILL
		button.disabled = state.phase == "combat" and card.cost > state.player.energy
		button.pressed.connect(_dispatch.bind({"type":"PLAY_CARD", "index":index} if state.phase == "combat" else {"type":"CHOOSE_REWARD", "card_id":card.id}))
		row.add_child(button)
		var margin = MarginContainer.new()
		margin.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
		margin.mouse_filter = Control.MOUSE_FILTER_IGNORE
		for side in ["left", "right", "top", "bottom"]:
			margin.add_theme_constant_override("margin_" + side, 12)
		button.add_child(margin)
		var body = VBoxContainer.new()
		body.mouse_filter = Control.MOUSE_FILTER_IGNORE
		body.add_theme_constant_override("separation", 5)
		margin.add_child(body)
		var top = HBoxContainer.new()
		top.mouse_filter = Control.MOUSE_FILTER_IGNORE
		body.add_child(top)
		var category = _label(card.type.to_upper(), 14, MUTED)
		category.size_flags_horizontal = Control.SIZE_EXPAND_FILL
		top.add_child(category)
		top.add_child(_label(str(card.cost) + " E", 24, GOLD))
		var emblem = Sigil.new()
		emblem.kind = card.type
		emblem.custom_minimum_size.y = 30
		emblem.mouse_filter = Control.MOUSE_FILTER_IGNORE
		emblem.resized.connect(emblem.queue_redraw)
		body.add_child(emblem)
		var title_label = _label(card.name, 20, TEXT if not button.disabled else MUTED)
		title_label.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
		title_label.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
		body.add_child(title_label)
		var effect = _label(card.description.replace("\n", " "), 17, MUTED if button.disabled else RED if card.get("sanity_cost", 0) > 0 else GREEN)
		effect.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
		effect.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
		effect.size_flags_vertical = Control.SIZE_EXPAND_FILL
		body.add_child(effect)

func _render_decisions() -> void:
	var heading = {"route":"CHOOSE YOUR ROUTE", "event":"A CHOICE WITH A PRICE", "rest":"RECOVER BEFORE THE NEXT BATTLE", "relic":"CHOOSE ONE LASTING RELIC"}[state.phase]
	shell.add_child(_label(heading, 17, GREEN))
	var row = HBoxContainer.new()
	row.name = "Decisions"
	row.custom_minimum_size.y = 242
	row.add_theme_constant_override("separation", 16)
	shell.add_child(row)
	if state.phase == "route":
		for index in range(state.route_options.size()):
			var route: Dictionary = state.route_options[index]
			_decision(row, "Route%d" % index, route.label, route.description, route.kind.to_upper(), {"type":"CHOOSE_ROUTE", "route_id":route.id})
	elif state.phase == "event":
		var event: Dictionary = EngineRules.get_event(state.event_id)
		for index in range(event.choices.size()):
			var choice: Dictionary = event.choices[index]
			var already_owned: bool = choice.effects.get("gain_relic", "") in state.relics
			_decision(row, "EventChoice%d" % index, choice.label, event.description + "\n\n" + choice.description, "ALREADY OWNED" if already_owned else event.name.to_upper(), {"type":"CHOOSE_EVENT", "choice_id":choice.id}, already_owned)
	elif state.phase == "rest":
		_decision(row, "RestHeal", "Tend your wounds", "Recover 22 health and 2 sanity.\nThen continue to the next encounter.", "REST", {"type":"REST", "option":"heal"})
		_decision(row, "RestMeditate", "Steady your mind", "Recover 6 health and all sanity.\nThen continue to the next encounter.", "MEDITATE", {"type":"REST", "option":"meditate"})
	else:
		for index in range(state.relic_rewards.size()):
			var relic: Dictionary = EngineRules.get_relic(state.relic_rewards[index])
			_decision(row, "Relic%d" % index, relic.name, relic.description + "\n\nRecover 12 HP and 4 sanity before the next act.", "RELIC", {"type":"CHOOSE_RELIC", "relic_id":relic.id})

func _decision(row: HBoxContainer, node_name: String, title: String, description: String, category: String, action: Dictionary, disabled: bool = false) -> void:
	var button = Button.new()
	button.name = node_name
	button.disabled = disabled
	button.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	button.custom_minimum_size = Vector2(280, 228)
	button.pressed.connect(_dispatch.bind(action))
	row.add_child(button)
	var margin = MarginContainer.new()
	margin.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	margin.mouse_filter = Control.MOUSE_FILTER_IGNORE
	for side in ["left", "right", "top", "bottom"]:
		margin.add_theme_constant_override("margin_" + side, 20)
	button.add_child(margin)
	var body = VBoxContainer.new()
	body.mouse_filter = Control.MOUSE_FILTER_IGNORE
	body.add_theme_constant_override("separation", 10)
	margin.add_child(body)
	body.add_child(_label(category, 15, MUTED))
	var title_label = _label(title, 26, MUTED if disabled else GOLD)
	title_label.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	body.add_child(title_label)
	var text_label = _label(description, 17, MUTED if disabled else GREEN)
	text_label.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	text_label.size_flags_vertical = Control.SIZE_EXPAND_FILL
	body.add_child(text_label)

func _render_footer() -> void:
	var row = HBoxContainer.new()
	row.add_theme_constant_override("separation", 20)
	shell.add_child(row)
	var log_area = VBoxContainer.new()
	log_area.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	row.add_child(log_area)
	var recent = _label(state.log[-1], 19, TEXT)
	recent.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	log_area.add_child(recent)
	log_area.add_child(_label("SAVED ON DEVICE  ·  ORIGINAL DESIGN" if local_save_ok else "SAVE UNAVAILABLE — KEEP APP OPEN", 14, MUTED if local_save_ok else RED))
	var end_button = _button("Skip reward  →" if state.phase == "reward" else "End turn  →", _dispatch.bind({"type":"SKIP_REWARD"} if state.phase == "reward" else {"type":"END_TURN"}), 220)
	end_button.name = "SkipReward" if state.phase == "reward" else "EndTurn"
	end_button.disabled = state.phase not in ["combat", "reward"]
	end_button.add_theme_stylebox_override("normal", _box(Color("365842"), GOLD, 12, 1))
	row.add_child(end_button)

func _dispatch(action: Dictionary) -> void:
	var next = EngineRules.act(state, action)
	if next == state:
		return
	state = next
	_save_local()
	_render.call_deferred()

func _new_run(pathway: String = "") -> void:
	state = EngineRules.create_run((state.seed + 1) & 0xffffffff, state.pathway if pathway.is_empty() else pathway)
	_save_local()
	_render.call_deferred()

func _confirm_new_run() -> void:
	var dialog = ConfirmationDialog.new()
	dialog.title = "Start a new run?"
	dialog.dialog_text = "Your current run will be replaced on this device."
	dialog.get_ok_button().text = "Start new run"
	dialog.get_ok_button().custom_minimum_size.y = 72
	dialog.get_cancel_button().custom_minimum_size.y = 72
	dialog.confirmed.connect(_show_pathways.call_deferred)
	dialog.visibility_changed.connect(func():
		if not dialog.visible:
			dialog.queue_free())
	add_child(dialog)
	dialog.popup_centered(Vector2i(580, 200))

func _show_pathways() -> void:
	var dialog = AcceptDialog.new()
	dialog.title = "Choose a pathway · original adaptation"
	dialog.get_ok_button().text = "Keep current run"
	dialog.get_ok_button().custom_minimum_size.y = 72
	var row = HBoxContainer.new()
	row.custom_minimum_size = Vector2(1000, 270)
	row.add_theme_constant_override("separation", 16)
	dialog.add_child(row)
	for path in EngineRules.pathways():
		var button = Button.new()
		button.name = "Pathway_" + path.id
		button.size_flags_horizontal = Control.SIZE_EXPAND_FILL
		button.custom_minimum_size = Vector2(310, 260)
		button.pressed.connect(func():
			_new_run(path.id)
			dialog.hide())
		row.add_child(button)
		var margin = MarginContainer.new()
		margin.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
		margin.mouse_filter = Control.MOUSE_FILTER_IGNORE
		for side in ["left", "right", "top", "bottom"]:
			margin.add_theme_constant_override("margin_" + side, 18)
		button.add_child(margin)
		var body = VBoxContainer.new()
		body.mouse_filter = Control.MOUSE_FILTER_IGNORE
		body.add_theme_constant_override("separation", 12)
		margin.add_child(body)
		body.add_child(_label(path.name, 31, GOLD))
		var subtitle = _label(path.subtitle, 18, GREEN)
		subtitle.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
		body.add_child(subtitle)
		var description = _label(path.description, 18, MUTED)
		description.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
		body.add_child(description)
	dialog.visibility_changed.connect(func():
		if not dialog.visible:
			dialog.queue_free())
	add_child(dialog)
	dialog.popup_centered(Vector2i(1050, 420))

func _show_relics() -> void:
	var dialog = AcceptDialog.new()
	dialog.title = "Your relics · lasting effects"
	dialog.get_ok_button().custom_minimum_size.y = 72
	var scroll = ScrollContainer.new()
	scroll.custom_minimum_size = Vector2(640, 350)
	dialog.add_child(scroll)
	var body = VBoxContainer.new()
	body.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	body.add_theme_constant_override("separation", 14)
	scroll.add_child(body)
	for id in state.relics:
		var relic = EngineRules.get_relic(id)
		body.add_child(_label(relic.name, 25, GOLD))
		var description = _label(relic.description, 20, GREEN)
		description.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
		body.add_child(description)
	dialog.visibility_changed.connect(func():
		if not dialog.visible:
			dialog.queue_free())
	add_child(dialog)
	dialog.popup_centered(Vector2i(700, 470))

func _save_local() -> void:
	local_save_ok = false
	var envelope = EngineRules.make_save(state)
	if envelope.is_empty():
		return
	var file = FileAccess.open(SAVE_PATH + ".tmp", FileAccess.WRITE)
	if file == null:
		return
	file.store_string(JSON.stringify(envelope))
	file.flush()
	var write_error = file.get_error()
	file.close()
	if write_error != OK:
		return
	local_save_ok = DirAccess.rename_absolute(SAVE_PATH + ".tmp", SAVE_PATH) == OK

func _read_local() -> Dictionary:
	if not FileAccess.file_exists(SAVE_PATH):
		return {}
	var file = FileAccess.open(SAVE_PATH, FileAccess.READ)
	if file == null or file.get_length() > EngineRules.MAX_SAVE_BYTES:
		return {}
	var envelope = JSON.parse_string(file.get_as_text())
	file.close()
	return EngineRules.decode_save(envelope)

func _show_deck() -> void:
	var dialog = AcceptDialog.new()
	dialog.title = "Your deck · %d cards" % state.deck.size()
	dialog.get_ok_button().custom_minimum_size.y = 72
	var scroll = ScrollContainer.new()
	scroll.custom_minimum_size = Vector2(640, 430)
	dialog.add_child(scroll)
	var list = VBoxContainer.new()
	list.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	list.add_theme_constant_override("separation", 12)
	scroll.add_child(list)
	var counts = {}
	for id in state.deck:
		counts[id] = counts.get(id, 0) + 1
	for id in counts:
		var card = EngineRules.get_card(id)
		list.add_child(_label("%d × %s   ·   %d energy" % [counts[id], card.name, card.cost], 24, GOLD))
		list.add_child(_label(card.description.replace("\n", " "), 19, GREEN))
	dialog.visibility_changed.connect(func():
		if not dialog.visible:
			dialog.queue_free())
	add_child(dialog)
	dialog.popup_centered(Vector2i(700, 550))

func _show_cloud() -> void:
	if is_instance_valid(cloud_dialog):
		cloud_dialog.popup_centered()
		return
	cloud_dialog = AcceptDialog.new()
	cloud_dialog.title = "Cloud backup · optional"
	cloud_dialog.get_ok_button().text = "Return to game"
	cloud_dialog.get_ok_button().custom_minimum_size.y = 72
	var layout = VBoxContainer.new()
	layout.custom_minimum_size = Vector2(660, 410)
	layout.add_theme_constant_override("separation", 10)
	cloud_dialog.add_child(layout)
	cloud_status = _label("Play offline without an account. Email login can restore across devices.", 19, GREEN)
	cloud_status.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	cloud_status.custom_minimum_size.x = 630
	layout.add_child(cloud_status)
	cloud_email = LineEdit.new()
	cloud_email.placeholder_text = "Email for cross-device recovery"
	cloud_email.custom_minimum_size.y = 72
	layout.add_child(cloud_email)
	cloud_password = LineEdit.new()
	cloud_password.placeholder_text = "Password (at least 8 characters)"
	cloud_password.secret = true
	cloud_password.custom_minimum_size.y = 72
	layout.add_child(cloud_password)
	var account_row = HBoxContainer.new()
	layout.add_child(account_row)
	account_row.add_child(_button("Guest", _cloud_guest, 145))
	account_row.add_child(_button("Log in", _cloud_login, 145))
	account_row.add_child(_button("Register", _cloud_register, 145))
	account_row.add_child(_button("Sign out", _cloud_logout, 145))
	var saves_row = HBoxContainer.new()
	layout.add_child(saves_row)
	saves_row.add_child(_button("Check cloud", _cloud_check, 190))
	saves_row.add_child(_button("Back up run", _cloud_upload, 190))
	saves_row.add_child(_button("Restore run", _cloud_restore, 190))
	var notice = _label("Guest saves belong to this device's session. Register an email before changing devices.\nRestore only replaces this local run when you confirm.", 17, MUTED)
	notice.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	layout.add_child(notice)
	add_child(cloud_dialog)
	if not cloud.configured:
		cloud_status.text = "Cloud backup is unavailable in this build. Your game and device save work offline."
		for row in [account_row, saves_row]:
			for button in row.get_children():
				button.disabled = true
	cloud_dialog.popup_centered(Vector2i(720, 560))

func _cloud_guest() -> void:
	_invalidate_cloud_snapshot()
	cloud_busy = true
	cloud.sign_in_guest()

func _cloud_login() -> void:
	_invalidate_cloud_snapshot()
	cloud_busy = true
	cloud.login(cloud_email.text.strip_edges(), cloud_password.text)
	cloud_password.clear()

func _cloud_register() -> void:
	_invalidate_cloud_snapshot()
	cloud_busy = true
	cloud.register(cloud_email.text.strip_edges(), cloud_password.text)
	cloud_password.clear()

func _cloud_logout() -> void:
	_invalidate_cloud_snapshot()
	cloud.sign_out()

func _cloud_check() -> void:
	_invalidate_cloud_snapshot()
	cloud.download_save()

func _cloud_upload() -> void:
	_invalidate_cloud_snapshot()
	cloud.upload_save(EngineRules.make_save(state))

func _cloud_restore() -> void:
	var restored = EngineRules.decode_save(cloud_snapshot)
	if restored.is_empty():
		cloud_status.text = "Check cloud first. A compatible saved run must be present to restore."
		return
	var dialog = ConfirmationDialog.new()
	restore_confirmation = dialog
	dialog.title = "Restore the cloud run?"
	dialog.dialog_text = "This replaces the run saved on this device."
	dialog.get_ok_button().text = "Restore cloud run"
	dialog.get_ok_button().custom_minimum_size.y = 72
	dialog.get_cancel_button().custom_minimum_size.y = 72
	dialog.confirmed.connect(func():
		state = restored
		_save_local()
		_render()
		cloud_status.text = "Cloud run restored and saved on this device.")
	dialog.visibility_changed.connect(func():
		if not dialog.visible:
			dialog.queue_free())
	cloud_dialog.add_child(dialog)
	dialog.popup_centered(Vector2i(580, 200))

func _invalidate_cloud_snapshot() -> void:
	cloud_snapshot = {}
	if is_instance_valid(restore_confirmation):
		restore_confirmation.hide()
		restore_confirmation.queue_free()
	restore_confirmation = null

func _cloud_result(operation: String, ok: bool, payload: Dictionary) -> void:
	cloud_busy = false
	status_message = payload.get("message", "Cloud request completed." if ok else "Cloud request failed. Your local run is preserved.")
	if is_instance_valid(cloud_status):
		cloud_status.text = status_message
	if not ok:
		_invalidate_cloud_snapshot()
		return
	if operation in ["login", "sign_in_guest", "register"] and cloud.is_authenticated():
		_invalidate_cloud_snapshot()
		cloud.download_save()
	if operation == "download_save":
		_invalidate_cloud_snapshot()
		var received = payload.get("save_envelope", {})
		if payload.get("has_save", false) and not EngineRules.decode_save(received).is_empty():
			cloud_snapshot = received
		elif payload.get("has_save", false):
			if is_instance_valid(cloud_status):
				cloud_status.text = "Cloud save is incompatible or invalid. Local progress was preserved."
