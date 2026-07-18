"""
modules/crimes/report.py

OC reports:
- oc_item_audit: required items vs current holders.
- oc_cpr: CPR baseline and threshold checks.
"""

from pathlib import Path
import json
from utils.colors import success, warning, error, info, header, muted, highlight


class CrimeReport:

    DEFAULT_RULES = {
        "tiers": {
            "1": {"default_min_cpr": 0},
            "2": {"default_min_cpr": 60},
            "3": {"default_min_cpr": 70},
            "4": {"default_min_cpr": 70},
            "5": {"default_min_cpr": 70},
            "6": {"default_min_cpr": 70},
            "7": {"default_min_cpr": 60},
            "8": {"default_min_cpr": 60},
            "9": {"default_min_cpr": 85},
            "10": {"default_min_cpr": 90},
        },
        "crime_overrides": {},
    }

    def __init__(self, queries, logger):
        self.queries = queries
        self.logger = logger

    #########################################################

    def _load_rules(self):

        rules_path = self._rules_path()
        legacy_path = Path(__file__).resolve().parents[2] / "for context" / "oc_rules.json"

        if not rules_path.exists():
            if legacy_path.exists():
                try:
                    with legacy_path.open("r", encoding="utf-8") as f:
                        legacy_rules = json.load(f)
                    self._save_rules(self._normalize_rules(legacy_rules))
                except Exception as exc:
                    self.logger.warning(f"Could not parse legacy rules file {legacy_path}: {exc}")
                    self._save_rules(self.DEFAULT_RULES)
            else:
                self._save_rules(self.DEFAULT_RULES)

        try:
            with rules_path.open("r", encoding="utf-8") as f:
                return self._normalize_rules(json.load(f))
        except Exception as exc:
            self.logger.warning(f"Could not parse rules file {rules_path}: {exc}")
            return self._normalize_rules(self.DEFAULT_RULES)

    #########################################################

    def _rules_path(self):
        root = Path(__file__).resolve().parents[2]
        path = root / "data" / "oc_rules.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    #########################################################

    def _save_rules(self, rules):
        path = self._rules_path()
        with path.open("w", encoding="utf-8") as f:
            json.dump(rules, f, indent=2)

    #########################################################

    def _normalize_rules(self, rules):
        if not isinstance(rules, dict):
            rules = {}

        tiers = {}

        if isinstance(rules.get("tiers"), dict):
            for tier in range(1, 11):
                t = str(tier)
                payload = rules["tiers"].get(t, {})
                if isinstance(payload, dict):
                    tiers[t] = {"default_min_cpr": int(payload.get("default_min_cpr", 0) or 0)}
                else:
                    tiers[t] = {"default_min_cpr": 0}

        if not tiers:
            legacy = rules.get("default_min_cpr_by_difficulty", {})
            for tier in range(1, 11):
                t = str(tier)
                tiers[t] = {"default_min_cpr": int((legacy.get(t) if isinstance(legacy, dict) else 0) or 0)}

        crime_overrides = rules.get("crime_overrides", {})
        if not isinstance(crime_overrides, dict):
            crime_overrides = {}

        normalized_overrides = {}
        for crime_name, payload in crime_overrides.items():
            if not isinstance(payload, dict):
                continue
            positions = payload.get("positions", {})
            if not isinstance(positions, dict):
                positions = {}
            normalized_overrides[str(crime_name)] = {
                "default_min_cpr": int(payload.get("default_min_cpr", 0) or 0),
                "positions": {
                    str(position): int(value or 0)
                    for position, value in positions.items()
                },
            }

        return {
            "tiers": tiers,
            "crime_overrides": normalized_overrides,
        }

    #########################################################

    def _min_cpr(self, rules, crime_name, difficulty, position):
        overrides = rules.get("crime_overrides", {}) if isinstance(rules, dict) else {}

        selected = None
        for name, payload in overrides.items():
            if str(name).strip().lower() == str(crime_name).strip().lower():
                selected = payload if isinstance(payload, dict) else {}
                break

        if selected:
            positions = selected.get("positions", {}) or {}
            for pos_name, min_cpr in positions.items():
                if str(pos_name).strip().lower() == str(position).strip().lower():
                    return int(min_cpr or 0)
            if "default_min_cpr" in selected:
                return int(selected.get("default_min_cpr") or 0)

        tiers = rules.get("tiers", {}) if isinstance(rules, dict) else {}
        tier_payload = tiers.get(str(difficulty), {}) if isinstance(tiers, dict) else {}
        if isinstance(tier_payload, dict):
            return int(tier_payload.get("default_min_cpr", 0) or 0)

        return 0

    #########################################################

    def rules_show(self):
        rules = self._load_rules()

        lines = []
        lines.append(f"\n{header('========== OC RULES ==========')}")
        lines.append(highlight("Tier defaults (1-10):"))
        for tier in range(1, 11):
            t = str(tier)
            min_cpr = int(rules.get("tiers", {}).get(t, {}).get("default_min_cpr", 0) or 0)
            lines.append(f"- Tier {tier}: min CPR {min_cpr}%")

        lines.append(f"\n{highlight('Crime overrides:')}")
        overrides = rules.get("crime_overrides", {})
        if not overrides:
            lines.append(muted("- none"))
        else:
            for crime_name, payload in sorted(overrides.items(), key=lambda x: x[0].lower()):
                lines.append(
                    f"- {crime_name}: default {int(payload.get('default_min_cpr', 0) or 0)}%"
                )
                positions = payload.get("positions", {})
                if positions:
                    for pos, value in sorted(positions.items(), key=lambda x: x[0].lower()):
                        lines.append(f"  {pos}: {int(value or 0)}%")

        lines.append(f"\nRules file: {info(str(self._rules_path()))}")
        lines.append(header("==============================\n"))
        return "\n".join(lines)

    #########################################################

    def rules_set_tier(self, tier, min_cpr):
        rules = self._load_rules()
        t = str(int(tier))
        if int(tier) < 1 or int(tier) > 10:
            raise ValueError("tier must be between 1 and 10")

        rules.setdefault("tiers", {})[t] = {"default_min_cpr": int(min_cpr)}
        self._save_rules(rules)
        return f"Set tier {tier} minimum CPR to {int(min_cpr)}%"

    #########################################################

    def rules_set_crime(self, crime_name, min_cpr):
        name = str(crime_name or "").strip()
        if not name:
            raise ValueError("crime_name is required")

        rules = self._load_rules()
        overrides = rules.setdefault("crime_overrides", {})
        payload = overrides.setdefault(name, {"default_min_cpr": 0, "positions": {}})
        payload["default_min_cpr"] = int(min_cpr)
        payload.setdefault("positions", {})
        self._save_rules(rules)

        return f"Set crime override '{name}' default minimum CPR to {int(min_cpr)}%"

    #########################################################

    def rules_set_position(self, crime_name, position, min_cpr):
        name = str(crime_name or "").strip()
        pos = str(position or "").strip()
        if not name or not pos:
            raise ValueError("crime_name and position are required")

        rules = self._load_rules()
        overrides = rules.setdefault("crime_overrides", {})
        payload = overrides.setdefault(name, {"default_min_cpr": 0, "positions": {}})
        payload.setdefault("positions", {})[pos] = int(min_cpr)
        self._save_rules(rules)

        return (
            f"Set crime override '{name}' position '{pos}' minimum CPR to {int(min_cpr)}%"
        )

    #########################################################

    def rules_remove_crime(self, crime_name):
        name = str(crime_name or "").strip()
        if not name:
            raise ValueError("crime_name is required")

        rules = self._load_rules()
        overrides = rules.setdefault("crime_overrides", {})
        if name in overrides:
            del overrides[name]
            self._save_rules(rules)
            return f"Removed crime override '{name}'"

        return f"Crime override '{name}' not found"

    #########################################################

    def item_audit(self):

        slots = self.queries.active_slots()
        members = self.queries.members()
        member_ids = {int(member["user_id"]) for member in members}
        loans = [
            row
            for row in self.queries.outstanding_loans()
            if int(row.get("player_id") or 0) in member_ids
        ]

        active_statuses = {"recruiting", "planning"}
        slots = [
            s
            for s in slots
            if str(s.get("status") or "").strip().lower() in active_statuses
            and int(s.get("required_item_id") or 0) > 0
        ]

        assigned_slots = [s for s in slots if int(s.get("user_id") or 0) > 0]
        unassigned_slots = [s for s in slots if int(s.get("user_id") or 0) <= 0]

        if not slots:
            return "No active recruiting/planning OC slots found. Run: python main.py sync crimes --mode live"

        req_by_user_item = {}
        req_available_by_user_item = {}
        req_by_item_assigned = {}
        req_by_item_assigned_available = {}
        req_by_item_unassigned = {}
        req_by_item_unassigned_available = {}
        req_details = {}
        req_item_names = {}

        for slot in assigned_slots:
            key = (int(slot["user_id"]), int(slot["required_item_id"]))
            req_by_user_item[key] = req_by_user_item.get(key, 0) + 1
            req_by_item_assigned[key[1]] = req_by_item_assigned.get(key[1], 0) + 1
            if int(slot.get("item_is_available") or 0) == 1:
                req_available_by_user_item[key] = req_available_by_user_item.get(key, 0) + 1
                req_by_item_assigned_available[key[1]] = req_by_item_assigned_available.get(key[1], 0) + 1
            req_details.setdefault(key, {
                "user_name": slot["user_name"],
                "item_name": slot["required_item_name"],
            })
            req_item_names[key[1]] = slot["required_item_name"]

        for slot in unassigned_slots:
            item_id = int(slot["required_item_id"])
            req_by_item_unassigned[item_id] = req_by_item_unassigned.get(item_id, 0) + 1
            if int(slot.get("item_is_available") or 0) == 1:
                req_by_item_unassigned_available[item_id] = req_by_item_unassigned_available.get(item_id, 0) + 1
            req_item_names[item_id] = slot["required_item_name"]

        required_item_ids = set(req_by_item_assigned) | set(req_by_item_unassigned)
        all_armoury_stock = self.queries.faction_item_stock()
        all_deposited_totals = self.queries.faction_item_deposited_totals()
        alias_ids_by_name = self.queries.armoury_item_ids_by_name(req_item_names.values())
        equivalent_ids = {}
        for item_id, item_name in req_item_names.items():
            ids = {int(item_id)}
            ids.update(alias_ids_by_name.get(str(item_name).strip().lower(), set()))
            equivalent_ids[int(item_id)] = ids

        holders = {}
        holders_by_item = {}
        for row in loans:
            key = (int(row["player_id"]), int(row["item_id"]))
            holders[key] = holders.get(key, 0) + int(row["quantity_out"] or 0)
            item_id = int(row["item_id"])
            holders_by_item[item_id] = holders_by_item.get(item_id, 0) + int(row["quantity_out"] or 0)

        correct = []
        fulfilled_by_stock = []
        missing = []
        assigned_missing_by_item = {}

        for key, req_qty in req_by_user_item.items():
            held_qty = holders.get(key, 0)
            ok_qty = min(req_qty, held_qty)
            if ok_qty > 0:
                correct.append((key, ok_qty, req_qty))

            available_qty = min(
                req_qty - ok_qty,
                int(req_available_by_user_item.get(key, 0)),
            )
            if available_qty > 0:
                fulfilled_by_stock.append((key, available_qty, req_qty))

            need = req_qty - ok_qty - available_qty
            if need > 0:
                missing.append((key, need, req_qty))
                _, item_id = key
                assigned_missing_by_item[item_id] = assigned_missing_by_item.get(item_id, 0) + need

            if held_qty > ok_qty:
                holders[key] = held_qty - ok_qty
            else:
                holders.pop(key, None)

        unassigned_missing_by_item = {}
        for item_id, total in req_by_item_unassigned.items():
            available = int(req_by_item_unassigned_available.get(item_id, 0))
            need = max(0, int(total) - available)
            if need > 0:
                unassigned_missing_by_item[item_id] = need

        wrong_holder = []
        returnable = []

        for key, qty in holders.items():
            user_id, item_id = key
            item_needed = (
                int(assigned_missing_by_item.get(item_id, 0))
                + int(unassigned_missing_by_item.get(item_id, 0))
            )

            if item_needed > 0:
                needed_by = [
                    detail["user_name"]
                    for (u_id, i_id), detail in req_details.items()
                    if i_id == item_id and u_id != user_id
                ]
                unassigned_need = unassigned_missing_by_item.get(item_id, 0)
                if unassigned_need > 0:
                    needed_by.append(f"{unassigned_need} unassigned recruiting/planning slot(s)")
                wrong_holder.append((key, qty, needed_by))
            else:
                returnable.append((key, qty))

        required_holders = [
            row
            for row in loans
            if any(
                int(row.get("item_id") or 0) in equivalent_ids.get(int(req_id), {int(req_id)})
                for req_id in required_item_ids
            )
        ]

        stock_needed = []
        all_required_ids = set(req_by_item_assigned) | set(req_by_item_unassigned)
        for item_id in all_required_ids:
            required_total = req_by_item_assigned.get(item_id, 0) + req_by_item_unassigned.get(item_id, 0)
            available_total = (
                int(req_by_item_assigned_available.get(item_id, 0))
                + int(req_by_item_unassigned_available.get(item_id, 0))
            )
            alias_ids = equivalent_ids.get(int(item_id), {int(item_id)})
            held_total = sum(int(holders_by_item.get(alias_id, 0)) for alias_id in alias_ids)
            stock_total = sum(int(all_armoury_stock.get(alias_id, 0)) for alias_id in alias_ids)
            deposited_total = sum(int(all_deposited_totals.get(alias_id, 0)) for alias_id in alias_ids)
            has_mismatch_alias = any(int(alias_id) != int(item_id) for alias_id in alias_ids)

            # If crime and armoury use different item IDs for the same name,
            # treat deposited history as a stock floor to reduce false zeroes.
            if has_mismatch_alias and stock_total <= 0 and deposited_total > 0:
                stock_total = deposited_total

            short = max(0, int(required_total) - available_total - held_total - stock_total)
            if short > 0:
                any_req = next(
                    (detail for (u_id, i_id), detail in req_details.items() if i_id == item_id),
                    {"item_name": req_item_names.get(item_id, f"Item {item_id}")},
                )
                stock_needed.append((item_id, any_req["item_name"], short, required_total, held_total, available_total, stock_total))

        lines = []
        lines.append(f"\n{header('========== OC ITEM AUDIT ==========')}")
        lines.append(f"Active slots with item requirements (recruiting/planning): {info(str(len(slots)))}")
        lines.append(f"Assigned slots needing items now: {success(str(len(assigned_slots)))}")
        lines.append(f"Unassigned recruiting/planning slots (future demand): {warning(str(len(unassigned_slots)))}")
        lines.append(f"Outstanding loan rows: {info(str(len(loans)))}")
        lines.append(muted("-----------------------------------"))

        lines.append(f"\n{header('REQUIRED ITEM LOAN HOLDERS')}" )
        if required_holders:
            for row in sorted(required_holders, key=lambda r: (-int(r.get("quantity_out") or 0), str(r.get("player_name") or ""))):
                lines.append(
                    f"- {row['player_name']} holds {highlight(row['item_name'])} [{int(row['item_id'])}] x{int(row.get('quantity_out') or 0)}"
                )
        else:
            lines.append(muted("- none"))

        lines.append(f"\n{header('REQUIRED ITEM FACTION STOCK')}" )
        if required_item_ids:
            for item_id in sorted(required_item_ids):
                item_name = req_item_names.get(item_id, f"Item {item_id}")
                alias_ids = equivalent_ids.get(int(item_id), {int(item_id)})
                qty = sum(int(all_armoury_stock.get(alias_id, 0)) for alias_id in alias_ids)
                on_loan = sum(int(holders_by_item.get(alias_id, 0)) for alias_id in alias_ids)
                deposited_total = sum(int(all_deposited_totals.get(alias_id, 0)) for alias_id in alias_ids)
                has_mismatch_alias = any(int(alias_id) != int(item_id) for alias_id in alias_ids)
                if has_mismatch_alias and qty <= 0 and deposited_total > 0:
                    qty = deposited_total
                alias_note = ""
                if has_mismatch_alias:
                    alias_targets = ", ".join(
                        str(alias_id)
                        for alias_id in sorted(alias_ids)
                        if int(alias_id) != int(item_id)
                    )
                    alias_note = f" | alias match: {item_id}->{alias_targets}"
                lines.append(
                    f"- {highlight(item_name)} [{item_id}] in faction armoury: {qty} | on loan: {on_loan}{alias_note}"
                )
        else:
            lines.append(muted("- none"))

        lines.append(f"\n{success('CORRECT HOLDER')}")
        if correct:
            for (user_id, item_id), ok_qty, req_qty in sorted(correct, key=lambda x: (-x[1], x[0][0])):
                d = req_details[(user_id, item_id)]
                lines.append(
                    f"- {d['user_name']} holds {highlight(d['item_name'])} [{item_id}] | matched {ok_qty}/{req_qty}"
                )
        else:
            lines.append(muted("- none"))

        lines.append(f"\n{success('FULFILLED VIA ARMOURY AVAILABILITY')}")
        if fulfilled_by_stock:
            for (user_id, item_id), avail_qty, req_qty in sorted(fulfilled_by_stock, key=lambda x: (-x[1], x[0][0])):
                d = req_details[(user_id, item_id)]
                lines.append(
                    f"- {d['user_name']} has {highlight(d['item_name'])} [{item_id}] available via armoury {avail_qty}/{req_qty}"
                )
        else:
            lines.append(muted("- none"))

        lines.append(f"\n{warning('WRONG HOLDER')}")
        if wrong_holder:
            for (user_id, item_id), qty, needed_by in sorted(wrong_holder, key=lambda x: (-x[1], x[0][0])):
                holder = next(
                    (row["player_name"] for row in loans if int(row["player_id"]) == user_id and int(row["item_id"]) == item_id),
                    f"User {user_id}",
                )
                need_text = ", ".join(needed_by) if needed_by else "active OC users"
                item_name = next(
                    (row["item_name"] for row in loans if int(row["item_id"]) == item_id),
                    f"Item {item_id}",
                )
                lines.append(
                    f"- {holder} holds {highlight(item_name)} [{item_id}] x{qty} | needed by: {need_text}"
                )
        else:
            lines.append(muted("- none"))

        lines.append(f"\n{warning('RETURNABLE')}")
        if returnable:
            for (user_id, item_id), qty in sorted(returnable, key=lambda x: (-x[1], x[0][0])):
                holder = next(
                    (row["player_name"] for row in loans if int(row["player_id"]) == user_id and int(row["item_id"]) == item_id),
                    f"User {user_id}",
                )
                item_name = next(
                    (row["item_name"] for row in loans if int(row["item_id"]) == item_id),
                    f"Item {item_id}",
                )
                lines.append(f"- {holder} can return {highlight(item_name)} [{item_id}] x{qty}")
        else:
            lines.append(muted("- none"))

        lines.append(f"\n{error('STOCK NEEDED')}")
        if stock_needed:
            for item_id, item_name, short, required_total, held_total, available_total, stock_total in sorted(stock_needed, key=lambda x: (-x[2], x[1])):
                lines.append(
                    f"- {highlight(item_name)} [{item_id}] short {error(str(short))} (required {required_total}, held {held_total}, available {available_total}, in_armoury {stock_total})"
                )
        else:
            lines.append(muted("- none"))

        lines.append(f"\n{error('MISSING USER-ITEM PAIRS')}")
        if missing:
            for (user_id, item_id), need_qty, req_qty in sorted(missing, key=lambda x: (-x[1], x[0][0])):
                d = req_details[(user_id, item_id)]
                lines.append(
                    f"- {d['user_name']} needs {highlight(d['item_name'])} [{item_id}] x{need_qty} (required {req_qty})"
                )
        else:
            lines.append(muted("- none"))

        lines.append(f"\n{warning('FUTURE UNASSIGNED DEMAND')}")
        if req_by_item_unassigned:
            for item_id, qty in sorted(req_by_item_unassigned.items(), key=lambda x: (-x[1], x[0])):
                item_name = req_item_names.get(item_id, f"Item {item_id}")
                lines.append(
                    f"- {highlight(item_name)} [{item_id}] needed by {qty} unassigned recruiting/planning slot(s)"
                )
        else:
            lines.append(muted("- none"))

        lines.append(header("===================================\n"))
        return "\n".join(lines)

    #########################################################

    def outside_members_report(self, limit=200):

        outside = self.queries.members_outside_crimes()
        recruits = [
            row
            for row in outside
            if "recruit" in str(row.get("position") or "").strip().lower()
        ]
        eligible = [row for row in outside if row not in recruits]

        lines = []
        lines.append(f"\n{header('========== OC OUTSIDE MEMBERS ==========')}")
        lines.append("Current roster members not assigned to active recruiting/planning crimes")
        lines.append(f"Outside total: {info(str(len(outside)))}")
        lines.append(f"Eligible outside (non-recruit): {success(str(len(eligible)))}")
        lines.append(f"Recruits outside: {warning(str(len(recruits)))}")
        lines.append(muted("----------------------------------------"))

        if not outside:
            lines.append(success("All current roster members are in active OCs."))
            lines.append("========================================\n")
            return "\n".join(lines)

        lines.append(f"\n{success('AVAILABLE FOR ASSIGNMENT')}")
        if eligible:
            for row in eligible[: int(limit)]:
                name = row.get("user_name") or f"User {row.get('user_id')}"
                role = row.get("position") or "Member"
                lines.append(f"- {name} [{row['user_id']}] ({role})")
        else:
            lines.append(muted("- none"))

        lines.append(f"\n{warning('RECRUITS (CANNOT JOIN OCs)')}")
        if recruits:
            for row in recruits[: int(limit)]:
                name = row.get("user_name") or f"User {row.get('user_id')}"
                role = row.get("position") or "Recruit"
                lines.append(f"- {name} [{row['user_id']}] ({role})")
        else:
            lines.append(muted("- none"))

        shown = min(len(outside), int(limit))
        if shown < len(outside):
            lines.append(info(f"... {len(outside) - shown} more (increase --limit to show all)"))

        lines.append(header("========================================\n"))
        return "\n".join(lines)

    #########################################################

    def cpr_report(self):

        slots = self.queries.active_slots()
        stats = self.queries.cpr_stats()
        rules = self._load_rules()

        if not slots:
            return "No active recruiting/planning OC slots found. Run: python main.py sync crimes --mode live"

        best_lookup = {
            (int(row["user_id"]), int(row["crime_level"]), str(row["position"]).strip().lower()): int(row["best_cpr"] or 0)
            for row in stats
        }

        lines = []
        lines.append(f"\n{header('========== OC CPR REPORT ==========')}")

        fail_count = 0

        for slot in sorted(slots, key=lambda s: (int(s["difficulty"]), str(s["crime_name"]), str(s["slot_position"]), str(s["user_name"]))):
            level = int(slot["difficulty"] or 0)
            user_id = int(slot["user_id"] or 0)
            position = str(slot["slot_position"] or "")
            cpr = int(slot["checkpoint_pass_rate"] or 0)
            min_cpr = self._min_cpr(rules, slot["crime_name"], level, position)

            best = best_lookup.get((user_id, level, position.strip().lower()), cpr)
            if cpr < min_cpr - 2:
                status = error("LOW")
                cpr_display = error(f"{cpr}%")
                fail_count += 1
            elif cpr < min_cpr:
                status = warning("BORDERLINE")
                cpr_display = warning(f"{cpr}%")
                fail_count += 1
            else:
                status = success("OK")
                cpr_display = success(f"{cpr}%")

            min_display = header(f"{min_cpr}%")
            if cpr < min_cpr:
                best_display = warning(f"{best}%") if best < min_cpr else success(f"{best}%")
            else:
                best_display = success(f"{best}%")

            lines.append(
                f"L{level} {slot['crime_name']} | {position} | {slot['user_name']} | "
                f"CPR {cpr_display} | best {best_display} | min {min_display} | {status}"
            )

        lines.append(muted("-----------------------------------"))
        lines.append(f"Rows: {info(str(len(slots)))} | Below threshold: {error(str(fail_count)) if fail_count else success('0')}")
        lines.append(header("===================================\n"))

        return "\n".join(lines)
