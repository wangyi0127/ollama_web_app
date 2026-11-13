import argparse
import os
from http.server import ThreadingHTTPServer

from openai import OpenAI

from .database import initialize_database
from .server import OllamaOpenAIHandler


def main():
    parser = argparse.ArgumentParser(
        description="使用 OpenAI Python SDK 通过浏览器访问本地 Ollama。"
    )
    parser.add_argument(
        "--host",
        default=os.environ.get("OLLAMA_WEB_HOST", "127.0.0.1"),
        help="网页服务监听地址（默认仅本机可访问）。",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.environ.get("OLLAMA_WEB_PORT", "8000")),
        help="网页服务端口。",
    )
    parser.add_argument(
        "--ollama-url",
        default=os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434"),
        help="Ollama 服务地址。",
    )
    args = parser.parse_args()
    OllamaOpenAIHandler.ollama_url = args.ollama_url.rstrip("/")
    initialize_database()
    OllamaOpenAIHandler.client = OpenAI(
        base_url=f"{OllamaOpenAIHandler.ollama_url}/v1",
        api_key="ollama",
        timeout=300,
        max_retries=0,
    )

    try:
        server = ThreadingHTTPServer((args.host, args.port), OllamaOpenAIHandler)
    except OSError as exc:
        parser.error(f"无法启动网页服务：{exc}")
    print(f"网页服务已启动：http://{args.host}:{args.port}", flush=True)
    print(f"OpenAI SDK 连接目标：{args.ollama_url}/v1", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n正在关闭网页服务。", flush=True)
    finally:
        server.server_close()
        OllamaOpenAIHandler.client.close()
