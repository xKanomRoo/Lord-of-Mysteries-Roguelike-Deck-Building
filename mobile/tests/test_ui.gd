extends SceneTree
## Native Control interaction/layout smoke. No browser or remote server is used.
## A screenshot is captured only with a real renderer, never in headless mode.

const Rules = preload("res://scripts/game_engine.gd")
var ui: Control
var checks := 0
var failures := 0
var input_actions := 0
var touch_actions := 0
var screenshots: Array = []
var screenshot_dir := ""
var phases_seen: Dictionary = {}
var encounters_seen: Array = []
var event_choices_measured := 0
var relic_choices_measured := 0
var source_hashes: Dictionary = {}


func _initialize() -> void:
	for argument in OS.get_cmdline_user_args():
		if argument.begins_with("--screenshot-dir="):
			screenshot_dir = argument.trim_prefix("--screenshot-dir=")
	_run.call_deferred()


func _check(condition: bool, message: String) -> void:
	checks += 1
	if not condition:
		failures += 1
		printerr("FAIL: " + message)


func _frames(count: int = 3) -> void:
	for _index in range(count):
		await process_frame


func _button(name_value: String) -> Button:
	var found = ui.find_child(name_value, true, false)
	_check(found is Button, "native button exists: " + name_value)
	return found as Button


func _click(button: Button) -> void:
	if button == null:
		return
	var center := button.get_global_rect().get_center()
	var viewport := button.get_viewport()
	# Embedded dialogs receive pointer events through their owning viewport.
	# Their child Control coordinates are local to the dialog, not the game.
	while viewport is Window and viewport != root and viewport.is_embedded():
		center += Vector2(viewport.position)
		viewport = viewport.get_parent().get_viewport()
	var press := InputEventMouseButton.new()
	press.button_index = MOUSE_BUTTON_LEFT
	press.position = center
	press.global_position = center
	press.pressed = true
	viewport.push_input(press, true)
	await process_frame
	var release := InputEventMouseButton.new()
	release.button_index = MOUSE_BUTTON_LEFT
	release.position = center
	release.global_position = center
	release.pressed = false
	viewport.push_input(release, true)
	input_actions += 1
	await _frames()


func _tap(button: Button) -> void:
	if button == null:
		return
	var center := button.get_global_rect().get_center()
	var press := InputEventScreenTouch.new()
	press.index = 0
	press.position = center
	press.pressed = true
	Input.parse_input_event(press)
	await process_frame
	var release := InputEventScreenTouch.new()
	release.index = 0
	release.position = center
	release.pressed = false
	Input.parse_input_event(release)
	touch_actions += 1
	await _frames()


func _reset(seed_value: int = 123, pathway: String = "seer") -> void:
	ui.state = Rules.create_run(seed_value, pathway)
	ui._save_local()
	ui._render()
	await _frames()


func _layout(label_value: String) -> void:
	var viewport := root.get_visible_rect()
	for button_name in ["DeckButton", "RelicsButton", "CloudButton", "NewRun", "EndTurn"]:
		var button := _button(button_name)
		if button == null:
			continue
		var bounds := button.get_global_rect()
		_check(viewport.encloses(bounds), "%s: %s stays inside logical viewport" % [label_value, button_name])
		_check(bounds.size.x >= 72 and bounds.size.y >= 72, "%s: %s has a 72-unit touch target" % [label_value, button_name])
		_check(button.get_theme_font_size("font_size") >= 20, "%s: %s text remains readable" % [label_value, button_name])
	var scroll = ui.find_child("HandScroll", true, false) as ScrollContainer
	_check(scroll != null and viewport.encloses(scroll.get_global_rect()), label_value + ": hand stays in viewport")
	if scroll != null:
		var first_card := _button("Card0")
		_check(first_card != null and first_card.size.x >= 192 and first_card.size.y >= 228, label_value + ": card touch surface remains large")
		if first_card != null:
			_check(scroll.get_global_rect().has_point(first_card.get_global_rect().get_center()), label_value + ": first card is reachable")
		_check_card_labels(label_value)


func _check_card_labels(label_value: String) -> void:
	var cards = ui.find_child("Cards", true, false)
	_check(cards != null, label_value + ": card presentation exists")
	if cards == null:
		return
	for card in cards.get_children():
		for label in card.find_children("*", "Label", true, false):
			_check(card.get_global_rect().encloses(label.get_global_rect()), "%s: %s text stays within its card: %s" % [label_value, card.name, label.text.replace("\n", " / ")])


func _stress_card_geometry() -> void:
	var before: Dictionary = ui.state.duplicate(true)
	# An intentionally oversized, inert presentation fixture. It is never saved or
	# sent to the engine: every authored card is measured at its minimum width.
	ui.state.phase = "combat"
	ui.state.hand = Rules.data().cards_by_id.keys()
	ui._render()
	await _frames()
	_check_card_labels("all authored cards at minimum hand width")
	ui.state = before
	ui._render()
	await _frames()


func _stress_decision_geometry() -> void:
	var before: Dictionary = ui.state.duplicate(true)
	# Inert presentation fixtures cover every authored choice, including prices
	# and already-owned relic labels. They never become real saved game states.
	for event in Rules.data().events:
		ui.state = before.duplicate(true)
		ui.state.phase = "event"
		ui.state.enemy.hp = 0
		ui.state.event_id = event.id
		for choice in event.choices:
			var gained: String = choice.effects.get("gain_relic", "")
			if not gained.is_empty() and gained not in ui.state.relics:
				ui.state.relics.append(gained)
		ui._render()
		await _frames()
		_choice_layout("event")
		for index in range(event.choices.size()):
			var button := _button("EventChoice%d" % index)
			for label in button.find_children("*", "Label", true, false):
				_check(button.get_global_rect().encloses(label.get_global_rect()), "event %s: choice text fits: %s" % [event.id, label.text.replace("\n", " / ")])
			if event.choices[index].effects.has("gain_relic"):
				_check(button.disabled, "already-owned event relic cannot be selected twice")
			event_choices_measured += 1
	var relics: Array = Rules.data().relics
	for offset in range(0, relics.size(), 3):
		ui.state = before.duplicate(true)
		ui.state.phase = "relic"
		ui.state.enemy.hp = 0
		ui.state.relic_rewards = []
		for item in relics.slice(offset, mini(offset + 3, relics.size())):
			ui.state.relic_rewards.append(item.id)
		ui._render()
		await _frames()
		_choice_layout("relic")
		for index in range(ui.state.relic_rewards.size()):
			var button := _button("Relic%d" % index)
			for label in button.find_children("*", "Label", true, false):
				_check(button.get_global_rect().encloses(label.get_global_rect()), "relic choice text fits: " + label.text.replace("\n", " / "))
			relic_choices_measured += 1
	ui.state = before
	ui._render()
	await _frames()


func _capture(file_name: String) -> void:
	if screenshot_dir.is_empty():
		return
	_check(DisplayServer.get_name() != "headless", "screenshots require an actual display renderer")
	if DisplayServer.get_name() == "headless":
		return
	await RenderingServer.frame_post_draw
	var image := root.get_texture().get_image()
	_check(not image.is_empty() and image.get_width() > 0 and image.get_height() > 0, "actual framebuffer has pixels")
	if image.is_empty():
		return
	var first := image.get_pixel(0, 0)
	var varied := false
	for x in range(0, image.get_width(), maxi(1, image.get_width() / 24)):
		for y in range(0, image.get_height(), maxi(1, image.get_height() / 16)):
			var pixel := image.get_pixel(x, y)
			if Vector3(pixel.r - first.r, pixel.g - first.g, pixel.b - first.b).length() > 0.05:
				varied = true
	_check(varied, "framebuffer contains rendered UI rather than a uniform clear color")
	DirAccess.make_dir_recursive_absolute(screenshot_dir)
	var path := screenshot_dir.path_join(file_name)
	_check(image.save_png(path) == OK, "rendered viewport screenshot saved")
	screenshots.append({"path": path, "width": image.get_width(), "height": image.get_height()})


func _dialog() -> AcceptDialog:
	for child in ui.get_children():
		if child is AcceptDialog and child.visible:
			return child
	return null


func _close_dialog() -> void:
	var dialog := _dialog()
	if dialog != null:
		dialog.hide()
	await _frames()


func _pathway_layout() -> void:
	var dialog := _dialog()
	_check(dialog != null and root.get_visible_rect().encloses(Rect2(Vector2(dialog.position), Vector2(dialog.size))), "pathway dialog fits the game viewport")
	var choices := ui.find_children("Pathway_*", "Button", true, false)
	_check(choices.size() == 3, "all three pathway choices are presented")
	for button in choices:
		_check(button.get_viewport().get_visible_rect().encloses(button.get_global_rect()), "pathway button fits its dialog")
		_check(button.size.x >= 310 and button.size.y >= 260, "pathway choice keeps its authored touch surface")
		for label in button.find_children("*", "Label", true, false):
			_check(button.get_global_rect().encloses(label.get_global_rect()), "pathway description fits: " + label.text)


func _best_card() -> int:
	var chosen := -1
	var best := -100000.0
	for index in range(ui.state.hand.size()):
		var card: Dictionary = Rules.get_card(ui.state.hand[index])
		if card.cost > ui.state.player.energy:
			continue
		var score: float = card.get("damage", 0) * 2.0 + card.get("draw", 0) * 8.0 + card.get("attack_bonus", 0) * 12.0
		score += card.get("poison", 0) * 4.0 + card.get("vulnerable", 0) * 3.0 + card.get("weak", 0) * 4.0
		if card.get("heal", 0) > 0 and ui.state.player.hp < ui.state.player.max_hp - 5:
			score += card.heal * 3.0
		if card.get("sanity", 0) > 0 and ui.state.player.sanity < 9:
			score += 15.0
		if ui.state.enemy.intent.kind == "attack":
			score += mini(card.get("block", 0), maxi(0, ui.state.enemy.intent.value - ui.state.player.block)) * 1.8
		if score > best:
			best = score
			chosen = index
	return chosen


func _reward_index() -> int:
	var chosen := 0
	var best := -100000.0
	for index in range(ui.state.rewards.size()):
		var card: Dictionary = Rules.get_card(ui.state.rewards[index])
		var score: float = card.get("damage", 0) * 2.0 / maxf(1.0, card.cost)
		score += card.get("draw", 0) * 6.0 + card.get("attack_bonus", 0) * 12.0
		score += card.get("heal", 0) * 3.0 + card.get("poison", 0) * 3.0
		if score > best:
			best = score
			chosen = index
	return chosen


func _route_index() -> int:
	var preferred := "event" if phases_seen.get("event", 0) == 0 else "rest"
	for index in range(ui.state.route_options.size()):
		if ui.state.route_options[index].kind == preferred:
			return index
	return 0


func _choice_layout(phase: String) -> void:
	var pattern: String = {"route": "Route*", "event": "EventChoice*", "rest": "Rest*", "relic": "Relic*"}.get(phase, "")
	if pattern.is_empty():
		return
	var choices := ui.find_children(pattern, "Button", true, false)
	_check(not choices.is_empty(), phase + ": visible choices exist")
	for choice in choices:
		if not choice.is_visible_in_tree():
			continue
		_check(root.get_visible_rect().encloses(choice.get_global_rect()), phase + ": choice touch surface fits viewport")
		_check(choice.size.y >= 72, phase + ": choice has a large touch target")


func _walk_run() -> int:
	var rewards := 0
	phases_seen = {}
	encounters_seen = []
	for _step in range(1000):
		var phase: String = ui.state.phase
		phases_seen[phase] = phases_seen.get(phase, 0) + 1
		if phase in ["victory", "defeat"]:
			break
		var before: Dictionary = ui.state.duplicate(true)
		_choice_layout(phase)
		match phase:
			"combat":
				if ui.state.encounter not in encounters_seen:
					encounters_seen.append(ui.state.encounter)
				var index := _best_card()
				if index >= 0:
					var target := _button("Card%d" % index)
					var scroll = ui.find_child("HandScroll", true, false) as ScrollContainer
					scroll.ensure_control_visible(target)
					await _frames()
					await _click(target)
				else:
					await _click(_button("EndTurn"))
			"reward":
				var old_deck_size: int = ui.state.deck.size()
				await _click(_button("Card%d" % _reward_index()))
				rewards += 1
				_check(ui.state.deck.size() == old_deck_size + 1, "reward Control adds the selected card")
			"route":
				await _click(_button("Route%d" % _route_index()))
			"event":
				await _click(_button("EventChoice0"))
			"rest":
				await _click(_button("RestHeal"))
			"relic":
				var count: int = ui.state.relics.size()
				await _click(_button("Relic0"))
				_check(ui.state.relics.size() == count + 1, "relic Control adds the selected passive")
			_:
				_check(false, "known playable native phase: " + phase)
				break
		_check(ui.state != before, "native Control resolves " + phase + " action")
		_check(ui._read_local() == ui.state, "native " + phase + " action saves a resumable state")
		if ui.state == before:
			break
	return rewards


func _run() -> void:
	# The dummy headless display otherwise starts with a 64 × 64 window, which
	# expands the logical canvas to a square instead of the intended landscape.
	root.size = Vector2i(1280, 720)
	await _frames()
	for path in ["res://scripts/main.gd", "res://scripts/game_engine.gd", "res://scripts/cloud_save.gd", "res://data/content.json"]:
		source_hashes[path] = FileAccess.get_sha256(path)
	var packed = load("res://main.tscn") as PackedScene
	_check(packed != null, "native scene loads")
	if packed == null:
		quit(1)
		return
	ui = packed.instantiate() as Control
	root.add_child(ui)
	await _frames(5)
	# This suite checks the offline UI even when a developer has configured their
	# own export. Protocol tests exercise cloud requests through separate mocks.
	ui.cloud.configured = false
	_check(not ui.cloud.configured, "test fixture has no cloud configuration")
	await _reset()
	_layout("1280 × 720")
	await _capture("native-1280x720.png")

	# Hit the actual card Control and compare UI/model/save, not a callback emit.
	var index := _best_card()
	var before: Dictionary = ui.state.duplicate(true)
	var card: Dictionary = Rules.get_card(before.hand[index])
	if DisplayServer.get_name() == "headless":
		# Dummy display input cannot emulate OS touchscreen events.
		await _click(_button("Card%d" % index))
	else:
		await _tap(_button("Card%d" % index))
	_check(ui.state != before, "native card hit changes state")
	_check(ui.state.player.energy == before.player.energy - card.cost, "native card hit spends displayed energy")
	_check(ui._read_local() == ui.state and ui.local_save_ok, "action persists an exact local resume state")
	var old_turn: int = ui.state.turn
	var hp: int = ui.state.player.hp
	var expected_damage: int = maxi(0, ui.state.enemy.intent.value - ui.state.player.block)
	await _click(_button("EndTurn"))
	_check(ui.state.turn == old_turn + 1, "End turn Control advances turn")
	_check(ui.state.player.hp == hp - expected_damage, "End turn resolves displayed enemy attack")
	_check(ui.state.player.energy == ui.state.player.max_energy and ui.state.hand.size() >= 5, "next turn refills energy and hand")

	await _click(_button("DeckButton"))
	_check(_dialog() != null and _dialog().title.contains("%d cards" % ui.state.deck.size()), "Deck Control opens current deck")
	await _close_dialog()
	before = ui.state.duplicate(true)
	await _click(_button("CloudButton"))
	_check(_dialog() != null and ui.cloud_status.text.contains("unavailable") and ui.cloud_status.text.contains("offline"), "unconfigured cloud explains offline availability")
	_check(ui.state == before and ui._read_local() == before, "unconfigured cloud preserves offline progress")
	# Replay inert cloud result fixtures; no HTTP request or real account is used.
	var snapshot: Dictionary = Rules.make_save(Rules.create_run(77))
	ui._cloud_result("download_save", true, {"has_save": true, "save_envelope": snapshot})
	_check(ui.cloud_snapshot == snapshot, "compatible cloud read makes a restore snapshot")
	ui._cloud_result("login", false, {"message": "Inert failed-login fixture"})
	_check(ui.cloud_snapshot.is_empty(), "failed account switch discards an old restore snapshot")
	ui._cloud_result("download_save", true, {"has_save": true, "save_envelope": snapshot})
	ui._cloud_restore()
	_check(is_instance_valid(ui.restore_confirmation) and ui.restore_confirmation.visible, "cloud restore asks before replacing this device")
	ui._cloud_result("download_save", false, {"message": "Inert failed-read fixture"})
	_check(ui.cloud_snapshot.is_empty() and ui.restore_confirmation == null, "failed cloud read closes stale restore confirmation")
	ui._cloud_result("download_save", true, {"has_save": true, "save_envelope": snapshot})
	ui._cloud_upload()
	_check(ui.cloud_snapshot.is_empty() and ui.state == before, "unconfigured upload clears stale snapshot without touching progress")
	ui._cloud_result("download_save", true, {"has_save": true, "save_envelope": {"invalid": true}})
	_check(ui.cloud_snapshot.is_empty() and ui.state == before, "invalid remote snapshot cannot replace offline progress")
	await _close_dialog()

	for pathway in ["seer", "hunter", "apprentice"]:
		before = ui.state.duplicate(true)
		await _click(_button("NewRun"))
		var confirmation := _dialog() as ConfirmationDialog
		_check(confirmation != null and ui.state == before, "New run asks before replacing progress")
		if confirmation != null:
			await _click(confirmation.get_ok_button())
		_check(ui.state == before, "pathway selection keeps current progress until a choice")
		_pathway_layout()
		await _click(_button("Pathway_" + pathway))
		_check(ui.state.seed == before.seed + 1 and ui.state.turn == 1 and ui.state.pathway == pathway, "pathway Control starts a new " + pathway + " run")
		var path: Dictionary = Rules.data().pathways_by_id[pathway]
		_check(ui.state.deck == path.deck and path.starting_relic in ui.state.relics, pathway + ": chosen starting deck and relic are present")
		_check(ui._read_local() == ui.state, pathway + ": chosen pathway resumes from local save")
		_layout(pathway + " pathway")
		if pathway != "seer":
			await _capture("native-" + pathway + ".png")

	# A deterministic original campaign, through actual native Controls.
	await _reset(123)
	var rewards := await _walk_run()
	_check(ui.state.phase == "victory" and ui.state.encounter == 11 and encounters_seen.size() == 12, "native UI completes all twelve combats across three acts")
	_check(rewards >= 9, "campaign awards a continuing deck")
	for phase in ["route", "event", "rest", "relic"]:
		_check(phases_seen.get(phase, 0) > 0, "campaign has playable " + phase + " Controls")
	_check(ui._read_local() == ui.state, "terminal run remains resumable")
	await _capture("native-victory.png")
	await _click(_button("Restart"))
	_check(ui.state.phase == "combat" and ui.state.encounter == 0, "terminal Restart Control starts a fresh run")
	await _stress_card_geometry()
	await _stress_decision_geometry()

	# Preserve the authored baseline at different physical sizes and aspect ratios.
	root.size = Vector2i(1600, 900)
	await _frames(5)
	_layout("1600 × 900")
	await _capture("native-1600x900.png")
	root.size = Vector2i(1600, 720)
	await _frames(5)
	_layout("1600 × 720 wide")
	await _capture("native-wide.png")
	root.size = Vector2i(960, 540)
	await _frames(5)
	_layout("960 × 540 scaled")
	await _capture("native-960x540.png")

	for path in source_hashes:
		_check(FileAccess.get_sha256(path) == source_hashes[path], "tested source stayed unchanged: " + path)
	var report = {"checks": checks, "failures": failures, "input_actions": input_actions, "touch_actions": touch_actions, "event_choices_measured": event_choices_measured, "relic_choices_measured": relic_choices_measured, "phases_seen": phases_seen, "encounters_seen": encounters_seen, "source_sha256": source_hashes, "display": DisplayServer.get_name(), "screenshots": screenshots}
	print(JSON.stringify(report))
	if not screenshot_dir.is_empty():
		var file := FileAccess.open(screenshot_dir.path_join("native-ui-check.json"), FileAccess.WRITE)
		if file != null:
			file.store_string(JSON.stringify(report, "\t"))
	ui.queue_free()
	await _frames()
	quit(0 if failures == 0 else 1)
