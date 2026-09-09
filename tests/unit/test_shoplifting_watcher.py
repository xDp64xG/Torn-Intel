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


def test_any_trigger_areas_alert_on_each_newly_disabled_obstacle():
    payload = {
        "shoplifting": {
            "big_als": [
                {"title": "Four cameras", "disabled": True},
                {"title": "Two guards", "disabled": False},
            ]
        }
    }

    should_alert, state, titles = ShopliftingWatcher.evaluate_area(payload, "big_als", None)
    assert should_alert is True
    assert titles == ["Four cameras"]

    should_alert, state, titles = ShopliftingWatcher.evaluate_area(payload, "big_als", state)
    assert should_alert is False

    payload["shoplifting"]["big_als"][1]["disabled"] = True
    should_alert, _, titles = ShopliftingWatcher.evaluate_area(payload, "big_als", state)
    assert should_alert is True
    assert titles == ["Two guards"]


def test_pharmacy_alert_text_lists_disabled_obstacles():
    text = ShopliftingWatcher.format_alert(area="pharmacy", titles=["Checkpoint"])

    assert text == "Pharmacy has a disabled obstacle.\nDisabled: Checkpoint"


def test_trigger_override_requires_every_watched_obstacle():
    payload = {
        "shoplifting": {
            "super_store": [
                {"title": "Two cameras", "disabled": False},
                {"title": "Checkpoint", "disabled": True},
            ]
        }
    }

    should_alert, _, _ = ShopliftingWatcher.evaluate_area(payload, "super_store", None, trigger="all")
    assert should_alert is False

    payload["shoplifting"]["super_store"][0]["disabled"] = True
    should_alert, _, titles = ShopliftingWatcher.evaluate_area(payload, "super_store", None, trigger="all")
    assert should_alert is True
    assert titles == ["Two cameras", "Checkpoint"]


def test_watch_list_limits_alerts_to_selected_obstacles():
    payload = {
        "shoplifting": {
            "cyber_force": [
                {"title": "Two cameras", "disabled": True},
                {"title": "One guard", "disabled": False},
            ]
        }
    }

    should_alert, _, _ = ShopliftingWatcher.evaluate_area(payload, "cyber_force", None, watch="One guard")
    assert should_alert is False

    should_alert, _, titles = ShopliftingWatcher.evaluate_area(payload, "cyber_force", None, watch="Two cameras")
    assert should_alert is True
    assert titles == ["Two cameras"]


def test_area_lookup_tolerates_torn_key_casing():
    payload = {"shoplifting": {"Bits_n_bobs": [{"title": "Two cameras", "disabled": True}]}}

    assert ShopliftingWatcher.disabled_titles(payload, "bits_n_bobs") == ["Two cameras"]


def test_parse_watch_list_splits_on_common_separators():
    assert ShopliftingWatcher.parse_watch_list("Checkpoint, Two cameras;One guard") == (
        "Checkpoint",
        "Two cameras",
        "One guard",
    )
    assert ShopliftingWatcher.parse_watch_list("") == ()


def test_security_kind_triggers_only_watch_their_own_security():
    payload = {
        "shoplifting": {
            "cyber_force": [
                {"title": "Two cameras", "disabled": True},
                {"title": "One guard", "disabled": False},
            ]
        }
    }

    should_alert, _, titles = ShopliftingWatcher.evaluate_area(payload, "cyber_force", None, trigger="cameras")
    assert should_alert is True
    assert titles == ["Two cameras"]

    should_alert, _, _ = ShopliftingWatcher.evaluate_area(payload, "cyber_force", None, trigger="guards")
    assert should_alert is False

    payload["shoplifting"]["cyber_force"][1]["disabled"] = True
    should_alert, _, titles = ShopliftingWatcher.evaluate_area(payload, "cyber_force", None, trigger="guards")
    assert should_alert is True
    assert titles == ["One guard"]


def test_security_kind_alert_text():
    assert ShopliftingWatcher.alert_message(area="cyber_force", trigger="cameras") == "Cyber Force cameras are down."
    assert ShopliftingWatcher.alert_message(area="super_store", trigger="checkpoint") == "Super Store checkpoint is down."


def test_available_triggers_match_the_security_each_area_has():
    assert ShopliftingWatcher.available_triggers("cyber_force") == ("any", "all", "cameras", "guards")
    assert ShopliftingWatcher.available_triggers("super_store") == ("any", "all", "cameras", "checkpoint")
    assert ShopliftingWatcher.available_triggers("bits_n_bobs") == ("any",)


def test_unavailable_trigger_falls_back_to_the_area_default():
    assert ShopliftingWatcher.area_trigger("bits_n_bobs", "guards") == "any"
    assert ShopliftingWatcher.area_trigger("cyber_force", "guards") == "guards"


def test_validate_watch_list_reports_unknown_security():
    titles, unknown = ShopliftingWatcher.validate_watch_list("big_als", "four cameras, One guard")

    assert titles == ("Four cameras",)
    assert unknown == ("One guard",)