import os
import uuid
import time
import json
import csv
import hashlib
import random
from datetime import datetime, timezone
from pathlib import Path

from flask import Flask, render_template, request, jsonify, send_from_directory

from image_to_binary import image_to_binary

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
UPLOAD_FOLDER = os.path.join(BASE_DIR, "static", "uploads")
KEYS_BASE_DIR = os.path.join(BASE_DIR, "static", "keys")
RAW_IMG_DIR = os.path.join(BASE_DIR, "RawImg")
TEMP_DECRYPT_DIR = os.path.join(BASE_DIR, "tmp_decrypt")
BINARY_MAPPING_CSV = os.path.join(BASE_DIR, "image_binary_mapping.csv")

os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(KEYS_BASE_DIR, exist_ok=True)
os.makedirs(TEMP_DECRYPT_DIR, exist_ok=True)

ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZ ,."
ALPHABET_SIZE = len(ALPHABET)
KEY_CHARSET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"

app = Flask(__name__)
app.config["SECRET_KEY"] = "dev-secret-key"
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER

# Chat history stored in memory.
messages = []
MAX_HISTORY = 200

# Online users: user_id -> {"username": ..., "last_seen": timestamp}
online_users = {}

# Cache for image_binary_mapping.csv: image_name -> binary_code
_binary_cache = None


def now_ms():
    return int(time.time() * 1000)


def make_message(user_id, username, msg_type, content):
    """Build a message payload."""
    ts = datetime.now(timezone.utc).isoformat(timespec="seconds")
    return {
        "id": str(uuid.uuid4()),
        "userId": user_id,
        "username": username,
        "type": msg_type,  # "text" / "image" / "system"
        "content": content,
        "timestamp": ts,
        "tsMs": now_ms(),
    }


def prune_history():
    global messages
    if len(messages) > MAX_HISTORY:
        messages = messages[-MAX_HISTORY:]


def get_online_users():
    # Heartbeat interval is around 7-8s, so use a relaxed offline threshold.
    cutoff = now_ms() - 25_000
    return [
        {"userId": uid, "username": info["username"]}
        for uid, info in online_users.items()
        if info.get("last_seen", 0) >= cutoff
    ]


def generate_random_key(length: int = 8) -> str:
    return "".join(random.choice(KEY_CHARSET) for _ in range(length))


def char_to_index(ch: str) -> int:
    ch = ch.upper()
    if ch in ALPHABET:
        return ALPHABET.index(ch)
    return ALPHABET.index(" ")


def index_to_char(idx: int) -> str:
    return ALPHABET[idx % ALPHABET_SIZE]


def safe_key_name(key: str) -> str:
    return "".join(c if c.isalnum() or c in "-_." else "_" for c in key) or "default"


def compute_char_index(binary_code: str, key: str) -> int:
    data = (key + ":" + (binary_code or "")).encode("utf-8")
    digest = hashlib.sha256(data).digest()
    value = int.from_bytes(digest[:4], "big")
    return value % ALPHABET_SIZE


def _dedupe_keep_order(items):
    seen = set()
    out = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        out.append(item)
    return out


def _normalize_mapping(mapping):
    normalized = {}
    for i in range(ALPHABET_SIZE):
        key = str(i)
        normalized[key] = _dedupe_keep_order(mapping.get(key) or [])
    return normalized


def load_binary_cache():
    global _binary_cache
    if _binary_cache is not None:
        return _binary_cache

    cache = {}
    csv_path = Path(BINARY_MAPPING_CSV)
    if csv_path.exists():
        with open(csv_path, "r", encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                image_name = (row.get("image_name") or "").strip()
                binary_code = (row.get("binary_code") or "").strip()
                if image_name and binary_code and image_name not in cache:
                    cache[image_name] = binary_code

    _binary_cache = cache
    return _binary_cache


def get_raw_image_files():
    raw_path = Path(RAW_IMG_DIR)
    if not raw_path.exists():
        raise RuntimeError(f"Raw image directory does not exist: {RAW_IMG_DIR}")

    allowed = {".jpg", ".jpeg", ".png", ".bmp"}
    files = []
    seen = set()
    for p in raw_path.iterdir():
        if not p.is_file():
            continue
        if p.suffix.lower() not in allowed:
            continue
        norm = str(p.resolve()).lower()
        if norm in seen:
            continue
        seen.add(norm)
        files.append(p)

    files.sort(key=lambda x: x.name)
    return files


def initialize_key_mapping(key: str):
    """
    First time a key is used:
    - Traverse RawImg files
    - Reuse cached binary fingerprints when possible
    - Compute char-group index from key + fingerprint
    - Save index -> filenames mapping into mapping.json
    """
    key_name = safe_key_name(key)
    key_dir = os.path.join(KEYS_BASE_DIR, key_name)
    mapping_file = os.path.join(key_dir, "mapping.json")

    if os.path.exists(mapping_file):
        with open(mapping_file, "r", encoding="utf-8") as f:
            mapping = json.load(f)
        normalized = _normalize_mapping(mapping)
        if normalized != mapping:
            with open(mapping_file, "w", encoding="utf-8") as wf:
                json.dump(normalized, wf, ensure_ascii=False)
        return normalized, False

    os.makedirs(key_dir, exist_ok=True)
    groups = {str(i): [] for i in range(ALPHABET_SIZE)}
    groups_seen = {str(i): set() for i in range(ALPHABET_SIZE)}
    image_files = get_raw_image_files()
    binary_cache = load_binary_cache()

    for img_path in image_files:
        binary_string = binary_cache.get(img_path.name)
        if not binary_string:
            binary_string, _, _ = image_to_binary(str(img_path))
        if not binary_string:
            continue

        idx = compute_char_index(binary_string, key)
        idx_str = str(idx)
        target_name = img_path.name

        if target_name in groups_seen[idx_str]:
            continue
        groups_seen[idx_str].add(target_name)
        groups[idx_str].append(target_name)

    with open(mapping_file, "w", encoding="utf-8") as f:
        json.dump(groups, f, ensure_ascii=False)

    return groups, True


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/upload", methods=["POST"])
def upload_image():
    """HTTP image upload endpoint."""
    if "image" not in request.files:
        return jsonify({"success": False, "error": "No image file provided"}), 400

    file = request.files["image"]
    if file.filename == "":
        return jsonify({"success": False, "error": "Empty filename"}), 400

    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in [".png", ".jpg", ".jpeg", ".gif", ".webp"]:
        return jsonify({"success": False, "error": "Unsupported file type"}), 400

    filename = f"{uuid.uuid4().hex}{ext}"
    save_path = os.path.join(app.config["UPLOAD_FOLDER"], filename)
    file.save(save_path)

    image_url = f"/static/uploads/{filename}"
    return jsonify({"success": True, "url": image_url})


@app.route("/static/uploads/<path:filename>")
def uploaded_file(filename):
    return send_from_directory(app.config["UPLOAD_FOLDER"], filename)


@app.route("/raw_images/<path:filename>")
def raw_image_file(filename):
    return send_from_directory(RAW_IMG_DIR, filename)


@app.route("/api/heartbeat", methods=["POST"])
def heartbeat():
    data = request.get_json(force=True) or {}
    user_id = data.get("userId")
    username = (data.get("username") or "Anonymous").strip() or "Anonymous"
    if not user_id:
        return jsonify({"ok": False, "error": "missing userId"}), 400
    online_users[user_id] = {"username": username, "last_seen": now_ms()}
    return jsonify({"ok": True, "users": get_online_users()})


@app.route("/api/send_message", methods=["POST"])
def api_send_message():
    data = request.get_json(force=True) or {}
    user_id = data.get("userId")
    username = (data.get("username") or "Anonymous").strip() or "Anonymous"
    content = (data.get("content") or "").strip()
    if not user_id or not content:
        return jsonify({"ok": False, "error": "bad payload"}), 400

    msg = make_message(user_id, username, "text", content)
    messages.append(msg)
    prune_history()
    return jsonify({"ok": True, "message": msg})


@app.route("/api/send_image", methods=["POST"])
def api_send_image():
    data = request.get_json(force=True) or {}
    user_id = data.get("userId")
    username = (data.get("username") or "Anonymous").strip() or "Anonymous"
    url = (data.get("url") or "").strip()
    if not user_id or not url:
        return jsonify({"ok": False, "error": "bad payload"}), 400

    msg = make_message(user_id, username, "image", url)
    messages.append(msg)
    prune_history()
    return jsonify({"ok": True, "message": msg})


@app.route("/api/messages")
def api_messages():
    """Poll new messages: /api/messages?since=timestamp_ms"""
    try:
        since = int(request.args.get("since", "0"))
    except ValueError:
        since = 0
    new_msgs = [m for m in messages if m.get("tsMs", 0) > since]
    server_time = now_ms()
    return jsonify({"ok": True, "messages": new_msgs, "serverTime": server_time})


@app.route("/api/assign_key", methods=["POST"])
def api_assign_key():
    """
    Assign a key to a newly joined user:
    - Reuse existing key directories when possible
    - Avoid collisions among currently active users
    """
    data = request.get_json(force=True) or {}
    user_id = data.get("userId")
    username = (data.get("username") or "Anonymous").strip() or "Anonymous"
    if not user_id:
        return jsonify({"ok": False, "error": "missing userId"}), 400

    info = online_users.get(user_id, {})
    info["username"] = username
    online_users[user_id] = info

    if info.get("key"):
        return jsonify({"ok": True, "key": info["key"], "existing": True})

    existing_keys = []
    base = Path(KEYS_BASE_DIR)
    if base.exists():
        for p in base.iterdir():
            if p.is_dir():
                existing_keys.append(p.name)

    cutoff = now_ms() - 25_000
    used_keys_online = {
        uinfo.get("key")
        for uinfo in online_users.values()
        if uinfo.get("last_seen", cutoff) >= cutoff and uinfo.get("key")
    }

    candidates = [k for k in existing_keys if k not in used_keys_online]

    if candidates:
        chosen = random.choice(candidates)
        info["key"] = chosen
        online_users[user_id] = info
        return jsonify({"ok": True, "key": chosen, "existing": True})

    all_used_keys = {
        uinfo.get("key")
        for uinfo in online_users.values()
        if uinfo.get("key")
    }

    while True:
        new_key = generate_random_key()
        if new_key not in all_used_keys and new_key not in existing_keys:
            break

    info["key"] = new_key
    online_users[user_id] = info
    return jsonify({"ok": True, "key": new_key, "existing": False})


@app.route("/api/encrypt_text", methods=["POST"])
def api_encrypt_text():
    """Convert text to encrypted image URL list by key mapping."""
    data = request.get_json(force=True) or {}
    key = (data.get("key") or "").strip()
    text = (data.get("text") or "").strip()
    if not key or not text:
        return jsonify({"ok": False, "error": "missing key or text"}), 400

    try:
        mapping, initialized_now = initialize_key_mapping(key)
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

    key_name = safe_key_name(key)
    key_dir = os.path.join(KEYS_BASE_DIR, key_name)
    use_legacy_key_storage = any(
        os.path.isdir(os.path.join(key_dir, str(i))) for i in range(ALPHABET_SIZE)
    )
    urls = []

    # Reduce duplicates for the same character within one outgoing message.
    used_per_index = {str(i): set() for i in range(ALPHABET_SIZE)}

    for ch in text:
        idx = char_to_index(ch)
        idx_str = str(idx)
        files = mapping.get(idx_str) or []
        if not files:
            continue

        candidates = list(files)
        used = used_per_index[idx_str]

        unused = [f for f in candidates if f not in used]
        if unused:
            file_name = random.choice(unused)
        else:
            file_name = random.choice(candidates)

        used.add(file_name)

        if use_legacy_key_storage:
            url = f"/static/keys/{key_name}/{idx_str}/{file_name}"
        else:
            url = f"/raw_images/{file_name}"
        urls.append(url)

    return jsonify({"ok": True, "images": urls, "initializedNow": initialized_now})


@app.route("/api/decrypt_images", methods=["POST"])
def api_decrypt_images():
    """Decrypt uploaded images into text in upload order."""
    key = (request.form.get("key") or "").strip()
    if not key:
        return jsonify({"ok": False, "error": "missing key"}), 400

    files = request.files.getlist("images")
    if not files:
        return jsonify({"ok": False, "error": "no images received"}), 400

    chars = []
    temp_paths = []

    try:
        for f in files:
            ext = os.path.splitext(f.filename)[1].lower()
            tmp_name = f"{uuid.uuid4().hex}{ext or '.png'}"
            tmp_path = os.path.join(TEMP_DECRYPT_DIR, tmp_name)
            f.save(tmp_path)
            temp_paths.append(tmp_path)

            binary_string, _, _ = image_to_binary(tmp_path)
            if not binary_string:
                continue
            idx = compute_char_index(binary_string, key)
            ch = index_to_char(idx)
            chars.append(ch)
    finally:
        for p in temp_paths:
            try:
                os.remove(p)
            except OSError:
                pass

    text = "".join(chars)
    return jsonify({"ok": True, "text": text})


@app.route("/api/logout", methods=["POST"])
def api_logout():
    """Mark user offline before page close (sendBeacon/fetch)."""
    data = request.get_json(force=True, silent=True) or {}
    user_id = data.get("userId")
    if user_id and user_id in online_users:
        online_users.pop(user_id, None)
    return jsonify({"ok": True})


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5001, debug=True)
