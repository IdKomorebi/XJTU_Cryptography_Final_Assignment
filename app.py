import os
import uuid
import time
import json
import shutil
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

os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(KEYS_BASE_DIR, exist_ok=True)
os.makedirs(TEMP_DECRYPT_DIR, exist_ok=True)

ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZ ,."
ALPHABET_SIZE = len(ALPHABET)
KEY_CHARSET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"

app = Flask(__name__)
app.config["SECRET_KEY"] = "dev-secret-key"
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER

# 聊天历史（内存）
messages = []
MAX_HISTORY = 200

# 在线用户：user_id -> {"username": ..., "last_seen": timestamp}
online_users = {}


def now_ms():
    return int(time.time() * 1000)


def make_message(user_id, username, msg_type, content):
    """
    构造消息对象
    """
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
    # 心跳间隔约 7-8 秒，这里给一个稍微宽松的阈值
    cutoff = now_ms() - 25_000  # 25 秒没心跳就认为离线
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
    # 其他字符统一映射为空格
    return ALPHABET.index(" ")


def index_to_char(idx: int) -> str:
    return ALPHABET[idx % ALPHABET_SIZE]


def safe_key_name(key: str) -> str:
    # 简单处理目录名安全问题
    return "".join(c if c.isalnum() or c in "-_." else "_" for c in key) or "default"


def compute_char_index(binary_code: str, key: str) -> int:
    data = (key + ":" + (binary_code or "")).encode("utf-8")
    digest = hashlib.sha256(data).digest()
    value = int.from_bytes(digest[:4], "big")
    return value % ALPHABET_SIZE


def initialize_key_mapping(key: str):
    """
    第一次使用某个密钥时：
    - 遍历 RawImg 下所有图片
    - 计算 32 位编码，再结合密钥做哈希 %29 得到字符下标
    - 在 static/keys/<key_name>/<0-28>/ 里复制图片
    - 在 mapping.json 中保存索引到文件列表的映射
    """
    key_name = safe_key_name(key)
    key_dir = os.path.join(KEYS_BASE_DIR, key_name)
    mapping_file = os.path.join(key_dir, "mapping.json")

    if os.path.exists(mapping_file):
        with open(mapping_file, "r", encoding="utf-8") as f:
            return json.load(f), False

    os.makedirs(key_dir, exist_ok=True)
    groups = {str(i): [] for i in range(ALPHABET_SIZE)}

    raw_path = Path(RAW_IMG_DIR)
    if not raw_path.exists():
        raise RuntimeError(f"原始图片目录不存在: {RAW_IMG_DIR}")

    exts = [".jpg", ".jpeg", ".png", ".bmp"]
    image_files = []
    for ext in exts:
        image_files.extend(raw_path.glob(f"*{ext}"))
        image_files.extend(raw_path.glob(f"*{ext.upper()}"))

    image_files = sorted(image_files, key=lambda x: x.name)

    for img_path in image_files:
        binary_string, _, _ = image_to_binary(str(img_path))
        if not binary_string:
            continue
        idx = compute_char_index(binary_string, key)
        idx_str = str(idx)

        target_dir = os.path.join(key_dir, idx_str)
        os.makedirs(target_dir, exist_ok=True)
        target_name = img_path.name
        target_path = os.path.join(target_dir, target_name)

        if not os.path.exists(target_path):
            shutil.copy2(str(img_path), target_path)

        groups[idx_str].append(target_name)

    with open(mapping_file, "w", encoding="utf-8") as f:
        json.dump(groups, f, ensure_ascii=False)

    return groups, True


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/upload", methods=["POST"])
def upload_image():
    """
    HTTP 图片上传接口
    前端通过 FormData POST 文件，返回图片 URL
    """
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


@app.route("/api/heartbeat", methods=["POST"])
def heartbeat():
    data = request.get_json(force=True) or {}
    user_id = data.get("userId")
    username = (data.get("username") or "匿名用户").strip() or "匿名用户"
    if not user_id:
        return jsonify({"ok": False, "error": "missing userId"}), 400
    online_users[user_id] = {"username": username, "last_seen": now_ms()}
    return jsonify({"ok": True, "users": get_online_users()})


@app.route("/api/send_message", methods=["POST"])
def api_send_message():
    data = request.get_json(force=True) or {}
    user_id = data.get("userId")
    username = (data.get("username") or "匿名用户").strip() or "匿名用户"
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
    username = (data.get("username") or "匿名用户").strip() or "匿名用户"
    url = (data.get("url") or "").strip()
    if not user_id or not url:
        return jsonify({"ok": False, "error": "bad payload"}), 400

    msg = make_message(user_id, username, "image", url)
    messages.append(msg)
    prune_history()
    return jsonify({"ok": True, "message": msg})


@app.route("/api/messages")
def api_messages():
    """
    轮询获取新消息:
    /api/messages?since=timestamp_ms
    """
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
    为新登录用户分配密钥：
    - 优先从已有密钥中随机分配，保证当前在线用户之间不重复
    - 如果不够分，则生成新的随机密钥
    """
    data = request.get_json(force=True) or {}
    user_id = data.get("userId")
    username = (data.get("username") or "匿名用户").strip() or "匿名用户"
    if not user_id:
        return jsonify({"ok": False, "error": "missing userId"}), 400

    # 更新/记录在线用户（此处不设置 last_seen，只记录用户名和密钥）
    info = online_users.get(user_id, {})
    info["username"] = username
    online_users[user_id] = info

    # 如果该用户之前已经有密钥，就直接返回
    if info.get("key"):
        return jsonify({"ok": True, "key": info["key"], "existing": True})

    # 已存在的密钥目录（历史上用过的）
    existing_keys = []
    base = Path(KEYS_BASE_DIR)
    if base.exists():
        for p in base.iterdir():
            if p.is_dir():
                existing_keys.append(p.name)

    # 当前在线用户已经占用的密钥
    cutoff = now_ms() - 15_000
    used_keys = {
        uinfo.get("key")
        for uinfo in online_users.values()
        if uinfo.get("last_seen", cutoff) >= cutoff and uinfo.get("key")
    }

    candidates = [k for k in existing_keys if k not in used_keys]

    if candidates:
        chosen = random.choice(candidates)
        info["key"] = chosen
        online_users[user_id] = info
        return jsonify({"ok": True, "key": chosen, "existing": True})

    # 没有可用旧密钥，则生成新的随机密钥
    new_key = generate_random_key()
    info["key"] = new_key
    online_users[user_id] = info
    return jsonify({"ok": True, "key": new_key, "existing": False})


@app.route("/api/encrypt_text", methods=["POST"])
def api_encrypt_text():
    """
    文本 -> 图片 URL 列表（根据密钥和 RawImg 映射）
    """
    data = request.get_json(force=True) or {}
    key = (data.get("key") or "").strip()
    text = (data.get("text") or "").strip()
    if not key or not text:
        return jsonify({"ok": False, "error": "缺少密钥或文本"}), 400

    try:
        mapping, initialized_now = initialize_key_mapping(key)
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

    key_name = safe_key_name(key)
    urls = []

    # 为了一个消息内部尽量不用同一字符的同一图片，这里为每个字符下标维护一个已使用列表
    used_per_index = {str(i): set() for i in range(ALPHABET_SIZE)}

    for ch in text:
        idx = char_to_index(ch)
        idx_str = str(idx)
        files = mapping.get(idx_str) or []
        if not files:
            continue

        candidates = list(files)
        used = used_per_index[idx_str]

        # 优先从“未使用”集合里随机选，如果都用过了就允许重复
        unused = [f for f in candidates if f not in used]
        if unused:
            file_name = random.choice(unused)
        else:
            file_name = random.choice(candidates)

        used.add(file_name)

        url = f"/static/keys/{key_name}/{idx_str}/{file_name}"
        urls.append(url)

    return jsonify({"ok": True, "images": urls, "initializedNow": initialized_now})


@app.route("/api/decrypt_images", methods=["POST"])
def api_decrypt_images():
    """
    上传图片 + 密钥 -> 解密出文本（按上传顺序）
    """
    key = (request.form.get("key") or "").strip()
    if not key:
        return jsonify({"ok": False, "error": "缺少密钥"}), 400

    files = request.files.getlist("images")
    if not files:
        return jsonify({"ok": False, "error": "没有接收到图片"}), 400

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
    """
    页面关闭前通过 sendBeacon / fetch 告知服务器该用户下线
    """
    data = request.get_json(force=True, silent=True) or {}
    user_id = data.get("userId")
    if user_id and user_id in online_users:
        online_users.pop(user_id, None)
    return jsonify({"ok": True})


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5001, debug=True)

