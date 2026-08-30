from pathlib import Path
import sys

import pytest


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def test_discord_bot_registers_shoplifting_slash_command(monkeypatch):
    pytest.importorskip("discord")
    from discord.ext import commands
    from services.discord_bot_service import serve_discord_bot

    captured = {}

    def fake_run(bot, *_args, **_kwargs):
        captured["bot"] = bot

    monkeypatch.setattr(commands.Bot, "run", fake_run)

    serve_discord_bot(token="test-token")

    assert captured["bot"].tree.get_command("ti_shoplifting") is not None