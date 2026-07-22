import argparse


def build_parser():

    parser = argparse.ArgumentParser(
        prog="TornIntel"
    )

    sub = parser.add_subparsers(dest="command")

    sync = sub.add_parser("sync")

    sync.add_argument(
        "module",
        choices=[
            "attacks",
            "chains",
            "rankedwars",
            "armoury",
            "companies",
            "crimes",
            "revives"
        ]
    )

    sync.add_argument(
        "--mode",
        choices=["backfill", "live", "search"],
        default="backfill",
        help="backfill: walk history once. live: catch up from last sync. search: one-off query."
    )

    sync.add_argument(
        "--filters",
        choices=["incoming", "outgoing"],
        default=None
    )

    sync.add_argument(
        "--from",
        dest="from_timestamp",
        type=int,
        default=None
    )

    sync.add_argument(
        "--to",
        dest="to_timestamp",
        type=int,
        default=None
    )

    sync.add_argument(
        "--pages",
        type=int,
        default=50,
        help="Max pages for modules that support page backfill (used by crimes backfill, default: 50)"
    )

    # Search-specific arguments (for --mode search)
    sync.add_argument(
        "--attacker",
        "--reviver",
        type=int,
        default=None,
        help="Search by attacker/reviver player ID"
    )

    sync.add_argument(
        "--attacker-name",
        "--reviver-name",
        dest="attacker_name",
        type=str,
        default=None,
        help="Search by attacker/reviver name (case-insensitive)"
    )

    sync.add_argument(
        "--defender",
        "--target",
        type=int,
        default=None,
        help="Search by defender/target player ID"
    )

    sync.add_argument(
        "--defender-name",
        "--target-name",
        dest="defender_name",
        type=str,
        default=None,
        help="Search by defender/target name (case-insensitive)"
    )

    sync.add_argument(
        "--chain",
        type=int,
        default=None,
        help="Search by chain hit number"
    )

    sync.add_argument(
        "--result",
        type=str,
        default=None,
        help="Search by attack result (Attacked, Mugged, Hospitalized, Lost, ...)"
    )

    sync.add_argument(
        "--limit",
        type=int,
        default=25,
        help="Max number of results to return (default: 25)"
    )

    sync.add_argument(
        "--oldest",
        action="store_true",
        default=False,
        help="Show oldest attacks first (default: newest first)"
    )

    # Armoury-specific search arguments
    sync.add_argument(
        "--player",
        type=str,
        default=None,
        help="Search armoury by player name (case-insensitive)"
    )

    sync.add_argument(
        "--item",
        type=str,
        default=None,
        help="Search armoury by item name (case-insensitive)"
    )

    sync.add_argument(
        "--category",
        type=str,
        default=None,
        help="Search armoury by item category (Medical, Drug, Utility, etc.)"
    )

    sync.add_argument(
        "--event-type",
        dest="event_type",
        type=str,
        default=None,
        help="Search armoury by event type (used, deposited, filled, loaned, received)"
    )

    report = sub.add_parser("report")

    report.add_argument(
        "module",
        choices=[
            "attacks",
            "chains",
            "rankedwars",
            "armoury",
            "companies",
            "crimes",
            "revives"
        ]
    )

    report.add_argument(
        "report_type",
        choices=[
            "chain_hit",
            "chain_stats",
            "chain_leaderboard",
            "chain_player",
            "war_stats",
            "war_leaderboard",
            "war_player",
            "war_payout",
            "war_costs",
            "chain_costs",
            "player_usage",
            "category",
            "medical_summary",
            "loan_tracker",
            "oc_item_audit",
            "oc_cpr",
            "oc_outside",
        ],
        help="chain_hit: find who made the Nth hit. "
             "chain_stats: overall stats with top attackers. "
             "chain_leaderboard: ranked faction members. "
             "chain_player: all attacks by a specific player. "
             "war_stats: overall war statistics. "
             "war_leaderboard: ranked attackers in a war. "
             "war_player: all attacks by a player in a war. "
             "war_costs: armoury costs during a ranked war. "
             "chain_costs: armoury costs during a chain. "
             "player_usage: armoury usage by player. "
             "category: armoury usage by category. "
             "medical_summary: medical items summary. "
             "loan_tracker: outstanding armoury loans with rough return ETA. "
             "oc_item_audit: OC required item holder audit. "
             "oc_cpr: OC checkpoint pass rate summary against rules. "
             "oc_outside: current faction members not assigned to active OCs."
    )

    report.add_argument(
        "--category",
        type=str,
        default=None,
        help="Item category (required for category report)"
    )

    report.add_argument(
        "--chain_id",
        type=int,
        default=None,
        help="Chain ID to analyze (for chain reports)"
    )

    report.add_argument(
        "--war_id",
        type=int,
        default=None,
        help="War ID to analyze (for war reports)"
    )

    report.add_argument(
        "--hit_number",
        type=int,
        default=None,
        help="Hit number to find (required for chain_hit)"
    )

    report.add_argument(
        "--player",
        type=str,
        default=None,
        help="Player name to look up (required for chain_player)"
    )

    report.add_argument(
        "--item",
        type=str,
        default=None,
        help="Item name filter (used by armoury loan_tracker)"
    )

    report.add_argument(
        "--top_n",
        type=int,
        default=10,
        help="Number of top attackers to show in chain_stats (default: 10)"
    )

    report.add_argument(
        "--limit",
        type=int,
        default=50,
        help="Max rows for report types that list multiple entries (default: 50)"
    )

    crime_rules = sub.add_parser("crime_rules")

    crime_rules.add_argument(
        "action",
        choices=[
            "show",
            "set_tier",
            "set_crime",
            "set_position",
            "remove_crime",
        ],
        help="show: print current rules. set_tier: set default min CPR for tier 1-10. set_crime: set default for a specific crime. set_position: set position-specific minimum for a crime. remove_crime: remove a crime override."
    )

    crime_rules.add_argument(
        "--tier",
        type=int,
        default=None,
        help="Tier number 1-10 (required for set_tier)."
    )

    crime_rules.add_argument(
        "--crime-name",
        dest="crime_name",
        type=str,
        default=None,
        help="Crime name for override actions (set_crime, set_position, remove_crime)."
    )

    crime_rules.add_argument(
        "--position",
        type=str,
        default=None,
        help="Position name for set_position action."
    )

    crime_rules.add_argument(
        "--min-cpr",
        dest="min_cpr",
        type=int,
        default=None,
        help="Minimum CPR percentage for set_tier/set_crime/set_position actions."
    )

    report.add_argument(
        "--stacking-days",
        dest="stacking_days",
        type=int,
        default=0,
        help="Pre-window days to include Xanax stacking costs for war_costs/chain_costs (default: 0)"
    )

    report.add_argument(
        "--temp-return-days",
        dest="temp_return_days",
        type=int,
        default=2,
        help="Post-window days to count Temporary returns when estimating net temporary usage (default: 2)"
    )

    report.add_argument(
        "--total_payout",
        type=float,
        default=None,
        help="Total payout amount (for war_payout report)"
    )

    report.add_argument(
        "--xanax_cost",
        type=float,
        default=0,
        help="Xanax cost to deduct (for war_payout report, default: 0)"
    )

    report.add_argument(
        "--faction_cut",
        type=float,
        default=0,
        help="Faction cut percentage 0-100 (for war_payout report, default: 0)"
    )

    report.add_argument(
        "--bounty_cost",
        type=float,
        default=0,
        help="Bounty cost to deduct (for war_payout report, default: 0)"
    )

    report.add_argument(
        "--per_assist",
        type=float,
        default=0,
        help="Payment per assist on opposing faction (for war_payout report, default: 0)"
    )

    report.add_argument(
        "--pay_outside_hits",
        type=int,
        default=0,
        choices=[0, 1],
        help="Pay for hits outside war (1=yes, 0=no, default: 0)"
    )

    payout = sub.add_parser("payout")

    payout.add_argument(
        "module",
        choices=[
            "rankedwars",
        ]
    )

    payout.add_argument(
        "--war_id",
        type=int,
        required=True,
        help="War ID to calculate payouts for"
    )

    payout.add_argument(
        "--total_payout",
        type=float,
        required=True,
        help="Total payout amount"
    )

    payout.add_argument(
        "--xanax_cost",
        type=float,
        default=0,
        help="Xanax cost to deduct (default: 0)"
    )

    payout.add_argument(
        "--faction_cut",
        type=float,
        default=0,
        help="Faction cut percentage 0-100 (default: 0)"
    )

    payout.add_argument(
        "--bounty_cost",
        type=float,
        default=0,
        help="Bounty cost to deduct (default: 0)"
    )

    payout.add_argument(
        "--per_assist",
        type=float,
        default=0,
        help="Payment per assist on opposing faction (default: 0)"
    )

    payout.add_argument(
        "--pay_outside_hits",
        type=int,
        default=0,
        choices=[0, 1],
        help="Pay for hits outside war (1=yes, 0=no, default: 0)"
    )

    payout_csv = sub.add_parser("payout_csv")

    payout_csv.add_argument(
        "module",
        choices=[
            "rankedwars",
        ]
    )

    payout_csv.add_argument(
        "--war_id",
        type=int,
        required=True,
        help="War ID to calculate payouts for"
    )

    payout_csv.add_argument(
        "--csv_path",
        type=str,
        required=True,
        help="Path to the Torn war report CSV export"
    )

    payout_csv.add_argument(
        "--total_payout",
        type=float,
        required=True,
        help="Total payout amount"
    )

    payout_csv.add_argument(
        "--xanax_cost",
        type=float,
        default=0,
        help="Xanax cost to deduct (default: 0)"
    )

    payout_csv.add_argument(
        "--faction_cut",
        type=float,
        default=0,
        help="Faction cut percentage 0-100 (default: 0)"
    )

    payout_csv.add_argument(
        "--bounty_cost",
        type=float,
        default=0,
        help="Bounty cost to deduct (default: 0)"
    )

    payout_csv.add_argument(
        "--per_assist",
        type=float,
        default=0,
        help="Payment per assist on opposing faction (default: 0)"
    )

    payout_csv.add_argument(
        "--pay_outside_hits",
        type=int,
        default=0,
        choices=[0, 1],
        help="Pay for hits outside war (1=yes, 0=no, default: 0)"
    )

    watch = sub.add_parser("watch")

    watch.add_argument(
        "module",
        choices=[
            "attacks",
            "chains",
            "rankedwars",
            "armoury",
            "revives",
        ]
    )

    watch.add_argument(
        "--cooldown",
        type=int,
        default=5,
        help="Seconds to wait between polls when caught up (default: 5). Syncs aggressively until data is caught up."
    )

    watch.add_argument(
        "--duration",
        type=int,
        default=None,
        help="Total seconds to run (None = infinite)"
    )

    prices = sub.add_parser("prices")

    prices.add_argument(
        "action",
        choices=["update", "update_all", "show", "set", "missing", "export_manual"],
        help="update: fetch latest prices per item from v2 API. update_all: refresh all known item IDs via v2 torn/{id}/items value.market_price. show: display current prices. set: set a manual price. missing: list high-usage items with no effective price. export_manual: export manual overrides to CSV."
    )

    prices.add_argument(
        "--item_id",
        type=int,
        default=None,
        help="Item ID (required for 'set' action)"
    )

    prices.add_argument(
        "--price",
        type=float,
        default=None,
        help="Price to set (required for 'set' action)"
    )

    prices.add_argument(
        "--category",
        type=str,
        default=None,
        help="Filter prices by category (Medical, Drug, Utility, etc.)"
    )

    prices.add_argument(
        "--limit",
        type=int,
        default=25,
        help="Max results to show (default: 25)"
    )

    prices.add_argument(
        "--min-uses",
        dest="min_uses",
        type=int,
        default=5,
        help="Minimum usage count before an item appears in 'missing' (default: 5)"
    )

    prices.add_argument(
        "--event-type",
        dest="event_type",
        type=str,
        default="used",
        help="Restrict 'missing' to an armoury event type (default: used). Use empty string to include all."
    )

    prices.add_argument(
        "--output",
        type=str,
        default="data/manual_price_overrides.csv",
        help="CSV output path for 'export_manual' (default: data/manual_price_overrides.csv)"
    )

    revive_requests = sub.add_parser("revive_requests")

    revive_requests.add_argument(
        "action",
        choices=["add", "list", "reconcile", "delete"],
        help="add: create a revive request. list: view pending/fulfilled requests. reconcile: match pending requests against synced revives. delete: remove revive requests for testing/cleanup."
    )

    revive_requests.add_argument("--request-id", dest="request_id", type=str, default=None)
    revive_requests.add_argument("--requested-at", dest="requested_at", type=int, default=None)
    revive_requests.add_argument("--requester", dest="requester_name", type=str, default=None)
    revive_requests.add_argument("--requester-id", dest="requester_id", type=int, default=None)
    revive_requests.add_argument("--target-id", dest="target_id", type=int, default=None)
    revive_requests.add_argument("--target-name", dest="target_name", type=str, default=None)
    revive_requests.add_argument("--source", dest="source", type=str, default="external")
    revive_requests.add_argument("--notes", dest="notes", type=str, default=None)
    revive_requests.add_argument("--status", dest="status", choices=["pending", "fulfilled", "all"], default="pending")
    revive_requests.add_argument("--limit", dest="limit", type=int, default=50)
    revive_requests.add_argument("--window-seconds", dest="window_seconds", type=int, default=21600)

    revive_listener = sub.add_parser("revive_listener")

    revive_listener.add_argument(
        "action",
        choices=["serve"],
        help="serve: run the local revive request HTTP listener."
    )

    revive_listener.add_argument("--host", dest="host", type=str, default=None)
    revive_listener.add_argument("--port", dest="port", type=int, default=None)
    revive_listener.add_argument("--poll-seconds", dest="poll_seconds", type=int, default=15)
    revive_listener.add_argument("--window-seconds", dest="window_seconds", type=int, default=21600)

    discord = sub.add_parser("discord")

    discord.add_argument(
        "action",
        choices=["serve"],
        help="serve: run the Discord bot bridge for TornIntel CLI commands."
    )

    discord.add_argument(
        "--token",
        dest="token",
        type=str,
        default=None,
        help="Discord bot token. Defaults to TORN_DISCORD_BOT_TOKEN if omitted."
    )

    discord.add_argument(
        "--prefix",
        dest="prefix",
        type=str,
        default=None,
        help="Message command prefix (default from TORN_DISCORD_BOT_PREFIX or !ti)."
    )

    discord.add_argument(
        "--guild-id",
        dest="guild_id",
        type=int,
        default=None,
        help="Optional guild ID for faster slash command sync during setup."
    )

    discord.add_argument(
        "--timeout-seconds",
        dest="timeout_seconds",
        type=int,
        default=None,
        help="Timeout for foreground command execution via Discord (default from env or 180)."
    )

    return parser