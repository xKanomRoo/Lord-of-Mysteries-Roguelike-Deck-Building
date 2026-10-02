extends SceneTree
## Offline protocol fixtures. These never contact Supabase or another server.

const CloudScript = preload("res://scripts/cloud_save.gd")
const GameSchema = preload("res://scripts/game_engine.gd")
const USER_A := "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
const USER_B := "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
const PUBLIC_KEY := "sb_publishable_local_protocol_fixture_only"
var checks := 0
var failures := 0

class FakeCloud:
	extends "res://scripts/cloud_save.gd"
	var replies: Array = []
	var requests: Array = []
	var events: Array = []

	func _request(path: String, method: int, payload: Dictionary, with_session: bool, return_row: bool = false) -> Dictionary:
		requests.append({"path": path, "method": method, "payload": payload.duplicate(true), "session": with_session, "return_row": return_row})
		if replies.is_empty():
			return {"transport_ok": false, "status": 0, "data": null}
		return replies.pop_front()

	func _store_session() -> bool:
		return true

	func _restore_session() -> void:
		pass

class SlowCloud:
	extends FakeCloud

	func _request(path: String, method: int, payload: Dictionary, with_session: bool, return_row: bool = false) -> Dictionary:
		await get_tree().create_timer(0.02).timeout
		return await super._request(path, method, payload, with_session, return_row)


func _initialize() -> void:
	_run.call_deferred()


func _check(condition: bool, message: String) -> void:
	checks += 1
	if not condition:
		failures += 1
		printerr("FAIL: " + message)


func _new_cloud() -> FakeCloud:
	var cloud := FakeCloud.new()
	root.add_child(cloud)
	cloud.result.connect(func(operation, ok, payload): cloud.events.append({"operation": operation, "ok": ok, "payload": payload}))
	_check(cloud.configure("https://fixture.supabase.co", PUBLIC_KEY), "configure fixture")
	return cloud


func _reply(data: Variant, status: int = 200) -> Dictionary:
	return {"transport_ok": true, "status": status, "data": data}


func _auth() -> Dictionary:
	return {"access_token": "fixture-access-token", "refresh_token": "fixture-refresh-token", "expires_in": 3600, "user": {"id": USER_A, "is_anonymous": true}}


func _envelope() -> Dictionary:
	return {"schema_version": GameSchema.SAVE_VERSION, "engine": GameSchema.ENGINE_ID, "state": {"seed": "fixture"}, "state_sha256": "0".repeat(64)}


func _row(revision: Variant, owner: String = USER_A) -> Dictionary:
	return {"user_id": owner, "schema_version": 1, "revision": revision, "payload": _envelope()}


func _login_guest(cloud: FakeCloud) -> void:
	cloud.replies.append(_reply(_auth()))
	cloud.sign_in_guest()
	_check(cloud.events[-1].ok and cloud.is_authenticated(), "guest session accepted")


func _run() -> void:
	var validator := _new_cloud()
	_check(not validator.configure("http://fixture.supabase.co", PUBLIC_KEY), "plaintext HTTP rejected")
	_check(not validator.configure("https://fixture.supabase.co/path", PUBLIC_KEY), "base path rejected")
	_check(not validator.configure("https://fixture.supabase.co", "sb_secret_fixture_server_key"), "secret key rejected")
	var anon_key := "x." + Marshalls.utf8_to_base64('{"role":"anon"}').trim_suffix("=") + ".x"
	var role_key := "x." + Marshalls.utf8_to_base64('{"role":"service_role"}').trim_suffix("=") + ".x"
	_check(validator.configure("https://fixture.supabase.co", anon_key), "legacy anon public key allowed")
	_check(not validator.configure("https://fixture.supabase.co", role_key), "legacy service-role key rejected")
	_check(not validator.configure("https://fixture.supabase.co", PUBLIC_KEY + "\r\nX-Test: injected"), "header injection rejected")
	var unsupported_save := _envelope()
	unsupported_save.schema_version = GameSchema.SAVE_VERSION + 1
	_check(not validator._valid_save_payload(unsupported_save), "unsupported game save version rejected independently of storage protocol")
	unsupported_save = _envelope()
	unsupported_save.engine = "another-game-engine"
	_check(not validator._valid_save_payload(unsupported_save), "another game engine save rejected")
	validator.free()

	var offline := FakeCloud.new()
	root.add_child(offline)
	offline.result.connect(func(operation, ok, payload): offline.events.append({"operation": operation, "ok": ok, "payload": payload}))
	offline.download_save()
	_check(not offline.events[-1].ok and offline.requests.is_empty(), "unconfigured offline mode has no request")
	offline.free()

	var cloud := _new_cloud()
	_login_guest(cloud)
	cloud.upload_save(_envelope())
	_check(not cloud.events[-1].ok and cloud.requests.size() == 1, "upload before first read refused")
	cloud.replies.append(_reply([]))
	cloud.download_save()
	_check(cloud.events[-1].ok and not cloud.events[-1].payload.has_save and cloud._revision == 0, "empty cloud read initializes revision")
	cloud.replies.append(_reply([_row(1)], 201))
	cloud.upload_save(_envelope())
	_check(cloud.events[-1].ok and cloud._revision == 1, "first insert acknowledged")
	_check(cloud.requests[-1].method == HTTPClient.METHOD_POST and cloud.requests[-1].payload.user_id == USER_A and cloud.requests[-1].payload.revision == 1, "insert owns player and revision")
	cloud.replies.append(_reply([_row(2)]))
	cloud.upload_save(_envelope())
	_check(cloud.events[-1].ok and cloud._revision == 2, "update acknowledged")
	_check(cloud.requests[-1].path.ends_with("&revision=eq.1") and cloud.requests[-1].method == HTTPClient.METHOD_PATCH, "update filters expected old revision")
	_check(not cloud.requests[-1].payload.has("user_id") and not cloud.requests[-1].payload.has("schema_version"), "update does not claim owner or schema privileges")
	cloud.replies.append(_reply([]))
	cloud.upload_save(_envelope())
	_check(not cloud.events[-1].ok and cloud.events[-1].payload.conflict and cloud._revision == -1, "stale patch detected as conflict")
	var request_count := cloud.requests.size()
	cloud.upload_save(_envelope())
	_check(cloud.requests.size() == request_count, "conflict retry requires re-read")
	cloud.replies.append(_reply([_row(5)]))
	cloud.download_save()
	_check(cloud.events[-1].ok and cloud.events[-1].payload.save_envelope.state.seed == "fixture" and cloud._revision == 5, "remote backup exposed without applying local game state")
	cloud.replies.append({"transport_ok": false, "status": 0, "data": null})
	cloud.upload_save(_envelope())
	_check(not cloud.events[-1].ok and cloud._revision == -1, "ambiguous failed write forces read")
	cloud.replies.append(_reply([_row(9, USER_B)]))
	cloud.download_save()
	_check(not cloud.events[-1].ok and cloud._revision == -1, "wrong player response rejected")
	cloud.replies.append(_reply([_row(1.5)]))
	cloud.download_save()
	_check(not cloud.events[-1].ok, "fractional revision rejected")
	cloud.replies.append(_reply([_row(1), _row(2)]))
	cloud.download_save()
	_check(not cloud.events[-1].ok, "multiple cloud rows rejected")
	var future_row := _row(1)
	future_row.schema_version = 2
	cloud.replies.append(_reply([future_row]))
	cloud.download_save()
	_check(not cloud.events[-1].ok, "unsupported row schema rejected")
	request_count = cloud.requests.size()
	var huge_save := _envelope()
	huge_save.state["huge"] = "x".repeat(65537)
	cloud.upload_save(huge_save)
	_check(not cloud.events[-1].ok and cloud.requests.size() == request_count, "oversized save blocked before network")
	cloud._expires_at = 0
	cloud.replies.append(_reply(_auth()))
	cloud.replies.append(_reply([_row(6)]))
	cloud.download_save()
	_check(cloud.events[-1].ok and cloud.requests[-2].path.ends_with("grant_type=refresh_token") and cloud._revision == 6, "expired session refreshed before read")
	cloud.replies.append(_reply({"id": USER_A}))
	cloud.register("guest@example.com", "fixture-password")
	_check(cloud.events[-1].ok and cloud.events[-1].payload.requires_confirmation and cloud.requests[-1].method == HTTPClient.METHOD_PUT and cloud._user_id == USER_A, "guest email linking retains player identity")
	cloud.free()

	var invalid := _new_cloud()
	var invalid_auth := _auth()
	invalid_auth.user.id = USER_A + "&injected=true"
	invalid.replies.append(_reply(invalid_auth))
	invalid.sign_in_guest()
	_check(not invalid.events[-1].ok and not invalid.is_authenticated(), "auth user id injection rejected")
	invalid_auth = _auth()
	invalid_auth.expires_in = 1.5
	invalid.replies.append(_reply(invalid_auth))
	invalid.sign_in_guest()
	_check(not invalid.events[-1].ok, "invalid expiry rejected")
	invalid.replies.append(_reply({"user": {"id": USER_A}}, 200))
	invalid.sign_in_guest()
	_check(not invalid.events[-1].ok, "missing auth tokens rejected")
	invalid.replies.append(_reply({"user": {"id": USER_A}}))
	invalid.register("player@example.com", "fixture-password")
	_check(invalid.events[-1].ok and invalid.events[-1].payload.requires_confirmation and not invalid.is_authenticated(), "confirmation-required signup does not fabricate session")
	invalid.free()

	var slow := SlowCloud.new()
	root.add_child(slow)
	slow.result.connect(func(operation, ok, payload): slow.events.append({"operation": operation, "ok": ok, "payload": payload}))
	slow.configure("https://fixture.supabase.co", PUBLIC_KEY)
	slow.replies.append(_reply(_auth()))
	slow.sign_in_guest()
	slow.sign_in_guest()
	_check(slow.events.size() == 1 and not slow.events[0].ok and slow._busy, "overlapping request refused without releasing active guard")
	await create_timer(0.04).timeout
	_check(slow.events.size() == 2 and slow.events[-1].ok and not slow._busy and slow.requests.size() == 1, "original request completes after rejected overlap")
	slow.free()

	# Run with isolated XDG_DATA_HOME, as documented; fixture credentials only.
	var disk_session = CloudScript.new()
	root.add_child(disk_session)
	disk_session.configure("https://fixture.supabase.co", PUBLIC_KEY)
	disk_session._access_token = "fixture-access-token"
	disk_session._refresh_token = "fixture-refresh-token"
	disk_session._user_id = USER_A
	disk_session._expires_at = int(Time.get_unix_time_from_system()) + 3600
	_check(disk_session._store_session() and FileAccess.file_exists(CloudScript.SESSION_PATH), "session persisted in private user storage")
	disk_session.configure("https://other-project.supabase.co", PUBLIC_KEY)
	_check(not disk_session.is_authenticated(), "stored tokens bound to configured project URL")
	disk_session.configure("https://fixture.supabase.co", PUBLIC_KEY)
	_check(disk_session._user_id == USER_A, "same project restores private session")
	var staged := FileAccess.open(CloudScript.SESSION_PATH + ".tmp", FileAccess.WRITE)
	staged.store_string("fixture-only-staged-token")
	staged.close()
	disk_session.sign_out()
	_check(not FileAccess.file_exists(CloudScript.SESSION_PATH) and not FileAccess.file_exists(CloudScript.SESSION_PATH + ".tmp") and not disk_session.is_authenticated(), "logout removes session and staged token copies")
	disk_session.free()
	print("CLOUD_PROTOCOL_FIXTURES: %d checks, %d failures; no network requests" % [checks, failures])
	quit(0 if failures == 0 else 1)
