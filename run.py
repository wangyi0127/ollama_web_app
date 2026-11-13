import importlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


if __name__ == "__main__":
    importlib.import_module("ollama_web_app.main").main()
