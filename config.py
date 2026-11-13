import re
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PAGE_FILE = Path(__file__).resolve().parent / "static" / "openai_chat.html"
CSS_FILE = PAGE_FILE.with_name("styles.css")
JS_FILE = PAGE_FILE.with_name("app.js")
DATABASE_FILE = Path(__file__).resolve().parent / "chat_data" / "chat_history.sqlite3"

MAX_REQUEST_BYTES = 1_000_000
MAX_CHAT_REQUEST_BYTES = 28_000_000
MAX_ATTACHMENT_BYTES = 10_000_000
MAX_TOTAL_ATTACHMENT_BYTES = 20_000_000
MAX_ATTACHMENTS = 5
MAX_ATTACHMENT_TEXT_CHARS = 100_000
MAX_OFFICE_ARCHIVE_BYTES = 40_000_000
MAX_OFFICE_XML_BYTES = 5_000_000

ATTACHMENT_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".txt": "text/plain",
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}

SESSION_COOKIE = "ollama_session"
SESSION_TTL_SECONDS = 30 * 24 * 60 * 60
PASSWORD_HASH_ITERATIONS = 600_000
USERNAME_PATTERN = re.compile(r"[A-Za-z0-9_.-]{3,32}\Z")
