from pathlib import Path

from birt_bot_lite.bot import run_bot


if __name__ == "__main__":
    run_bot(Path(__file__).resolve().parent)
