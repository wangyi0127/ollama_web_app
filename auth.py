import hashlib
import hmac
import json
import secrets
import sqlite3
import uuid
from contextlib import closing
from datetime import datetime, timedelta, timezone
from http.cookies import CookieError, SimpleCookie
from urllib.parse import urlsplit

from .config import (
    MAX_REQUEST_BYTES,
    PASSWORD_HASH_ITERATIONS,
    SESSION_COOKIE,
    SESSION_TTL_SECONDS,
    USERNAME_PATTERN,
)
from .database import open_database, utc_timestamp


class AuthMixin:
    def _check_origin(self):
        origin = self.headers.get("Origin")
        if not origin:
            return True
        if urlsplit(origin).netloc == self.headers.get("Host"):
            return True
        self._send_json(403, {"error": "跨站请求已拒绝。"})
        return False

    def _current_user(self):
        cookie = SimpleCookie()
        try:
            cookie.load(self.headers.get("Cookie", ""))
        except CookieError:
            return None
        session_cookie = cookie.get(SESSION_COOKIE)
        if session_cookie is None or not session_cookie.value:
            return None
        token_hash = hashlib.sha256(session_cookie.value.encode("utf-8")).hexdigest()
        with closing(open_database()) as database:
            user = database.execute(
                "SELECT users.id, users.username FROM sessions "
                "JOIN users ON users.id = sessions.user_id "
                "WHERE sessions.token_hash = ? AND sessions.expires_at > ?",
                (token_hash, utc_timestamp()),
            ).fetchone()
        return user

    def _require_user(self):
        user = self._current_user()
        if user is None:
            self._send_json(
                401,
                {"error": "登录状态已失效，请重新登录。"},
                {"Cache-Control": "no-store"},
            )
        return user

    def _register(self, payload):
        username = payload.get("username") if isinstance(payload, dict) else None
        password = payload.get("password") if isinstance(payload, dict) else None
        if not isinstance(username, str) or not USERNAME_PATTERN.fullmatch(username):
            self._send_json(400, {"error": "用户名需为 3–32 位字母、数字、点、下划线或连字符。"})
            return
        if not isinstance(password, str) or not 8 <= len(password) <= 128:
            self._send_json(400, {"error": "密码长度需为 8–128 个字符。"})
            return

        salt = secrets.token_bytes(16)
        password_hash = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), salt, PASSWORD_HASH_ITERATIONS
        )
        user = {
            "id": uuid.uuid4().hex,
            "username": username.lower(),
        }
        try:
            with closing(open_database()) as database:
                database.execute(
                    "INSERT INTO users (id, username, password_salt, password_hash, created_at) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (
                        user["id"],
                        user["username"],
                        salt,
                        password_hash,
                        utc_timestamp(),
                    ),
                )
                database.commit()
        except sqlite3.IntegrityError:
            self._send_json(409, {"error": "该用户名已被注册。"})
            return
        self._issue_session(user, 201)

    def _login(self, payload):
        username = payload.get("username") if isinstance(payload, dict) else None
        password = payload.get("password") if isinstance(payload, dict) else None
        if not isinstance(username, str) or not USERNAME_PATTERN.fullmatch(username):
            self._send_json(401, {"error": "用户名或密码不正确。"})
            return
        if not isinstance(password, str) or len(password) > 128:
            self._send_json(401, {"error": "用户名或密码不正确。"})
            return

        with closing(open_database()) as database:
            user = database.execute(
                "SELECT id, username, password_salt, password_hash "
                "FROM users WHERE username = ?",
                (username.lower(),),
            ).fetchone()
        if user is None:
            hashlib.pbkdf2_hmac(
                "sha256", password.encode("utf-8"), bytes(16), PASSWORD_HASH_ITERATIONS
            )
            self._send_json(401, {"error": "用户名或密码不正确。"})
            return

        candidate = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            user["password_salt"],
            PASSWORD_HASH_ITERATIONS,
        )
        if not hmac.compare_digest(candidate, user["password_hash"]):
            self._send_json(401, {"error": "用户名或密码不正确。"})
            return
        self._issue_session(user, 200)

    def _issue_session(self, user, status):
        token = secrets.token_urlsafe(32)
        token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
        created_at = datetime.now(timezone.utc)
        expires_at = (created_at + timedelta(seconds=SESSION_TTL_SECONDS)).isoformat(
            timespec="seconds"
        )
        with closing(open_database()) as database:
            database.execute(
                "DELETE FROM sessions WHERE expires_at <= ?",
                (utc_timestamp(),),
            )
            database.execute(
                "INSERT INTO sessions (token_hash, user_id, created_at, expires_at) "
                "VALUES (?, ?, ?, ?)",
                (token_hash, user["id"], created_at.isoformat(timespec="seconds"), expires_at),
            )
            database.commit()
        cookie = (
            f"{SESSION_COOKIE}={token}; HttpOnly; SameSite=Strict; Path=/; "
            f"Max-Age={SESSION_TTL_SECONDS}"
        )
        self._send_json(
            status,
            {"user": {"username": user["username"]}},
            {"Set-Cookie": cookie, "Cache-Control": "no-store"},
        )

    def _logout(self):
        cookie = SimpleCookie()
        try:
            cookie.load(self.headers.get("Cookie", ""))
        except CookieError:
            pass
        session_cookie = cookie.get(SESSION_COOKIE)
        if session_cookie is not None and session_cookie.value:
            token_hash = hashlib.sha256(session_cookie.value.encode("utf-8")).hexdigest()
            with closing(open_database()) as database:
                database.execute("DELETE FROM sessions WHERE token_hash = ?", (token_hash,))
                database.commit()
        self._send_json(
            200,
            {"ok": True},
            {
                "Set-Cookie": f"{SESSION_COOKIE}=; HttpOnly; SameSite=Strict; Path=/; Max-Age=0",
                "Cache-Control": "no-store",
            },
        )

    def _read_json_body(self, max_bytes=MAX_REQUEST_BYTES):
        try:
            content_length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            self._send_json(400, {"error": "请求长度无效。"})
            return None
        if content_length < 1 or content_length > max_bytes:
            self._send_json(413, {"error": "请求内容为空或超过允许的大小。"})
            return None

        try:
            return json.loads(self.rfile.read(content_length))
        except (json.JSONDecodeError, UnicodeDecodeError):
            self._send_json(400, {"error": "请求必须是有效的 JSON。"})
            return None
