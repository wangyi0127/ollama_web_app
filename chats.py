import uuid
from contextlib import closing

from .database import open_database, utc_timestamp


class ChatsMixin:
    def _delete_chat(self, chat_id, user):
        if not chat_id or len(chat_id) > 64 or "/" in chat_id:
            self._send_json(404, {"error": "找不到这条聊天记录。"})
            return
        with closing(open_database()) as database:
            result = database.execute(
                "DELETE FROM chats WHERE id = ? AND user_id = ?",
                (chat_id, user["id"]),
            )
            database.commit()
        if result.rowcount == 0:
            self._send_json(404, {"error": "找不到这条聊天记录。"})
            return
        self._send_json(200, {"deleted": True})

    def _get_chats(self, user):
        with closing(open_database()) as database:
            chats = database.execute(
                "SELECT id, title, model, created_at, updated_at "
                "FROM chats WHERE user_id = ? "
                "ORDER BY updated_at DESC, created_at DESC",
                (user["id"],),
            ).fetchall()
        self._send_json(200, {"chats": [dict(chat) for chat in chats]})

    def _get_chat(self, chat_id, user):
        if not chat_id or len(chat_id) > 64:
            self._send_json(404, {"error": "找不到这条聊天记录。"})
            return
        with closing(open_database()) as database:
            chat = database.execute(
                "SELECT id, title, model, created_at, updated_at "
                "FROM chats WHERE id = ? AND user_id = ?",
                (chat_id, user["id"]),
            ).fetchone()
            if chat is None:
                self._send_json(404, {"error": "找不到这条聊天记录。"})
                return
            messages = database.execute(
                "SELECT role, content, created_at FROM messages "
                "WHERE chat_id = ? ORDER BY id",
                (chat_id,),
            ).fetchall()
        self._send_json(
            200,
            {"chat": dict(chat), "messages": [dict(message) for message in messages]},
        )

    def _create_chat(self, payload, user):
        model = payload.get("model", "") if isinstance(payload, dict) else ""
        if not isinstance(model, str) or len(model) > 200:
            self._send_json(400, {"error": "模型名称无效。"})
            return
        chat_id = uuid.uuid4().hex
        timestamp = utc_timestamp()
        with closing(open_database()) as database:
            database.execute(
                "INSERT INTO chats (id, user_id, title, model, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (chat_id, user["id"], "新对话", model.strip(), timestamp, timestamp),
            )
            database.commit()
        self._send_json(
            201,
            {
                "chat": {
                    "id": chat_id,
                    "title": "新对话",
                    "model": model.strip(),
                    "created_at": timestamp,
                    "updated_at": timestamp,
                }
            },
        )
