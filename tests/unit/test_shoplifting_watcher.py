from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.shoplifting_watcher import ShopliftingWatcher
from cli.parser import build_parser


def test_shoplifting_defaults_to_start_when_only_options_are_provided():
    args = build_parser().parse_args(
        ["shoplifting", "--mention", "<@&1492151685378740308>", "--webhook-url", "https://discord.com/api/webhooks/example"]
    )

    assert args.action == "start"


def test_jewelry_store_requires_both_obstacles_disabled():
    clear_payload = {
        "shoplifting": {
            "jewelry_store": [
                {"title": "Three cameras", "disabled": True},
                {"title": "One guard", "disabled": True},
            ]
        }
    }
    blocked_payload = {
        "shoplifting": {
            "jewelry_store": [
                {"title": "Three cameras", "disabled": True},
                {"title": "One guard", "disabled": False},
            ]
        }
    }

    assert ShopliftingWatcher._jewelry_store_is_clear(clear_payload) is True
    assert ShopliftingWatcher._jewelry_store_is_clear(blocked_payload) is False
    assert ShopliftingWatcher._jewelry_store_is_clear({"shoplifting": {"jewelry_store": []}}) is False


def test_shoplifting_alert_message_uses_custom_or_default_text():
    assert ShopliftingWatcher.alert_message("  Jewelry is ready.  ") == "Jewelry is ready."
    assert ShopliftingWatcher.alert_message() == "Jewelry Store is clear for shoplifting."