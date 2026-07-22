"""
core/engine.py

Top-level entry point. Routes CLI commands to the
correct registered sync modules.
"""

from services.container import ServiceContainer
from core.manager import ModuleManager
from utils.colors import Colors, bold, header, subheader, money, divider, box_header, muted, success, info, highlight, warning
from modules.attacks.sync import AttackSync
from modules.attacks.queries import AttackQueries
from modules.attacks.report import AttackReport
from modules.chains.sync import ChainSync
from modules.chains.queries import ChainQueries
from modules.rankedwars.sync import RankedWarsSync
from modules.rankedwars.queries import RankedWarsQueries
from modules.rankedwars.report import RankedWarsReport
from modules.armoury.sync import ArmourySync
from modules.armoury.queries import ArmouryQueries
from modules.armoury.report import ArmouryReport
from modules.crimes.sync import CrimeSync
from modules.crimes.queries import CrimeQueries
from modules.crimes.report import CrimeReport
from modules.revives.sync import ReviveSync
from modules.revives.queries import ReviveQueries
from modules.revives.report import ReviveReport
from repositories.revive_request_repository import ReviveRequestRepository
import time


class TornIntel:

    def __init__(self):

        self.services = ServiceContainer()

        self.modules = ModuleManager()

        self.modules.register("attacks", AttackSync(self.services))
        self.modules.register("chains", ChainSync(self.services))
        self.modules.register("rankedwars", RankedWarsSync(self.services))
        self.modules.register("armoury", ArmourySync(self.services))
        self.modules.register("crimes", CrimeSync(self.services))
        self.modules.register("revives", ReviveSync(self.services))

        self.queries = {
            "attacks": AttackQueries(self.services.database),
            "chains": ChainQueries(self.services.database),
            "rankedwars": RankedWarsQueries(
                database=self.services.database,
                logger=self.services.logger,
            ),
            "armoury": ArmouryQueries(self.services.database, self.services.logger),
            "crimes": CrimeQueries(self.services.database),
            "revives": ReviveQueries(self.services.database),
        }

        self.reports = {
            "attacks": AttackReport(self.services.database),
            "rankedwars": RankedWarsReport(self.services.database, self.services.logger, self.services.settings),
            "armoury": ArmouryReport(self.queries["armoury"], self.services.logger, self.services.database),
            "crimes": CrimeReport(self.queries["crimes"], self.services.logger),
            "revives": ReviveReport(self.queries["revives"], self.services.logger),
        }

        # Wire scheduler back to engine for access to sync() method
        self.services.scheduler.engine = self

    #######################################################

    def sync(self, module_name, **kwargs):

        module = self.modules.get(module_name)

        if module is None:
            raise ValueError(
                f"No sync module registered for '{module_name}'"
            )

        return module.start(**kwargs)

    #######################################################

    def search(self, module_name, **kwargs):

        queries = self.queries.get(module_name)

        if queries is None:
            raise ValueError(
                f"No queries registered for '{module_name}'"
            )

        # Route to module-specific search
        if module_name == "armoury":
            results = queries.search(
                player_name=kwargs.get("player"),
                item_name=kwargs.get("item"),
                category=kwargs.get("category"),
                event_type=kwargs.get("event_type"),
                limit=kwargs.get("limit", 25),
                order="ASC" if kwargs.get("oldest_first") else "DESC",
            )
            self._print_armoury_search_results(results, kwargs)
        elif module_name == "crimes":
            results = queries.search(
                attacker_name=kwargs.get("player") or kwargs.get("attacker_name"),
                result=kwargs.get("item") or kwargs.get("result"),
                limit=kwargs.get("limit", 25),
                order="ASC" if kwargs.get("oldest_first") else "DESC",
            )
            self._print_crimes_search_results(results, kwargs)
        elif module_name == "revives":
            results = queries.search(
                attacker_id=kwargs.get("attacker"),
                attacker_name=kwargs.get("attacker_name"),
                defender_id=kwargs.get("defender"),
                defender_name=kwargs.get("defender_name"),
                result=kwargs.get("result"),
                limit=kwargs.get("limit", 25),
                order="ASC" if kwargs.get("oldest_first") else "DESC",
            )
            self._print_revives_search_results(results, kwargs)
        else:
            # Attacks and chains use attack search
            results = queries.search(
                attacker_id=kwargs.get("attacker"),
                attacker_name=kwargs.get("attacker_name"),
                defender_id=kwargs.get("defender"),
                defender_name=kwargs.get("defender_name"),
                result=kwargs.get("result"),
                chain=kwargs.get("chain"),
                limit=kwargs.get("limit", 25),
                order="ASC" if kwargs.get("oldest_first") else "DESC",
            )
            self._print_search_results(results, kwargs)

        return results

    def _print_search_results(self, results, filters):
        from datetime import datetime

        W = 88
        # Build a description of active filters
        active = []
        if filters.get("attacker"):
            active.append(f"attacker_id={filters['attacker']}")
        if filters.get("attacker_name"):
            active.append(f"attacker={filters['attacker_name']}")
        if filters.get("defender"):
            active.append(f"defender_id={filters['defender']}")
        if filters.get("defender_name"):
            active.append(f"defender={filters['defender_name']}")
        if filters.get("result"):
            active.append(f"result={filters['result']}")
        if filters.get("chain") is not None:
            active.append(f"chain=#{filters['chain']}")
        filter_str = "  |  ".join(active) if active else "none"

        print(f"\n{'='*W}")
        print(f"  ATTACK SEARCH  —  {filter_str}  —  {len(results)} result(s)")
        print(f"{'='*W}")

        if not results:
            print("  No attacks found.\n")
            return

        print(
            f"\n  {'Date/Time':<16}  {'Attacker':<20}  {'Defender':<20}  "
            f"{'Result':<13}  {'Resp':>6}  {'Chain#':>7}"
        )
        print(f"  {'-'*(W-2)}")

        for r in results:
            ts       = datetime.fromtimestamp(r["timestamp_started"]).strftime("%m-%d %H:%M")
            attacker = (r["attacker_name"] or "?")[:19]
            defender = (r["defender_name"] or "?")[:19]
            result   = (r["result"] or "?")[:12]
            respect  = r["respect_gain"] or 0
            chain_n  = r["chain"] or 0

            print(
                f"  {ts:<16}  {attacker:<20}  {defender:<20}  "
                f"{result:<13}  {respect:>6.2f}  #{chain_n:>6,}"
            )

        print(f"\n{'='*W}\n")

    def _print_revives_search_results(self, results, filters):
        from datetime import datetime
        import textwrap

        W = 124
        active = []
        if filters.get("attacker"):
            active.append(f"reviver_id={filters['attacker']}")
        if filters.get("attacker_name"):
            active.append(f"reviver={filters['attacker_name']}")
        if filters.get("defender"):
            active.append(f"target_id={filters['defender']}")
        if filters.get("defender_name"):
            active.append(f"target={filters['defender_name']}")
        if filters.get("result"):
            active.append(f"result={filters['result']}")
        filter_str = "  |  ".join(active) if active else "none"

        print(f"\n{'='*W}")
        print(f"  REVIVES SEARCH  —  {filter_str}  —  {len(results)} result(s)")
        print(f"{'='*W}")

        if not results:
            print("  No revives found.\n")
            return

        print(
            f"\n  {'Date/Time':<16}  {'Reviver':<20}  {'Target':<20}  {'Result':<10}  {'Chance':>7}"
        )
        print(f"  {'-'*(W-2)}")

        for r in results:
            ts = datetime.fromtimestamp(r["timestamp"]).strftime("%m-%d %H:%M")
            reviver = highlight((r["reviver_name"] or "?")[:19])
            target = info((r["target_name"] or "?")[:19])
            result_raw = (r["result"] or "?")[:9]
            chance = float(r.get("chance") or 0)
            reason = str(r.get("target_hospital_reason") or "-")
            result = success(result_raw) if result_raw.lower().startswith("success") else warning(result_raw)
            chance_text = success(f"{chance:>6.2f}%") if chance >= 80 else warning(f"{chance:>6.2f}%")

            print(
                f"  {ts:<16}  {reviver:<20}  {target:<20}  {result:<10}  {chance_text}"
            )

            wrapped_reason = textwrap.wrap(reason, width=W - 18) or ["-"]
            for idx, chunk in enumerate(wrapped_reason):
                prefix = warning("Hosp Reason:") if idx == 0 else ""
                print(f"  {'':<16}  {prefix:<20}  {muted(chunk)}")

        print(f"\n{'='*W}\n")

    def _print_armoury_search_results(self, results, filters):
        from datetime import datetime
        
        W = 110
        # Build a description of active filters
        active = []
        if filters.get("player"):
            active.append(f"player={filters['player']}")
        if filters.get("item"):
            active.append(f"item={filters['item']}")
        if filters.get("category"):
            active.append(f"category={filters['category']}")
        if filters.get("event_type"):
            active.append(f"event_type={filters['event_type']}")
        filter_str = "  |  ".join(active) if active else "none"
        
        print(f"\n{divider(W)}")
        print(f"  {header('ARMOURY SEARCH')} — {filter_str} — {info(str(len(results)))} result(s)")
        print(f"{divider(W)}")
        
        if not results:
            print("  No armoury events found.\n")
            return
        
        print(
            f"\n  {'Date/Time':<16}  {'Event':<10}  {'Player':<18}  "
            f"{'Item':<25}  {'Category':<12}  {'Qty':>4}  {'Price':>10}"
        )
        print(f"  {divider(W-2)}")
        
        for r in results:
            ts = datetime.fromtimestamp(r["timestamp"]).strftime("%m-%d %H:%M")
            event = (r["event_type"] or "?")[:9]
            player = (r["player_name"] or "?")[:17]
            item = (r["item_name"] or "?")[:24]
            category = (r["item_category"] or "?")[:11]
            qty = r["quantity"] or 0
            price = r["effective_price"] if "effective_price" in r.keys() else (r["item_price"] or 0)
            
            # Color the event type
            event_colored = highlight(event) if event != "?" else event
            # Color the item name
            item_colored = info(item) if item != "?" else item
            # Color the category
            category_colored = success(category) if category != "?" else category
            # Color the price
            price_colored = money(float(price)) if price > 0 else f"{price:,.0f}"
            
            print(
                f"  {ts:<16}  {event_colored:<18}  {player:<18}  "
                f"{item_colored:<33}  {category_colored:<20}  {qty:>4}  {price_colored:>10}"
            )
        
        print(f"\n{divider(W)}\n")

    def _print_crimes_search_results(self, results, filters):
        W = 118

        active = []
        if filters.get("player"):
            active.append(f"player={filters['player']}")
        if filters.get("item"):
            active.append(f"item={filters['item']}")
        filter_str = "  |  ".join(active) if active else "none"

        print(f"\n{'='*W}")
        print(f"  CRIMES SEARCH  —  {filter_str}  —  {len(results)} result(s)")
        print(f"{'='*W}")

        if not results:
            print("  No active crime slots found.\n")
            return

        print(
            f"\n  {'Crime':<24} {'Status':<11} {'Src':<6} {'Lvl':<4} {'Position':<16} {'Player':<20} {'Item':<20} {'CPR':>5} {'Best':>6}"
        )
        print(f"  {'-'*(W-2)}")

        for r in results:
            crime = (r.get("crime_name") or "?")[:23]
            status_raw = (r.get("status") or "?")[:10]
            level = int(r.get("difficulty") or 0)
            position = (r.get("slot_position") or "?")[:15]
            player = (r.get("user_name") or "?")[:19]
            item_id = int(r.get("required_item_id") or 0)
            item_name = (r.get("required_item_name") or "-")
            item = f"{item_name} [{item_id}]" if item_id > 0 else item_name
            item = item[:19]
            cpr = int(r.get("checkpoint_pass_rate") or 0)
            best = int(r.get("best_cpr") or cpr)
            source = "hist" if int(r.get("is_historical") or 0) == 1 else "active"

            if status_raw.lower().startswith("plan"):
                status = warning(status_raw)
            elif status_raw.lower().startswith("recruit"):
                status = success(status_raw)
            elif status_raw.lower().startswith("complete"):
                status = info(status_raw)
            else:
                status = muted(status_raw)

            if cpr >= best:
                cpr_text = success(f"{cpr:>4}%")
            else:
                cpr_text = warning(f"{cpr:>4}%")

            best_text = success(f"{best:>5}%")
            source_text = muted(source) if source == "hist" else highlight(source)

            print(
                f"  {crime:<24} {status:<11} {source_text:<6} {level:<4} {position:<16} {player:<20} {item:<20} {cpr_text:>5} {best_text:>6}"
            )

        if filters.get("player") or filters.get("attacker_name"):
            print("\n  historical rows come from previous crime slot snapshots (real crime names/status), not only current active slots")

        print(f"\n{'='*W}\n")

    #######################################################

    def report(self, module_name, report_type, **kwargs):

        report = self.reports.get(module_name)

        if report is None:
            raise ValueError(
                f"No reports available for '{module_name}'"
            )

        # Chain reports
        if report_type == "chain_hit":
            chain_id = kwargs.get("chain_id")
            hit_number = kwargs.get("hit_number")
            
            if chain_id is None or hit_number is None:
                raise ValueError(
                    "chain_hit report requires --chain_id and --hit_number"
                )
            
            hit = report.chain_hit(chain_id, hit_number)
            if hit:
                self._print_hit_report(hit)
            else:
                print(f"No hit #{hit_number} found in chain {chain_id}")

        elif report_type == "chain_stats":
            chain_id = kwargs.get("chain_id")
            top_n = kwargs.get("top_n", 10)

            if chain_id is None:
                raise ValueError(
                    "chain_stats report requires --chain_id"
                )

            faction_id = self.services.settings.faction_id
            stats = report.chain_stats(chain_id, top_n=top_n, faction_id=faction_id)
            if stats:
                self._print_chain_stats(stats)
            else:
                print(f"No chain data found for chain {chain_id}")

        elif report_type == "chain_player":
            chain_id = kwargs.get("chain_id")
            player = kwargs.get("player")

            if chain_id is None or not player:
                raise ValueError(
                    "chain_player report requires --chain_id and --player"
                )

            result = report.chain_player(chain_id, player)
            if result:
                self._print_player_report(chain_id, result)
            else:
                print(f"No attacks found for '{player}' in chain {chain_id}")

        elif report_type == "chain_leaderboard":
            chain_id = kwargs.get("chain_id")
            
            if chain_id is None:
                raise ValueError(
                    "chain_leaderboard report requires --chain_id"
                )
            
            faction_id = self.services.settings.faction_id
            leaderboard = report.chain_leaderboard(chain_id, faction_id=faction_id)
            if leaderboard:
                self._print_leaderboard(chain_id, leaderboard)
            else:
                print(f"No chain data found for chain {chain_id}")

        # War reports
        elif report_type == "war_stats":
            war_id = kwargs.get("war_id")
            
            if war_id is None:
                raise ValueError(
                    "war_stats report requires --war_id"
                )
            
            stats = report.war_stats(war_id)
            if stats:
                self._print_war_stats(stats)
            else:
                print(f"No war data found for war {war_id}")

        elif report_type == "war_leaderboard":
            war_id = kwargs.get("war_id")
            top_n = kwargs.get("top_n", 10)
            
            if war_id is None:
                raise ValueError(
                    "war_leaderboard report requires --war_id"
                )
            
            leaderboard = report.war_leaderboard(war_id, top_n=top_n)
            if leaderboard:
                self._print_war_leaderboard(war_id, leaderboard)
            else:
                print(f"No war data found for war {war_id}")

        elif report_type == "war_player":
            war_id = kwargs.get("war_id")
            player = kwargs.get("player")
            
            if war_id is None or not player:
                raise ValueError(
                    "war_player report requires --war_id and --player"
                )
            
            result = report.war_player(war_id, player)
            if result:
                self._print_war_player(war_id, result)
            else:
                print(f"No attacks found for '{player}' in war {war_id}")

        elif report_type == "war_payout":
            war_id = kwargs.get("war_id")
            total_payout = kwargs.get("total_payout")
            xanax_cost = kwargs.get("xanax_cost", 0)
            faction_cut = kwargs.get("faction_cut", 0)
            bounty_cost = kwargs.get("bounty_cost", 0)
            per_assist = kwargs.get("per_assist", 0)
            pay_outside_hits = kwargs.get("pay_outside_hits", 0)
            
            if war_id is None or total_payout is None:
                raise ValueError(
                    "war_payout report requires --war_id and --total_payout"
                )
            
            from modules.rankedwars.payout import WarPayoutCalculator
            calculator = WarPayoutCalculator(self.services.database, self.services.logger, self.services.settings)
            result = calculator.calculate_payouts(
                war_id, total_payout, xanax_cost, faction_cut, bounty_cost, per_assist, pay_outside_hits
            )
            
            if result:
                self._print_war_payout(result)
            else:
                print(f"No war data found for war {war_id}")

        elif report_type == "war_costs":
            war_id = kwargs.get("war_id")
            stacking_days = kwargs.get("stacking_days", 0)
            temp_return_days = kwargs.get("temp_return_days", 2)

            if war_id is None:
                raise ValueError("war_costs report requires --war_id")

            output = report.war_costs(
                war_id,
                stacking_days=stacking_days,
                temp_return_days=temp_return_days,
            )
            print(output)

        elif report_type == "chain_costs":
            chain_id = kwargs.get("chain_id")
            stacking_days = kwargs.get("stacking_days", 0)
            temp_return_days = kwargs.get("temp_return_days", 2)

            if chain_id is None:
                raise ValueError("chain_costs report requires --chain_id")

            output = report.chain_costs(
                chain_id,
                stacking_days=stacking_days,
                temp_return_days=temp_return_days,
            )
            print(output)

        # Armoury reports
        elif report_type == "player_usage":
            player_name = kwargs.get("player")
            if not player_name:
                raise ValueError("player_usage report requires --player")
            output = report.player_usage(player_name)
            print(output)

        elif report_type == "category":
            category = kwargs.get("category")
            if not category:
                raise ValueError("category report requires --category")
            output = report.category(category)
            print(output)

        elif report_type == "medical_summary":
            output = report.medical_summary()
            print(output)

        elif report_type == "loan_tracker":
            output = report.loan_tracker(
                player_name=kwargs.get("player"),
                item_name=kwargs.get("item"),
                limit=kwargs.get("limit", 50),
            )
            print(output)

        elif report_type == "oc_item_audit":
            output = report.item_audit()
            print(output)

        elif report_type == "oc_cpr":
            output = report.cpr_report()
            print(output)

        elif report_type == "oc_outside":
            output = report.outside_members_report(limit=kwargs.get("limit", 200))
            print(output)

        else:
            raise ValueError(
                f"Unknown report type '{report_type}'. "
                "Available: chain_hit, chain_stats, chain_leaderboard, chain_player, "
                "war_stats, war_leaderboard, war_player, war_payout, "
                "war_costs, chain_costs, player_usage, category, medical_summary, loan_tracker, "
                "oc_item_audit, oc_cpr, oc_outside"
            )

    #######################################################

    def manage_revive_requests(
        self,
        action,
        request_id=None,
        requested_at=None,
        requester_name=None,
        requester_id=None,
        target_id=None,
        target_name=None,
        source="external",
        notes=None,
        status="pending",
        limit=50,
        window_seconds=21600,
    ):

        repo = ReviveRequestRepository(self.services.database)
        report = self.reports.get("revives")

        if action == "add":
            if requested_at is None:
                raise ValueError("revive_requests add requires --requested-at")
            if target_id is None and not target_name:
                raise ValueError("revive_requests add requires --target-id or --target-name")

            final_request_id = request_id or (
                f"revreq:{int(time.time() * 1000)}:{target_id or target_name}"
            )

            stored_request_id = repo.create_request(
                {
                    "request_id": final_request_id,
                    "requested_timestamp": int(requested_at),
                    "created_at": int(time.time()),
                    "requester_id": int(requester_id) if requester_id is not None else None,
                    "requester_name": requester_name,
                    "target_id": int(target_id) if target_id is not None else None,
                    "target_name": target_name,
                    "source": source,
                    "status": "pending",
                    "fulfilled_revive_id": None,
                    "revived_timestamp": None,
                    "fulfilled_at": None,
                    "fulfilled_by_id": None,
                    "fulfilled_by_name": None,
                    "matched_at": None,
                    "notes": notes,
                    "raw_payload": None,
                }
            )

            repo.reconcile_against_database(window_seconds=window_seconds, limit=1)
            saved = repo.get(stored_request_id)
            print(f"Stored revive request {stored_request_id}")
            if saved:
                print(report.requests_list(status="all", target_name=saved["target_name"], limit=5))
            else:
                print(report.requests_list(status="all", target_name=target_name, limit=5))
            return

        if action == "list":
            print(report.requests_list(status=status, target_name=target_name, limit=limit))
            return

        if action == "reconcile":
            matched = repo.reconcile_against_database(window_seconds=window_seconds, limit=max(limit, 500))
            print(f"Matched {matched} pending revive request(s)")
            print(report.requests_list(status=status, target_name=target_name, limit=limit))
            return

        if action == "delete":
            removed = repo.delete_requests(
                status=status,
                request_id=request_id,
                requester_id=requester_id,
                requester_name=requester_name,
                target_id=target_id,
                target_name=target_name,
                source=source,
            )
            scope = status if status and status != "all" else "all"
            print(f"Removed {removed} revive request(s) with status={scope}")
            return

        raise ValueError(f"Unknown revive_requests action '{action}'")

    #######################################################

    def manage_revive_listener(self, action, host=None, port=None, poll_seconds=15, window_seconds=21600):

        if action != "serve":
            raise ValueError(f"Unknown revive_listener action '{action}'")

        self.services.revive_listener.serve(
            host=host,
            port=port,
            poll_seconds=poll_seconds,
            window_seconds=window_seconds,
        )

    #######################################################

    def manage_discord(self, action, token=None, prefix=None, guild_id=None, timeout_seconds=None):

        if action != "serve":
            raise ValueError(f"Unknown discord action '{action}'")

        from services.discord_bot_service import serve_discord_bot

        effective_token = token or self.services.settings.discord_bot_token
        if not effective_token:
            raise ValueError("discord serve requires --token or TORN_DISCORD_BOT_TOKEN in environment")

        effective_prefix = prefix or self.services.settings.discord_command_prefix
        effective_guild_id = guild_id if guild_id is not None else self.services.settings.discord_guild_id
        effective_timeout = (
            int(timeout_seconds)
            if timeout_seconds is not None
            else int(self.services.settings.discord_command_timeout)
        )

        serve_discord_bot(
            token=effective_token,
            prefix=effective_prefix,
            guild_id=effective_guild_id,
            timeout_seconds=effective_timeout,
            logger=self.services.logger,
        )

    #######################################################

    def manage_crime_rules(self, action, tier=None, crime_name=None, position=None, min_cpr=None):

        report = self.reports.get("crimes")
        if report is None:
            raise ValueError("Crimes report module is not available")

        if action == "show":
            print(report.rules_show())
            return

        if action == "set_tier":
            if tier is None or min_cpr is None:
                raise ValueError("set_tier requires --tier and --min-cpr")
            print(report.rules_set_tier(tier=tier, min_cpr=min_cpr))
            return

        if action == "set_crime":
            if not crime_name or min_cpr is None:
                raise ValueError("set_crime requires --crime-name and --min-cpr")
            print(report.rules_set_crime(crime_name=crime_name, min_cpr=min_cpr))
            return

        if action == "set_position":
            if not crime_name or not position or min_cpr is None:
                raise ValueError("set_position requires --crime-name --position --min-cpr")
            print(
                report.rules_set_position(
                    crime_name=crime_name,
                    position=position,
                    min_cpr=min_cpr,
                )
            )
            return

        if action == "remove_crime":
            if not crime_name:
                raise ValueError("remove_crime requires --crime-name")
            print(report.rules_remove_crime(crime_name=crime_name))
            return

        raise ValueError(f"Unknown crime_rules action '{action}'")

    #######################################################

    def watch(self, module_name, **kwargs):
        """Start continuous sync in live mode."""

        cooldown = kwargs.get("cooldown", 5)
        duration = kwargs.get("duration", None)

        self.services.scheduler.run_continuous(
            module_name,
            catch_up_cooldown=cooldown,
            duration_seconds=duration,
        )

    #######################################################

    def payout(self, module_name, **kwargs):
        """Calculate war payouts."""
        
        if module_name != "rankedwars":
            raise ValueError(f"Payout is only available for rankedwars")
        
        war_id = kwargs.get("war_id")
        total_payout = kwargs.get("total_payout")
        xanax_cost = kwargs.get("xanax_cost", 0)
        faction_cut = kwargs.get("faction_cut", 0)
        bounty_cost = kwargs.get("bounty_cost", 0)
        per_assist = kwargs.get("per_assist", 0)
        pay_outside_hits = kwargs.get("pay_outside_hits", 0)
        
        if war_id is None or total_payout is None:
            raise ValueError(
                "payout requires --war_id and --total_payout"
            )
        
        from modules.rankedwars.payout import WarPayoutCalculator
        calculator = WarPayoutCalculator(self.services.database, self.services.logger, self.services.settings)
        result = calculator.calculate_payouts(
            war_id, total_payout, xanax_cost, faction_cut, bounty_cost, per_assist, pay_outside_hits
        )
        
        if result:
            self._print_war_payout(result)
        else:
            print(f"No war data found for war {war_id}")

    def payout_csv(self, module_name, **kwargs):
        """Calculate war payouts using CSV data."""
        
        if module_name != "rankedwars":
            raise ValueError(f"Payout is only available for rankedwars")
        
        war_id = kwargs.get("war_id")
        csv_path = kwargs.get("csv_path")
        total_payout = kwargs.get("total_payout")
        xanax_cost = kwargs.get("xanax_cost", 0)
        faction_cut = kwargs.get("faction_cut", 0)
        bounty_cost = kwargs.get("bounty_cost", 0)
        per_assist = kwargs.get("per_assist", 0)
        pay_outside_hits = kwargs.get("pay_outside_hits", 0)
        
        if war_id is None or csv_path is None or total_payout is None:
            raise ValueError(
                "payout_csv requires --war_id, --csv_path, and --total_payout"
            )
        
        from modules.rankedwars.payout_from_csv import CSVWarPayoutCalculator
        calculator = CSVWarPayoutCalculator(self.services.database, self.services.logger, self.services.settings)
        result = calculator.calculate_payouts_from_csv(
            war_id, csv_path, total_payout, xanax_cost, faction_cut, bounty_cost, per_assist, pay_outside_hits
        )
        
        if result:
            self._print_war_payout(result)
        else:
            print(f"Failed to calculate payouts from CSV")

    #######################################################

    def _print_hit_report(self, hit):
        """Format and print a single hit report"""
        print(f"\n{'='*70}")
        print(f"HIT DETAILS - Attack #{hit['attack_id']}")
        print(f"{'='*70}")
        print(f"\nAttacker: {hit['attacker_name']} (Level {hit['attacker_level']})")
        print(f"Defender: {hit['defender_name']} (Level {hit['defender_level']})")
        print(f"\nResult: {hit['result']}")
        print(f"Respect Gain: {hit['respect_gain']} | Respect Loss: {hit['respect_loss']}")
        print(f"Chain: {hit['chain']}")

    def _print_chain_stats(self, stats):
        """Format and print chain statistics with colors"""
        W = 80
        print(f"\n{divider(W)}")
        print(box_header('CHAIN STATISTICS', W))

        duration_min = (stats.get('duration_seconds') or 0) // 60
        duration_h = duration_min // 60
        duration_rem = duration_min % 60
        duration_str = f"{duration_h}h {duration_rem}m" if duration_h else f"{duration_rem}m"

        print(f"\n{subheader('  PARAMETERS')}")
        print(f"  Faction hits tracked : {Colors.CYAN}{stats['total_hits']:,}{Colors.RESET}")
        print(f"  Unique attackers      : {Colors.CYAN}{stats['unique_attackers']:,}{Colors.RESET}")
        print(f"  Total respect gained  : {Colors.GREEN}{stats['total_respect_gained']:,.2f}{Colors.RESET}")
        print(f"  Avg respect / hit     : {Colors.GREEN}{(stats['avg_respect_per_hit'] or 0):.2f}{Colors.RESET}")
        print(f"  Success rate          : {Colors.YELLOW}{stats['success_rate_pct']:.1f}%{Colors.RESET}")
        print(f"  Duration              : {Colors.CYAN}{duration_str}{Colors.RESET}")
        if stats.get('chain_start_num') is not None and stats.get('chain_end_num'):
            print(f"  Chain hit range       : {Colors.BRIGHT_WHITE}#{stats['chain_start_num']:,} – #{stats['chain_end_num']:,}{Colors.RESET}")

        if stats.get('result_breakdown'):
            print(f"\n{subheader('  RESULT BREAKDOWN')}")
            print(f"  {Colors.BOLD}{Colors.CYAN}{'Result':<16} {'Hits':>6}  {'Respect':>10}{Colors.RESET}")
            print(f"  {divider(W-2)}")
            for r in stats['result_breakdown']:
                print(f"  {r['result']:<16} {Colors.CYAN}{r['count']:>6}{Colors.RESET}  {Colors.GREEN}{(r['respect'] or 0):>10.2f}{Colors.RESET}")

        if stats.get('top_attackers'):
            print(f"\n{subheader('  TOP ATTACKERS')}")
            print(f"  {Colors.BOLD}{Colors.CYAN}{'Rank':<5} {'Name':<20} {'Hits':>5}  {'Respect':>9}  {'Avg':>6}  {'Succ%':>6}{Colors.RESET}")
            print(f"  {divider(W-2)}")
            for i, a in enumerate(stats['top_attackers'], 1):
                name = (a['attacker_name'] or '(Unknown)')[:19]
                avg = a['avg_respect'] or 0
                first = a['first_hit'] or 0
                last = a['last_hit'] or 0
                succ_rate = a['success_rate_pct']
                succ_color = Colors.GREEN if succ_rate >= 80 else (Colors.YELLOW if succ_rate >= 50 else Colors.RED)
                print(
                    f"  {Colors.BRIGHT_YELLOW if i <= 3 else Colors.RESET}{i:<5} {name:<20}{Colors.RESET} {Colors.CYAN}{a['hits']:>5}{Colors.RESET}  "
                    f"{Colors.GREEN}{a['total_respect']:>9.2f}{Colors.RESET}  {Colors.GREEN}{avg:>6.2f}{Colors.RESET}  "
                    f"{succ_color}{succ_rate:>5.1f}%{Colors.RESET}"
                )
        print(f"\n{divider(W)}")

    def _print_player_report(self, chain_id, data):
        """Format and print a player's attacks within a chain with colors"""
        from datetime import datetime
        W = 80
        player_title = f"{data['player_name']} — {data['faction_name']}"
        print(f"\n{divider(W)}")
        print(box_header(player_title, W))
        print(f"\n{subheader('  SUMMARY')}")
        print(f"  Total hits     : {Colors.CYAN}{data['total_hits']}{Colors.RESET}")
        succ_rate = data['success_rate_pct']
        succ_color = Colors.GREEN if succ_rate >= 80 else (Colors.YELLOW if succ_rate >= 50 else Colors.RED)
        print(f"  Successful     : {Colors.CYAN}{data['successful_hits']}{Colors.RESET} ({succ_color}{data['success_rate_pct']:.1f}%{Colors.RESET})")
        print(f"  Total respect  : {Colors.GREEN}{data['total_respect']:.2f}{Colors.RESET}")
        print(f"  Avg respect    : {Colors.GREEN}{data['avg_respect']:.2f}{Colors.RESET}")
        print(f"  First hit      : {Colors.BRIGHT_WHITE}#{data['first_hit']:,}{Colors.RESET}")
        print(f"  Last hit       : {Colors.BRIGHT_WHITE}#{data['last_hit']:,}{Colors.RESET}")
        print(f"\n{subheader('  ATTACK HISTORY')}")
        print(f"  {Colors.BOLD}{Colors.CYAN}{'Chain#':>7}  {'Result':<14} {'Respect':>8}  {'Defender':<20} {'Time'}{Colors.RESET}")
        print(f"  {divider(W-2)}")
        for a in data['attacks']:
            ts = datetime.fromtimestamp(a['timestamp_started']).strftime('%m-%d %H:%M')
            defender = (a['defender_name'] or '?')[:19]
            result_color = Colors.GREEN if a['respect_gain'] > 0 else Colors.RED
            print(
                f"  {Colors.BRIGHT_WHITE}#{a['chain']:>6,}{Colors.RESET}  {result_color}{a['result']:<14}{Colors.RESET} {Colors.GREEN}{a['respect_gain']:>8.2f}{Colors.RESET}  "
                f"{defender:<20} {ts}"
            )
        print(f"\n{divider(W)}")

    def _print_leaderboard(self, chain_id, leaderboard):
        """Format and print chain leaderboard with colors"""
        W = 100
        print(f"\n{divider(W)}")
        title = f"CHAIN ID {chain_id} LEADERBOARD"
        print(box_header(title, W))
        print(f"\n{Colors.BOLD}{Colors.CYAN}{'Rank':<6} {'Name':<24} {'Faction':<28} {'Hits':>5}  {'Respect':>10}  {'Success':>8}{Colors.RESET}")
        print(f"{divider(W-2)}")
        
        for rank, attacker in enumerate(leaderboard, 1):
            name = attacker['attacker_name'] or "(Unknown)"
            faction = attacker['attacker_faction_name'] or "(No Faction)"
            succ_rate = attacker['success_rate_pct']
            succ_color = Colors.GREEN if succ_rate >= 80 else (Colors.YELLOW if succ_rate >= 50 else Colors.RED)
            rank_color = Colors.BRIGHT_YELLOW if rank <= 3 else Colors.RESET
            
            print(
                f"{rank_color}{rank:<6}{Colors.RESET} {name:<24} {faction:<28} "
                f"{Colors.CYAN}{attacker['hits']:>5}{Colors.RESET}  "
                f"{Colors.GREEN}{attacker['total_respect']:>10.1f}{Colors.RESET}  "
                f"{succ_color}{succ_rate:>7.1f}%{Colors.RESET}"
            )
        print(f"\n{divider(W)}")

    #######################################################

    def _print_war_stats(self, stats):
        """Format and print war statistics with colors"""
        from datetime import datetime
        W = 100
        
        print(f"\n{divider(W)}")
        war_title = f'WAR STATISTICS - War ID {stats["war_id"]}'
        print(box_header(war_title, W))
        
        # War overview
        winner_color = Colors.GREEN if stats['our_score'] > stats['opponent_score'] else Colors.RED
        print(f"\n{subheader('  FACTIONS')}")
        print(f"  Our: {Colors.CYAN}{stats['our_faction_name']}{Colors.RESET} vs Opponent: {Colors.CYAN}{stats['opponent_faction_name']}{Colors.RESET}")
        print(f"  Winner: {winner_color}{stats['winner_name']}{Colors.RESET}")
        print(f"  Duration: {Colors.CYAN}{stats['war_duration_str']}{Colors.RESET}")
        print(f"  Target respect: {Colors.GREEN}{stats['war_target']:,}{Colors.RESET}")
        
        # Scores
        print(f"\n{subheader('  FACTION COMPARISON')}")
        our_wins = stats['our_score'] > stats['opponent_score']
        print(f"  {Colors.BOLD}{Colors.CYAN}{'Faction':<30} {'Score':>12} {'Hits':>8} {'Avg Resp':>12} {'Succ%':>8}{Colors.RESET}")
        print(f"  {divider(W-2)}")
        
        our_score_color = Colors.GREEN if our_wins else Colors.RED
        print(
            f"  {stats['our_faction_name']:<30} {our_score_color}{stats['our_score']:>12}{Colors.RESET} "
            f"{Colors.CYAN}{stats['our_hits']:>8}{Colors.RESET} {Colors.GREEN}{stats['our_avg_respect']:>12.2f}{Colors.RESET} "
            f"{Colors.YELLOW}{stats['our_success_rate']:>7.1f}%{Colors.RESET}"
        )
        
        opp_score_color = Colors.GREEN if not our_wins else Colors.RED
        print(
            f"  {stats['opponent_faction_name']:<30} {opp_score_color}{stats['opponent_score']:>12}{Colors.RESET} "
            f"{Colors.CYAN}{stats['opponent_hits']:>8}{Colors.RESET} {Colors.GREEN}{stats['opponent_avg_respect']:>12.2f}{Colors.RESET} "
            f"{Colors.YELLOW}{stats['opponent_success_rate']:>7.1f}%{Colors.RESET}"
        )
        
        # Result breakdown
        if stats.get('our_result_breakdown'):
            print(f"\n{subheader('  RESULT BREAKDOWN (OUR FACTION)')}")
            print(f"  {Colors.BOLD}{Colors.CYAN}{'Result':<16} {'Hits':>8}  {'Respect':>12}{Colors.RESET}")
            print(f"  {divider(W-2)}")
            for result, data in sorted(stats['our_result_breakdown'].items()):
                hits = data["hits"] if isinstance(data, dict) else data
                respect = data["respect"] if isinstance(data, dict) else 0
                print(f"  {result:<16} {Colors.CYAN}{hits:>8}{Colors.RESET}  {Colors.GREEN}{respect:>12.2f}{Colors.RESET}")
        
        # Top attackers
        if stats.get('top_attackers'):
            print(f"\n{subheader('  TOP ATTACKERS (OUR FACTION)')}")
            print(
                f"  {Colors.BOLD}{Colors.CYAN}{'Rank':<5} {'Name':<24} {'Hits':>6}  {'Respect':>10}  "
                f"{'Avg':>7}  {'Succ%':>7}{Colors.RESET}"
            )
            print(f"  {divider(W-2)}")
            for i, a in enumerate(stats['top_attackers'], 1):
                name = (a['name'] or '(Unknown)')[:23]
                avg = a['avg_respect'] or 0
                succ_rate = a['success_rate']
                succ_color = Colors.GREEN if succ_rate >= 80 else (Colors.YELLOW if succ_rate >= 50 else Colors.RED)
                rank_color = Colors.BRIGHT_YELLOW if i <= 3 else Colors.RESET
                print(
                    f"  {rank_color}{i:<5}{Colors.RESET} {name:<24} {Colors.CYAN}{a['hits']:>6}{Colors.RESET}  "
                    f"{Colors.GREEN}{a['respect']:>10.2f}{Colors.RESET}  {Colors.GREEN}{avg:>7.2f}{Colors.RESET}  "
                    f"{succ_color}{succ_rate:>6.1f}%{Colors.RESET}"
                )
        
        print(f"\n{divider(W)}")

    def _print_war_leaderboard(self, war_id, leaderboard):
        """Format and print war leaderboard with colors"""
        W = 100
        print(f"\n{divider(W)}")
        title = f'WAR ID {war_id} - ATTACKER LEADERBOARD'
        print(box_header(title, W))
        
        print(f"{Colors.BOLD}{Colors.CYAN}{'Rank':<6} {'Name':<26} {'Hits':>7}  {'Respect':>12}  {'Avg':>8}  {'Success':>8}{Colors.RESET}")
        print(f"{divider(W-2)}")
        
        for row in leaderboard:
            name = (row['name'] or "(Unknown)")[:25]
            succ_rate = row['success_rate']
            succ_color = Colors.GREEN if succ_rate >= 80 else (Colors.YELLOW if succ_rate >= 50 else Colors.RED)
            rank_color = Colors.BRIGHT_YELLOW if row['rank'] <= 3 else Colors.RESET
            print(
                f"{rank_color}{row['rank']:<6}{Colors.RESET} {name:<26} {Colors.CYAN}{row['hits']:>7}{Colors.RESET}  "
                f"{Colors.GREEN}{row['respect']:>12.2f}{Colors.RESET}  {Colors.GREEN}{row['avg_respect']:>8.2f}{Colors.RESET}  "
                f"{succ_color}{succ_rate:>7.1f}%{Colors.RESET}"
            )
        
        print(f"\n{divider(W)}")

    def _print_war_player(self, war_id, data):
        """Format and print a player's attacks within a war with colors"""
        from datetime import datetime
        W = 100
        
        player_title = f"{data['player_name']} — War ID {war_id}"
        print(f"\n{divider(W)}")
        print(box_header(player_title, W))
        
        print(f"\n{subheader('  SUMMARY')}")
        print(f"  Total hits     : {Colors.CYAN}{data['hits']}{Colors.RESET}")
        successful_hits = data['hits'] - int(data['hits'] * (100 - data['success_rate']) / 100)
        succ_color = Colors.GREEN if data['success_rate'] >= 80 else (Colors.YELLOW if data['success_rate'] >= 50 else Colors.RED)
        print(f"  Successful     : {Colors.CYAN}{successful_hits}{Colors.RESET} "
              f"({succ_color}{data['success_rate']:.1f}%{Colors.RESET})")
        print(f"  Total respect  : {Colors.GREEN}{data['total_respect']:.2f}{Colors.RESET}")
        print(f"  Avg respect    : {Colors.GREEN}{data['avg_respect']:.2f}{Colors.RESET}")
        
        if data.get('attacks'):
            print(f"\n{subheader('  ATTACK HISTORY')}")
            print(f"  {Colors.BOLD}{Colors.CYAN}{'Chain':>8}  {'Result':<14} {'Respect':>10}  {'Defender':<24} {'Time'}{Colors.RESET}")
            print(f"  {divider(W-2)}")
            
            for a in data['attacks']:
                ts = datetime.fromtimestamp(a['timestamp']).strftime('%m-%d %H:%M')
                defender = (a['defender'] or '?')[:23]
                result_color = Colors.GREEN if a['respect'] > 0 else Colors.RED
                print(
                    f"  {Colors.BRIGHT_WHITE}#{a['chain_hit']:>7,}{Colors.RESET}  {result_color}{a['result']:<14}{Colors.RESET} {Colors.GREEN}{a['respect']:>10.2f}{Colors.RESET}  "
                    f"{defender:<24} {ts}"
                )
        
        print(f"\n{divider(W)}")

    def _print_war_payout(self, data):
        """Format and print war payout calculations with colors"""
        W = 140
        
        print(f"\n{divider(W)}")
        war_title = f'WAR PAYOUT CALCULATIONS - War ID {data["war_id"]}'
        print(box_header(war_title, W))
        
        print(f"\n{subheader('  PARAMETERS')}")
        print(f"  Total Payout Pool      : {money(data['total_payout'])}")
        print(f"  Faction Cut ({data['faction_cut_pct']:.1f}%)      : {money(data['total_payout'] * (data['faction_cut_pct']/100.0))}")
        print(f"  After Faction Cut      : {money(data['total_payout'] * (1 - data['faction_cut_pct']/100.0))}")
        print(f"  Xanax Cost             : {money(data['xanax_cost'])}")
        print(f"  Bounty Cost            : {money(data['bounty_cost'])}")
        if data.get('per_assist', 0) > 0:
            print(f"  Assist Payment         : {money(data['per_assist'])}/assist")
            print(f"  Total Assist Cost      : {money(data['total_assist_cost'])}")
        print(f"  Distribution Pool      : {money(data['payout_after_costs'])}")
        print(f"  Total War Respect      : {Colors.CYAN}{data['total_war_respect']:,.2f}{Colors.RESET}")
        if data.get('dollar_per_respect'):
            print(f"  $ per Respect          : {money(data['dollar_per_respect'])}")
        if data.get('pay_outside_hits'):
            print(f"  Outside Hits Enabled   : {Colors.GREEN}YES{Colors.RESET} (included in pool)")
        
        if data.get('payouts'):
            print(f"\n{subheader('  PLAYER PAYOUTS')}")
            # Columns: Rank, Name, War Hits, Bonus Hits, Assists, Outside, Respect Earned, Payout
            header_line = f"  {Colors.BOLD}{Colors.CYAN}{'Rank':<4} {'Name':<18} {'War':>3} {'Bon':>3} {'Ast':>3} {'Out':>3}  {'Respect':>10}  {'%':>6}  {'Payout':>14}{Colors.RESET}"
            print(header_line)
            print(f"  {divider(W-2)}")
            
            for rank, payout in enumerate(data['payouts'], 1):
                name = (payout['player_name'] or '(Unknown)')[:17]
                war_h = payout['num_war_hits'] if payout['num_war_hits'] > 0 else 0
                bon = payout.get('num_bonus_hits', 0) if payout.get('num_bonus_hits', 0) > 0 else 0
                asst = payout['num_assists'] if payout['num_assists'] > 0 else 0
                out = payout['num_outside'] if payout['num_outside'] > 0 else 0
                
                # Format bonus hits first, then apply color (ensures proper alignment with ANSI codes)
                bon_str = f"{bon:>3}"
                bon_display = f"{Colors.GREEN}{bon_str}{Colors.RESET}" if bon > 0 else bon_str
                
                # Color payout based on amount
                payout_amount = payout['player_share']
                if payout_amount >= 50000:
                    payout_color = Colors.GREEN
                elif payout_amount >= 20000:
                    payout_color = Colors.CYAN
                else:
                    payout_color = Colors.BRIGHT_BLACK
                
                payout_line = (
                    f"  {rank:<4} {name:<18} {war_h:>3} {bon_display} {asst:>3} {out:>3}  "
                    f"{payout['total_respect']:>10.2f}  {payout['respect_pct']:>5.1f}%  "
                    f"{payout_color}${payout_amount:>13,.2f}{Colors.RESET}"
                )
                print(payout_line)
        
        print(f"\n{divider(W)}\n")

    def manage_prices(self, action, item_id=None, price=None, category=None, limit=25, min_uses=5, event_type="used", output_path="data/manual_price_overrides.csv"):
        """Manage item market prices"""
        if action == "update":
            result = self.services.item_price_service.update_market_prices()
            if result.get("updated_count", 0) > 0:
                print(success(f"✓ Updated {result['updated_count']} item prices from API"))
                if result.get("error_count", 0) > 0:
                    print(warning(f"  ({result['error_count']} errors)"))
            else:
                print(warning("✗ No prices updated"))

        elif action == "update_all":
            result = self.services.item_price_service.update_market_prices_bulk()
            if result.get("updated_count", 0) > 0:
                print(success(f"✓ Updated {result['updated_count']} item prices via v2 torn/{{id}}/items"))
                if result.get("error_count", 0) > 0:
                    print(warning(f"  ({result['error_count']} row-level errors)"))
            elif result.get("message"):
                print(warning(f"✗ {result['message']}"))
            else:
                print(warning("✗ No prices updated by v2 torn/{id}/items"))
        
        elif action == "show":
            if category:
                self.services.database.execute(
                    "SELECT item_id, item_name, item_category, market_average, manual_override FROM item_prices WHERE item_category = ? ORDER BY market_average DESC LIMIT ?",
                    (category, limit)
                )
                print(f"\n{header(f'Item Prices - {category} Category')}\n")
            else:
                self.services.database.execute(
                    "SELECT item_id, item_name, item_category, market_average, manual_override FROM item_prices ORDER BY market_average DESC LIMIT ?",
                    (limit,)
                )
                print(f"\n{header(f'Item Prices (Top {limit})')}\n")
            
            rows = self.services.database.fetchall()
            if not rows:
                print("No prices found")
                return
            
            print(f"{'Item ID':<8} {'Name':<25} {'Category':<12} {'Price':<12}")
            print(divider(70))
            
            for row in rows:
                item_id = row["item_id"]
                name = row["item_name"][:24]
                cat = row["item_category"]
                price_val = row["manual_override"] if row["manual_override"] else row["market_average"]
                price_str = money(price_val) if price_val else "$0.00"
                source = "(manual)" if row["manual_override"] else ""
                print(f"{item_id:<8} {name:<25} {cat:<12} {price_str:<12} {source}")
            print()
        
        elif action == "set":
            if item_id is None or price is None:
                print(warning("✗ --item_id and --price required for 'set' action"))
                return
            
            self.services.item_price_service.set_manual_price(item_id, price)
            print(success(f"✓ Set manual price for item {item_id}: {money(price)}"))

        elif action == "missing":
            rows = self.services.item_price_service.missing_prices(
                limit=limit,
                min_uses=min_uses,
                event_type=event_type,
            )

            label = (event_type or "").strip() or "all events"
            print(f"\n{header(f'Missing Effective Prices ({label})')}\n")

            if not rows:
                print(success("No missing-price items found for this filter."))
                return

            print(f"{'Item ID':<8} {'Name':<28} {'Category':<12} {'Uses':>6} {'Qty':>8} {'Last Seen':<18}")
            print(divider(88))

            from datetime import datetime

            for row in rows:
                last_seen_ts = row["last_seen"] or 0
                last_seen = datetime.fromtimestamp(last_seen_ts).strftime("%Y-%m-%d %H:%M") if last_seen_ts else "-"
                print(
                    f"{row['item_id']:<8} "
                    f"{(row['item_name'] or '?')[:27]:<28} "
                    f"{(row['item_category'] or '?')[:11]:<12} "
                    f"{row['usage_count']:>6} "
                    f"{int(row['total_quantity'] or 0):>8} "
                    f"{last_seen:<18}"
                )

            print("\nSuggested commands:")
            for row in rows[:10]:
                print(f"  python main.py prices set --item_id {row['item_id']} --price <amount>")
            print()

        elif action == "export_manual":
            result = self.services.item_price_service.export_manual_prices(output_path=output_path)
            print(success(f"✓ Exported {result['count']} manual override rows"))
            print(info(f"  File: {result['path']}"))
        
        else:
            print(warning(f"✗ Unknown action: {action}"))