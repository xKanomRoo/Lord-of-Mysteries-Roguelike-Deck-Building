class_name CloudSave
extends Node
## Optional HTTPS cloud backup. Local play never depends on this node.
## Only a Supabase publishable/legacy anon PUBLIC key belongs in the APK.

signal result(operation: String, ok: bool, payload: Dictionary)
signal status_changed(message: String)
signal authenticated
signal save_loaded(payload: Dictionary, revision: int)
signal save_completed(revision: int)
signal request_failed(message: String)
signal conflict_detected

const SESSION_PATH := "user://cloud-session.json"
const GameSchema = preload("res://scripts/game_engine.gd")
const MAX_SAVE_BYTES := 65536
const MAX_RESPONSE_BYTES := 262144
const MAX_REVISION := 2147483647
const REQUEST_TIMEOUT := 15.0

var configured := false
var _base_url := ""
var _public_key := ""
var _access_token := ""
var _refresh_token := ""
var _user_id := ""
var _expires_at := 0
var _is_guest := true
var _revision := -1
var _busy := false
var _http: HTTPRequest


func configure(base_url: String, public_key: String) -> bool:
	if _busy:
		return false
	var host_pattern := RegEx.new()
	host_pattern.compile("^https://[A-Za-z0-9][A-Za-z0-9.-]*(?::443)?/?$")
	var clean_url := base_url.strip_edges()
	var clean_key := public_key.strip_edges()
	if host_pattern.search(clean_url) == null or not _valid_public_key(clean_key):
		return false
	if clean_key.contains("\n") or clean_key.contains("\r"):
		return false
	_clear_memory()
	_base_url = clean_url.trim_suffix("/")
	_public_key = clean_key
	configured = true
	_restore_session()
	return true


func configure_from_file(path: String = "res://cloud-config.json") -> bool:
	if not FileAccess.file_exists(path):
		return false
	var file := FileAccess.open(path, FileAccess.READ)
	if file == null or file.get_length() > 4096:
		return false
	var parsed = JSON.parse_string(file.get_as_text())
	if not parsed is Dictionary:
		return false
	if not parsed.get("base_url") is String or not parsed.get("public_key") is String:
		return false
	return configure(parsed.base_url, parsed.public_key)


func is_authenticated() -> bool:
	return not _user_id.is_empty() and not _access_token.is_empty()


func sign_in() -> void:
	sign_in_guest()


func save_game(payload: Dictionary) -> void:
	upload_save(payload)


func load_game() -> void:
	download_save()


func sign_in_guest() -> void:
	var operation := "sign_in_guest"
	if not _begin(operation):
		return
	if not _refresh_token.is_empty():
		if await _refresh_session():
			_finish(operation, true, {"message": "Saved account session restored."})
		else:
			_finish(operation, false, {"message": "Session could not be refreshed. Sign in again; do not create a new guest to recover an old save."})
		return
	var reply: Dictionary = await _request("/auth/v1/signup", HTTPClient.METHOD_POST, {}, false)
	if not _accept_auth_reply(reply):
		_finish(operation, false, {"message": "Guest sign-in failed. Enable anonymous sign-ins in your Supabase project and check connectivity."})
		return
	_finish(operation, true, {"message": "Guest signed in. Link an email before changing devices."})


func login(email: String, password: String) -> void:
	var operation := "login"
	if not _begin(operation):
		return
	if not _valid_credentials(email, password):
		_finish(operation, false, {"message": "Enter an email and a password of at least 8 characters."})
		return
	var reply: Dictionary = await _request("/auth/v1/token?grant_type=password", HTTPClient.METHOD_POST, {"email": email.strip_edges(), "password": password}, false)
	if not _accept_auth_reply(reply):
		_finish(operation, false, {"message": "Sign-in failed. Check your email, password and email confirmation."})
		return
	_finish(operation, true, {"message": "Signed in. Check the cloud save before backing up."})


func register(email: String, password: String) -> void:
	var operation := "register"
	if not _begin(operation):
		return
	if not _valid_credentials(email, password):
		_finish(operation, false, {"message": "Enter an email and a password of at least 8 characters."})
		return
	if is_authenticated():
		if not _is_guest:
			_finish(operation, false, {"message": "This account is already registered. Use Login for another account."})
			return
		if not await _ensure_session():
			_finish(operation, false, {"message": "Refresh the guest session before linking an email."})
			return
		var linked: Dictionary = await _request("/auth/v1/user", HTTPClient.METHOD_PUT, {"email": email.strip_edges(), "password": password}, true)
		if not _successful(linked) or not linked.data is Dictionary or linked.data.get("id") != _user_id:
			_finish(operation, false, {"message": "Email linking failed. Enable manual linking and check the project Auth settings."})
			return
		_finish(operation, true, {"message": "Email linking requested. Confirm the email, then use Login to recover this same account.", "requires_confirmation": true})
		return
	var reply: Dictionary = await _request("/auth/v1/signup", HTTPClient.METHOD_POST, {"email": email.strip_edges(), "password": password}, false)
	if not _successful(reply) or not reply.data is Dictionary:
		_finish(operation, false, {"message": "Registration failed. Check the project's email sign-up settings."})
		return
	if reply.data.has("access_token"):
		if not _accept_auth_reply(reply):
			_finish(operation, false, {"message": "The registration session was not valid."})
			return
		_finish(operation, true, {"message": "Registered. Check the cloud save before backing up."})
	else:
		if not reply.data.get("user") is Dictionary or not _valid_uuid(reply.data.user.get("id")):
			_finish(operation, false, {"message": "The registration response was not valid."})
			return
		_finish(operation, true, {"message": "Check your email to confirm registration, then use Login.", "requires_confirmation": true})


func download_save() -> void:
	var operation := "download_save"
	if not _begin(operation):
		return
	if not await _ensure_session():
		_finish(operation, false, {"message": "Sign in before checking the cloud save."})
		return
	var path := "/rest/v1/cloud_saves?select=user_id,schema_version,revision,payload&user_id=eq.%s&limit=1" % _user_id
	var reply: Dictionary = await _request(path, HTTPClient.METHOD_GET, {}, true)
	if not _successful(reply) or not reply.data is Array or reply.data.size() > 1:
		_finish(operation, false, {"message": "Cloud save could not be checked. Local progress is unchanged."})
		return
	if reply.data.is_empty():
		_revision = 0
		_finish(operation, true, {"message": "No cloud backup yet. You can back up this device.", "revision": 0, "has_save": false})
		return
	var row = reply.data[0]
	if not _valid_row(row):
		_finish(operation, false, {"message": "Cloud save format was rejected. Local progress is unchanged."})
		return
	_revision = int(row.revision)
	_finish(operation, true, {"message": "Cloud backup checked. Restore only if you want to replace this device's progress.", "revision": _revision, "has_save": true, "save_envelope": row.payload})


func upload_save(save_envelope: Dictionary) -> void:
	var operation := "upload_save"
	if not _begin(operation):
		return
	if not _valid_save_payload(save_envelope):
		_finish(operation, false, {"message": "Save payload is invalid or exceeds 64 KiB."})
		return
	if not await _ensure_session():
		_finish(operation, false, {"message": "Sign in before backing up."})
		return
	if _revision < 0:
		_finish(operation, false, {"message": "Check the cloud save first. This prevents overwriting another device's backup."})
		return
	if _revision >= MAX_REVISION:
		_finish(operation, false, {"message": "Cloud save revision limit reached."})
		return
	var next_revision := _revision + 1
	var body := {"schema_version": 1, "revision": next_revision, "payload": save_envelope}
	var path := "/rest/v1/cloud_saves"
	var method := HTTPClient.METHOD_POST
	if _revision == 0:
		body["user_id"] = _user_id
	else:
		body.erase("schema_version")
		path += "?user_id=eq.%s&revision=eq.%d" % [_user_id, _revision]
		method = HTTPClient.METHOD_PATCH
	var reply: Dictionary = await _request(path, method, body, true, true)
	if reply.get("status", 0) == 409 or (_successful(reply) and reply.data is Array and reply.data.is_empty()):
		_revision = -1
		_finish(operation, false, {"message": "Another device changed the cloud backup. Check it again; local progress is unchanged.", "conflict": true})
		return
	if not _successful(reply) or not reply.data is Array or reply.data.size() != 1 or not _valid_row(reply.data[0]) or int(reply.data[0].revision) != next_revision:
		# An interrupted write might have reached the server: require a new read.
		_revision = -1
		_finish(operation, false, {"message": "Backup was not confirmed. Check the cloud again before retrying; local progress is unchanged."})
		return
	_revision = next_revision
	_finish(operation, true, {"message": "Cloud backup saved.", "revision": _revision})


func sign_out() -> void:
	if _busy:
		_finish_busy_error("sign_out")
		return
	_clear_memory()
	var removal_failed := false
	for path in [SESSION_PATH, SESSION_PATH + ".tmp"]:
		if FileAccess.file_exists(path):
			removal_failed = DirAccess.remove_absolute(ProjectSettings.globalize_path(path)) != OK or removal_failed
	if removal_failed:
		_finish("sign_out", false, {"message": "Session could not be removed from this device."})
		return
	_finish("sign_out", true, {"message": "Local session cleared. An unlinked guest account cannot be recovered."})


func _begin(operation: String) -> bool:
	if _busy:
		_finish_busy_error(operation)
		return false
	if not configured:
		result.emit(operation, false, {"message": "Cloud backup is not configured. Offline play is available."})
		return false
	_busy = true
	status_changed.emit("Connecting…")
	return true


func _finish_busy_error(operation: String) -> void:
	result.emit(operation, false, {"message": "Wait for the current cloud request to finish."})


func _finish(operation: String, ok: bool, payload: Dictionary) -> void:
	_busy = false
	status_changed.emit(str(payload.get("message", "")))
	result.emit(operation, ok, payload)
	if not ok:
		request_failed.emit(str(payload.get("message", "Cloud request failed.")))
		if payload.get("conflict", false):
			conflict_detected.emit()
	elif operation in ["sign_in_guest", "login", "register"] and is_authenticated():
		authenticated.emit()
	elif operation == "download_save" and payload.get("has_save", false):
		save_loaded.emit(payload.save_envelope, int(payload.revision))
	elif operation == "upload_save":
		save_completed.emit(int(payload.revision))


func _request(path: String, method: int, payload: Dictionary, with_session: bool, return_row: bool = false) -> Dictionary:
	if _http == null:
		_http = HTTPRequest.new()
		_http.timeout = REQUEST_TIMEOUT
		_http.body_size_limit = MAX_RESPONSE_BYTES
		_http.max_redirects = 0
		add_child(_http)
	var headers := PackedStringArray(["apikey: " + _public_key, "Content-Type: application/json", "Accept: application/json"])
	if with_session:
		headers.append("Authorization: Bearer " + _access_token)
	if return_row:
		headers.append("Prefer: return=representation")
	var body := "" if method == HTTPClient.METHOD_GET else JSON.stringify(payload)
	# Godot's default TLS verifies the certificate and hostname. Never relax it.
	var error := _http.request(_base_url + path, headers, method, body)
	if error != OK:
		return {"transport_ok": false, "status": 0, "data": null}
	var completed: Array = await _http.request_completed
	if completed.size() != 4 or completed[0] != HTTPRequest.RESULT_SUCCESS:
		return {"transport_ok": false, "status": 0, "data": null}
	var bytes: PackedByteArray = completed[3]
	if bytes.size() > MAX_RESPONSE_BYTES:
		return {"transport_ok": false, "status": 0, "data": null}
	var parser := JSON.new()
	if parser.parse(bytes.get_string_from_utf8()) != OK:
		return {"transport_ok": false, "status": int(completed[1]), "data": null}
	return {"transport_ok": true, "status": int(completed[1]), "data": parser.data}


func _successful(reply: Dictionary) -> bool:
	return reply.get("transport_ok", false) and reply.get("status", 0) >= 200 and reply.get("status", 0) < 300


func _ensure_session() -> bool:
	if not is_authenticated():
		return false
	if _expires_at <= int(Time.get_unix_time_from_system()) + 60:
		return await _refresh_session()
	return true


func _refresh_session() -> bool:
	if _refresh_token.is_empty():
		return false
	var reply: Dictionary = await _request("/auth/v1/token?grant_type=refresh_token", HTTPClient.METHOD_POST, {"refresh_token": _refresh_token}, false)
	return _accept_auth_reply(reply)


func _accept_auth_reply(reply: Dictionary) -> bool:
	if not _successful(reply) or not reply.get("data") is Dictionary:
		return false
	var data: Dictionary = reply.data
	if not _valid_token(data.get("access_token")) or not _valid_token(data.get("refresh_token")):
		return false
	if not data.get("user") is Dictionary or not _valid_uuid(data.user.get("id")):
		return false
	var expires_in = data.get("expires_in", 0)
	if not _whole_number(expires_in) or expires_in < 60 or expires_in > 604800:
		return false
	_access_token = data.access_token
	_refresh_token = data.refresh_token
	_user_id = data.user.id
	_is_guest = data.user.get("is_anonymous", false) == true
	_expires_at = int(Time.get_unix_time_from_system()) + int(expires_in)
	_revision = -1
	return _store_session()


func _store_session() -> bool:
	var file := FileAccess.open(SESSION_PATH + ".tmp", FileAccess.WRITE)
	if file == null:
		_clear_memory()
		return false
	file.store_string(JSON.stringify({"base_url": _base_url, "access_token": _access_token, "refresh_token": _refresh_token, "user_id": _user_id, "expires_at": _expires_at, "is_guest": _is_guest}))
	file.flush()
	var error := file.get_error()
	file.close()
	if error != OK or DirAccess.rename_absolute(ProjectSettings.globalize_path(SESSION_PATH + ".tmp"), ProjectSettings.globalize_path(SESSION_PATH)) != OK:
		if FileAccess.file_exists(SESSION_PATH + ".tmp"):
			DirAccess.remove_absolute(ProjectSettings.globalize_path(SESSION_PATH + ".tmp"))
		_clear_memory()
		return false
	return true


func _restore_session() -> void:
	if not FileAccess.file_exists(SESSION_PATH):
		return
	var file := FileAccess.open(SESSION_PATH, FileAccess.READ)
	if file == null or file.get_length() > 32768:
		return
	var data = JSON.parse_string(file.get_as_text())
	if not data is Dictionary or data.get("base_url") != _base_url:
		return
	if not _valid_token(data.get("access_token")) or not _valid_token(data.get("refresh_token")) or not _valid_uuid(data.get("user_id")) or not _whole_number(data.get("expires_at")):
		return
	_access_token = data.access_token
	_refresh_token = data.refresh_token
	_user_id = data.user_id
	_expires_at = int(data.expires_at)
	_is_guest = data.get("is_guest", true) == true


func _clear_memory() -> void:
	_access_token = ""
	_refresh_token = ""
	_user_id = ""
	_expires_at = 0
	_is_guest = true
	_revision = -1


func _valid_row(row: Variant) -> bool:
	return row is Dictionary and row.get("user_id") == _user_id and _whole_number(row.get("schema_version")) and row.schema_version == 1 and _whole_number(row.get("revision")) and row.revision >= 1 and row.revision <= MAX_REVISION and row.get("payload") is Dictionary and _valid_save_payload(row.payload)


func _valid_save_payload(payload: Dictionary) -> bool:
	if payload.size() != 4 or not _whole_number(payload.get("schema_version")) or payload.schema_version != GameSchema.SAVE_VERSION:
		return false
	if payload.get("engine") != GameSchema.ENGINE_ID or not payload.get("state") is Dictionary or not payload.get("state_sha256") is String:
		return false
	var hash_pattern := RegEx.new()
	hash_pattern.compile("^[0-9a-f]{64}$")
	# The game engine checks the state schema and checksum before applying a save.
	return hash_pattern.search(payload.state_sha256) != null and JSON.stringify(payload).to_utf8_buffer().size() <= MAX_SAVE_BYTES


func _valid_credentials(email: String, password: String) -> bool:
	var clean := email.strip_edges()
	return clean.length() >= 3 and clean.length() <= 254 and clean.contains("@") and not clean.contains("\n") and not clean.contains("\r") and password.length() >= 8 and password.length() <= 128


func _valid_token(value: Variant) -> bool:
	return value is String and value.length() > 0 and value.length() <= 8192 and not value.contains("\n") and not value.contains("\r")


func _valid_public_key(value: String) -> bool:
	if value.length() < 20 or value.length() > 2048 or value.contains("\n") or value.contains("\r"):
		return false
	if value.begins_with("sb_publishable_"):
		return true
	var pieces := value.split(".")
	if pieces.size() != 3:
		return false
	var encoded := pieces[1].replace("-", "+").replace("_", "/")
	while encoded.length() % 4 != 0:
		encoded += "="
	var decoded = JSON.parse_string(Marshalls.base64_to_utf8(encoded))
	# This is a local key-type check, not JWT signature verification. Auth verifies it.
	return decoded is Dictionary and decoded.get("role") == "anon"


func _valid_uuid(value: Variant) -> bool:
	if not value is String:
		return false
	var pattern := RegEx.new()
	pattern.compile("^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
	return pattern.search(value) != null


func _whole_number(value: Variant) -> bool:
	return (value is int or value is float) and is_finite(float(value)) and float(value) == float(int(value))
