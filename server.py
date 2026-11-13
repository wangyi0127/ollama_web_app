import base64
import binascii
import json
import sqlite3
import zipfile
from contextlib import closing
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import unquote, urlsplit
from urllib.request import Request, urlopen
from xml.etree import ElementTree

from openai import OpenAIError

from .attachments import extract_attachment_text
from .auth import AuthMixin
from .chats import ChatsMixin
from .config import (
    ATTACHMENT_TYPES,
    CSS_FILE,
    JS_FILE,
    MAX_ATTACHMENT_BYTES,
    MAX_ATTACHMENT_TEXT_CHARS,
    MAX_ATTACHMENTS,
    MAX_CHAT_REQUEST_BYTES,
    MAX_TOTAL_ATTACHMENT_BYTES,
    PAGE_FILE,
)
from .database import open_database, utc_timestamp


class OllamaOpenAIHandler(
    AuthMixin,
    ChatsMixin,
    BaseHTTPRequestHandler,
):
    ollama_url = "http://127.0.0.1:11434"
    client = None
    protocol_version = "HTTP/1.0"
    server_version = "OllamaOpenAIWeb/1.0"

    def do_GET(self):
        path = urlsplit(self.path).path
        static_files = {
            "/styles.css": (CSS_FILE, "text/css; charset=utf-8"),
            "/app.js": (JS_FILE, "text/javascript; charset=utf-8"),
        }
        if path in static_files:
            file_path, content_type = static_files[path]
            try:
                content = file_path.read_bytes()
            except OSError as exc:
                self._send_json(500, {"error": f"无法读取网页资源：{exc}"})
                return
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(content)))
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(content)
            return

        if path in ("/", "/index.html"):
            try:
                page = PAGE_FILE.read_bytes()
            except OSError as exc:
                self._send_json(500, {"error": f"无法读取网页文件：{exc}"})
                return
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(page)))
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(page)
            return

        if path == "/api/session":
            user = self._current_user()
            self._send_json(
                200,
                {"user": {"username": user["username"]} if user else None},
                {"Cache-Control": "no-store"},
            )
            return

        if path.startswith("/api/") and path != "/api/session":
            user = self._require_user()
            if user is None:
                return

        if path == "/api/models":
            self._get_models()
            return

        if path == "/api/chats":
            self._get_chats(user)
            return

        if path.startswith("/api/chats/"):
            self._get_chat(unquote(path.removeprefix("/api/chats/")), user)
            return

        self._send_json(404, {"error": "未找到该地址。"})

    def do_POST(self):
        path = urlsplit(self.path).path

        if path in ("/api/register", "/api/login", "/api/logout"):
            if not self._check_origin():
                return
            if path == "/api/logout":
                self._logout()
                return
            payload = self._read_json_body()
            if payload is None:
                return
            if path == "/api/register":
                self._register(payload)
            else:
                self._login(payload)
            return

        if path not in ("/api/chats", "/api/chat"):
            self._send_json(404, {"error": "未找到该地址。"})
            return

        if not self._check_origin():
            return
        user = self._require_user()
        if user is None:
            return

        if path == "/api/chats":
            payload = self._read_json_body()
            if payload is not None:
                self._create_chat(payload, user)
            return

        if path == "/api/chat":
            self._post_chat(user)
            return

    def do_DELETE(self):
        path = urlsplit(self.path).path
        prefix = "/api/chats/"
        if not path.startswith(prefix):
            self._send_json(404, {"error": "未找到该地址。"})
            return
        if not self._check_origin():
            return
        user = self._require_user()
        if user is None:
            return

        chat_id = unquote(path.removeprefix(prefix))
        self._delete_chat(chat_id, user)

    def _post_chat(self, user):
        payload = self._read_json_body(MAX_CHAT_REQUEST_BYTES)
        if payload is None:
            return
        model = payload.get("model") if isinstance(payload, dict) else None
        chat_id = payload.get("chat_id") if isinstance(payload, dict) else None
        content = payload.get("message") if isinstance(payload, dict) else None
        raw_attachments = payload.get("attachments", []) if isinstance(payload, dict) else []
        if not isinstance(model, str) or not model.strip() or len(model) > 200:
            self._send_json(400, {"error": "请选择有效的 Ollama 模型。"})
            return
        if not isinstance(chat_id, str) or not chat_id or len(chat_id) > 64:
            self._send_json(400, {"error": "聊天窗口无效，请新建或重新选择聊天。"})
            return
        if not isinstance(content, str) or len(content) > 100_000:
            self._send_json(400, {"error": "消息不能超过 100,000 个字符。"})
            return
        if not isinstance(raw_attachments, list) or len(raw_attachments) > MAX_ATTACHMENTS:
            self._send_json(400, {"error": f"一次最多上传 {MAX_ATTACHMENTS} 个附件。"})
            return
        if not content.strip() and not raw_attachments:
            self._send_json(400, {"error": "请输入消息或选择附件。"})
            return

        attachments = []
        total_attachment_bytes = 0
        for item in raw_attachments:
            if not isinstance(item, dict):
                self._send_json(400, {"error": "附件格式无效。"})
                return
            raw_name = item.get("name")
            encoded_data = item.get("data")
            if not isinstance(raw_name, str) or not isinstance(encoded_data, str):
                self._send_json(400, {"error": "附件名称或内容无效。"})
                return
            filename = raw_name.replace("\\", "/").rsplit("/", 1)[-1].strip()
            if not filename or len(filename) > 200 or any(ord(char) < 32 for char in filename):
                self._send_json(400, {"error": "附件名称无效。"})
                return
            mime_type = ATTACHMENT_TYPES.get(Path(filename).suffix.lower())
            if mime_type is None:
                self._send_json(
                    400,
                    {"error": f"不支持 {filename}。请上传图片、PDF 或 DOCX/XLSX/PPTX 文件。"},
                )
                return
            try:
                data = base64.b64decode(encoded_data, validate=True)
            except (binascii.Error, ValueError):
                self._send_json(400, {"error": f"附件 {filename} 的编码无效。"})
                return
            if not data:
                self._send_json(400, {"error": f"附件 {filename} 为空。"})
                return
            if len(data) > MAX_ATTACHMENT_BYTES:
                self._send_json(413, {"error": f"附件 {filename} 超过 10 MB。"})
                return
            total_attachment_bytes += len(data)
            if total_attachment_bytes > MAX_TOTAL_ATTACHMENT_BYTES:
                self._send_json(413, {"error": "附件总大小不能超过 20 MB。"})
                return
            attachments.append(
                {
                    "name": filename,
                    "mime_type": mime_type,
                    "data": data,
                    "encoded_data": encoded_data,
                }
            )

        if attachments:
            try:
                capabilities = self._get_model_capabilities(model.strip())
            except (HTTPError, URLError, TimeoutError, OSError, ValueError, TypeError) as exc:
                self._send_json(502, {"error": f"无法读取 Ollama 模型能力：{exc}"})
                return
            if "vision" not in capabilities:
                self._send_json(400, {"error": "当前模型不支持多模态附件，请选择支持 vision 的模型。"})
                return

        document_parts = []
        image_attachments = []
        for attachment in attachments:
            if attachment["mime_type"].startswith("image/"):
                image_attachments.append(attachment)
                continue
            try:
                document_parts.append(
                    (
                        attachment["name"],
                        extract_attachment_text(attachment["name"], attachment["data"]),
                    )
                )
            except (ValueError, KeyError, zipfile.BadZipFile, ElementTree.ParseError) as exc:
                self._send_json(400, {"error": f"无法处理附件 {attachment['name']}：{exc}"})
                return
        model_context = "\n\n".join(
            f"[附件文本：{filename}]\n{text}" for filename, text in document_parts
        )
        if len(model_context) > MAX_ATTACHMENT_TEXT_CHARS:
            self._send_json(413, {"error": "附件提取出的文本超过 100,000 个字符，请减少内容或拆分文件。"})
            return
        stored_content = content.strip()
        if attachments:
            attachment_names = "、".join(item["name"] for item in attachments)
            stored_content = f"{stored_content}\n\n附件：{attachment_names}".strip()
        model_content = content.strip()
        if model_context:
            model_content = (
                f"{model_content}\n\n请结合以下附件文本进行分析：\n{model_context}".strip()
            )
        content_parts = [{"type": "text", "text": model_content}]
        content_parts.extend(
            {
                "type": "image_url",
                "image_url": {
                    "url": f"data:{image['mime_type']};base64,{image['encoded_data']}"
                },
            }
            for image in image_attachments
        )
        user_model_content = content_parts if image_attachments else model_content
        if not model_content and image_attachments:
            content_parts[0]["text"] = "请分析所附图片。"
            user_model_content = content_parts

        timestamp = utc_timestamp()
        with closing(open_database()) as database:
            chat = database.execute(
                "SELECT title FROM chats WHERE id = ? AND user_id = ?",
                (chat_id, user["id"]),
            ).fetchone()
            if chat is None:
                self._send_json(404, {"error": "找不到这条聊天记录，请新建聊天窗口。"})
                return
            history = database.execute(
                "SELECT messages.role, messages.content, messages.model_context "
                "FROM messages "
                "JOIN chats ON chats.id = messages.chat_id "
                "WHERE messages.chat_id = ? AND chats.user_id = ? ORDER BY messages.id",
                (chat_id, user["id"]),
            ).fetchall()
            title = chat["title"]
            if title == "新对话":
                title = (
                    " ".join(content.split())[:36]
                    or (attachments[0]["name"] if attachments else "新对话")
                )
            database.execute(
                "INSERT INTO messages (chat_id, role, content, model_context, created_at) "
                "VALUES (?, 'user', ?, ?, ?)",
                (chat_id, stored_content, model_context, timestamp),
            )
            database.execute(
                "UPDATE chats SET title = ?, model = ?, updated_at = ? "
                "WHERE id = ? AND user_id = ?",
                (title, model.strip(), timestamp, chat_id, user["id"]),
            )
            database.commit()

        sdk_messages = [
            {
                "role": "system",
                "content": "你是一个乐于助人的中文助手。请用简洁、准确的中文回答。",
            },
            *[
                {
                    "role": message["role"],
                    "content": "\n\n".join(
                        part
                        for part in (message["content"], message["model_context"])
                        if part
                    ),
                }
                for message in history[-60:]
            ],
            {"role": "user", "content": user_model_content},
        ]
        try:
            stream = self.client.chat.completions.create(
                model=model.strip(),
                messages=sdk_messages,
                stream=True,
            )
        except OpenAIError as exc:
            self._send_json(
                502,
                {"error": f"OpenAI SDK 调用 Ollama 失败：{self._format_openai_error(exc)}"},
            )
            return

        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache, no-transform")
        self.send_header("Connection", "close")
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()

        answer_parts = []
        stream_error = None
        client_disconnected = False
        try:
            for chunk in stream:
                if not chunk.choices:
                    continue
                content = chunk.choices[0].delta.content
                if content:
                    answer_parts.append(content)
                    self._write_event({"content": content})
        except (BrokenPipeError, ConnectionResetError):
            client_disconnected = True
        except OpenAIError as exc:
            stream_error = f"读取模型回复失败：{self._format_openai_error(exc)}"
        finally:
            close = getattr(stream, "close", None)
            if close is not None:
                close()

        answer = "".join(answer_parts)
        if answer:
            try:
                with closing(open_database()) as database:
                    timestamp = utc_timestamp()
                    database.execute(
                        "INSERT INTO messages (chat_id, role, content, created_at) "
                        "SELECT ?, 'assistant', ?, ? WHERE EXISTS ("
                        "SELECT 1 FROM chats WHERE id = ? AND user_id = ?)",
                        (chat_id, answer, timestamp, chat_id, user["id"]),
                    )
                    database.execute(
                        "UPDATE chats SET updated_at = ? WHERE id = ? AND user_id = ?",
                        (timestamp, chat_id, user["id"]),
                    )
                    database.commit()
            except sqlite3.Error as exc:
                stream_error = f"保存聊天记录失败：{exc}"

        if not client_disconnected:
            try:
                if stream_error:
                    self._write_event({"error": stream_error})
                else:
                    self._write_event({"done": True})
            except (BrokenPipeError, ConnectionResetError, OSError):
                pass

    def _get_model_capabilities(self, model_name):
        request = Request(
            f"{self.ollama_url}/api/show",
            data=json.dumps({"name": model_name}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(request, timeout=5) as response:
            payload = json.load(response)
        if not isinstance(payload, dict) or not isinstance(payload.get("capabilities"), list):
            raise TypeError("Ollama 没有返回有效的模型能力信息。")
        return {
            capability
            for capability in payload["capabilities"]
            if isinstance(capability, str)
        }

    @staticmethod
    def _format_openai_error(exc):
        response = getattr(exc, "response", None)
        if response is not None:
            status_code = getattr(response, "status_code", None)
            detail = getattr(response, "text", "").strip()
            if detail:
                if status_code is not None:
                    return f"HTTP {status_code}: {detail[:2000]}"
                return detail[:2000]
        return str(exc)

    def _get_models(self):
        try:
            with urlopen(f"{self.ollama_url}/api/tags", timeout=5) as response:
                payload = json.load(response)
        except HTTPError as exc:
            self._send_json(exc.code, {"error": f"Ollama 返回错误：{exc}"})
            return
        except (URLError, TimeoutError, OSError) as exc:
            self._send_json(502, {"error": f"无法连接本地 Ollama 服务：{exc}"})
            return
        models = payload.get("models") if isinstance(payload, dict) else None
        if not isinstance(models, list):
            self._send_json(502, {"error": "Ollama 返回了无效的模型列表。"})
            return
        for model in models:
            if not isinstance(model, dict) or not isinstance(model.get("name"), str):
                self._send_json(502, {"error": "Ollama 返回了无效的模型信息。"})
                return
            try:
                model["capabilities"] = sorted(
                    self._get_model_capabilities(model["name"])
                )
            except (HTTPError, URLError, TimeoutError, OSError, ValueError, TypeError) as exc:
                model["capabilities"] = []
                model["capabilities_error"] = str(exc)
        self._send_json(200, {"models": models})

    def _send_json(self, status, payload, headers=None):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Content-Type-Options", "nosniff")
        for name, value in (headers or {}).items():
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(body)

    def _write_event(self, payload):
        data = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        self.wfile.write(f"data: {data}\n\n".encode())
        self.wfile.flush()

    def log_message(self, format_string, *args):
        print(f"[{self.log_date_time_string()}] {format_string % args}")
