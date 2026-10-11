"""Private revive-log and contract controls, background sync and payment notices."""

from __future__ import annotations

import asyncio
import logging
import time

import discord
from discord import app_commands

from repositories.revive_request_repository import ReviveRequestRepository
from services.database import Database
from services.http_client import RateLimitError
from services.revive_operations import ReviveOperations, revive_payment_text
from services.revive_chance import ReviveChanceTracker
from utils.logger import Logger


REVIVE_TIMEOUT_SETTING = "revive_request_timeout_minutes"
REVIVE_MIN_CHANCE_SETTING = "revive_min_chance"
REVIVE_REGULAR_ROLE_SETTING = "revive_regular_role_id"
REVIVE_CONTRACT_ROLE_SETTING = "revive_contract_role_id"
DEFAULT_REVIVE_TIMEOUT_MINUTES = 15
MAX_REVIVE_TIMEOUT_MINUTES = 1440


def _int_setting(store, key):
    value = store.get_setting(key)
    try:
        return int(str(value).strip()) if value not in (None, "") else None
    except ValueError:
        return None


def revive_timeout_minutes(store) -> int:
    """Minutes a revive request stays open (0 disables expiry)."""
    value = _int_setting(store, REVIVE_TIMEOUT_SETTING)
    if value is None:
        return DEFAULT_REVIVE_TIMEOUT_MINUTES
    return max(0, min(MAX_REVIVE_TIMEOUT_MINUTES, value))


def revive_min_chance(store) -> float | None:
    value = store.get_setting(REVIVE_MIN_CHANCE_SETTING)
    try:
        chance = float(value) if value not in (None, "") else None
    except ValueError:
        return None
    return chance if chance and chance > 0 else None


def revive_chance_below_minimum(store, chance) -> bool:
    """Unknown estimates are never below the minimum."""
    minimum = revive_min_chance(store)
    return minimum is not None and chance is not None and float(chance) < minimum


def revive_ping_role_id(store, contract: bool) -> int | None:
    key = REVIVE_CONTRACT_ROLE_SETTING if contract else REVIVE_REGULAR_ROLE_SETTING
    return _int_setting(store, key)


def contract_price_keys(provider_tag) -> tuple[str, str]:
    tag = str(provider_tag or "").upper()
    return f"revive_contract_success_price_{tag}", f"revive_contract_failure_price_{tag}"


def contract_default_prices(store, provider_tag) -> tuple[int | None, int | None]:
    success_key, failure_key = contract_price_keys(provider_tag)
    return _int_setting(store, success_key), _int_setting(store, failure_key)


def register_revive_log_command(bot, settings, operations, default_direction="both"):
    factions = [
        app_commands.Choice(name=f"{f.tag} - {f.name}"[:100], value=f.tag)
        for f in settings.list_factions()[:25]
    ]

    @bot.tree.command(name="ti_revive_logs", description="Privately view incoming/outgoing faction revive logs")
    @app_commands.choices(faction=factions, direction=[
        app_commands.Choice(name=name.title(), value=name) for name in ("incoming", "outgoing", "both")
    ])
    async def ti_revive_logs(
        interaction: discord.Interaction, faction: str, direction: str = default_direction, limit: int = 10,
    ):
        await interaction.response.defer(ephemeral=True)
        selected = settings.get_faction(faction)
        if selected is None or not selected.faction_id:
            await interaction.followup.send("Unknown faction or missing Torn faction ID.", ephemeral=True)
            return
        try:
            rows = operations.recent_logs(selected.faction_id, direction, limit)
        except ValueError as exc:
            await interaction.followup.send(str(exc), ephemeral=True)
            return
        lines = [
            f"<t:{row['timestamp']}:f> {discord.utils.escape_markdown(str(row['reviver_name']))} -> "
            f"{discord.utils.escape_markdown(str(row['target_name']))}: {row['result']}, "
            f"recorded chance {row['chance']:.2f}% (at attempt, not current), "
            f"ED at attempt: {'yes' if row['target_early_discharge'] else 'no'}"
            for row in rows
        ]
        await DiscordReviveOperations.send_chunks(
            interaction, "\n".join(lines) or "No synced faction revive logs yet.",
        )


class DiscordReviveOperations:
    def __init__(self, bot, settings, gateway, store, can_manage, logger=None, operations=None):
        self.bot = bot
        self.settings = settings
        self.store = store
        self.gateway = gateway
        self.can_manage = can_manage
        self.logger = logger or logging.getLogger(__name__)
        self.operations = operations or ReviveOperations(settings.database_path, gateway)
        self.chance_tracker = ReviveChanceTracker(store, settings, self.logger)
        self.tasks = {}
        self.register_commands()

    def start(self, monitor_logs=True):
        if monitor_logs and self.gateway is None:
            self.logger.warning("Revive-log monitoring is unavailable: no Torn gateway configured.")
        for faction in self.settings.list_factions() if monitor_logs and self.gateway is not None else []:
            if faction.faction_id and faction.api_keys:
                task = self.tasks.get(faction.tag)
                if task is None or task.done():
                    if task is not None and not task.cancelled() and task.exception():
                        self.logger.error(f"[{faction.tag}] Revive-log task stopped: {task.exception()}")
                    self.tasks[faction.tag] = asyncio.create_task(self.watch_logs(faction))
        task = self.tasks.get("payment-dms")
        if task is None or task.done():
            if task is not None and not task.cancelled() and task.exception():
                self.logger.error(f"Revive payment DM task stopped: {task.exception()}")
            self.tasks["payment-dms"] = asyncio.create_task(self.watch_payment_dms())

    def reconcile(self):
        database = Database(self.settings, Logger())
        try:
            return ReviveRequestRepository(database).reconcile_against_database(limit=500)
        finally:
            database.close()

    async def watch_logs(self, faction):
        while not self.bot.is_closed():
            try:
                await asyncio.to_thread(self.operations.sync, faction)
                await asyncio.to_thread(self.reconcile)
            except Exception as exc:
                self.logger.warning(f"[{faction.tag}] Revive-log sync failed: {type(exc).__name__}: {exc}")
            await asyncio.sleep(max(8, int(self.settings.discord_revive_poll_seconds)))

    async def watch_payment_dms(self):
        while not self.bot.is_closed():
            try:
                await self.deliver_payment_dms()
            except Exception as exc:
                self.logger.warning(f"Revive payment DM watcher failed: {type(exc).__name__}: {exc}")
            await asyncio.sleep(5)

    async def deliver_payment_dms(self):
        for row in self.operations.payment_notifications():
            try:
                user = self.bot.get_user(int(row["discord_user_id"]))
                if user is None:
                    user = await self.bot.fetch_user(int(row["discord_user_id"]))
                reviver_id = int(row["fulfilled_by_id"] or 0)
                name = discord.utils.escape_markdown(str(row["fulfilled_by_name"] or f"User {reviver_id}"))
                reviver = f"[{name}](https://www.torn.com/profiles.php?XID={reviver_id})"
                context = self.operations.payment_context(row["request_id"])
                payment = revive_payment_text(context, reviver)
                if context["needs_review"]:
                    self.logger.warning(f"Contract coverage needs review for revive request {row['request_id']}.")
                await user.send(
                    f"Your revive request for **{discord.utils.escape_markdown(str(row['target_name'] or row['target_id']))}** "
                    f"was fulfilled by {reviver}.\n{payment}\nRequest: `{row['request_id']}`",
                    allowed_mentions=discord.AllowedMentions.none(),
                )
                self.operations.mark_payment_notification(row["request_id"], "sent")
            except discord.Forbidden:
                self.operations.mark_payment_notification(row["request_id"], "blocked")
                self.logger.warning(f"Requester DMs are blocked for revive request {row['request_id']}.")
            except (discord.HTTPException, OSError) as exc:
                self.logger.warning(f"Revive payment DM failed for {row['request_id']}: {type(exc).__name__}: {exc}")

    def register_commands(self):
        register_revive_log_command(self.bot, self.settings, self.operations, default_direction="incoming")
        factions = [
            app_commands.Choice(name=f"{f.tag} - {f.name}"[:100], value=f.tag)
            for f in self.settings.list_factions()[:25]
        ]

        @self.bot.tree.command(name="ti_revive_contract", description="Manage faction revive contracts and chance estimates")
        @app_commands.default_permissions(manage_channels=True)
        @app_commands.choices(provider=factions, action=[
            app_commands.Choice(name=name.title(), value=name)
            for name in ("start", "end", "current", "report", "estimate")
        ])
        @app_commands.describe(
            provider="Configured faction supplying the revives",
            target_faction_id="Faction receiving contracted revives",
            start_at="Contract start time as Unix timestamp",
            amount="Successful-revive target; failures are counted separately",
            success_price="Price per successful revive (defaults to /ti_revive_settings)",
            failure_price="Price per failed attempt (defaults to /ti_revive_settings)",
            contract_id="Contract ID for end, report or estimate",
            target_id="Target Torn ID for a contract chance estimate",
        )
        async def ti_revive_contract(
            interaction: discord.Interaction, action: str, provider: str | None = None,
            target_faction_id: int | None = None, start_at: int | None = None,
            amount: int | None = None, success_price: int | None = None,
            failure_price: int | None = None, contract_id: str | None = None,
            target_id: int | None = None,
        ):
            if not self.can_manage(interaction):
                await interaction.response.send_message("Manage Channels permission is required.", ephemeral=True)
                return
            await interaction.response.defer(ephemeral=True)
            now = int(time.time())
            try:
                if action == "start":
                    selected = self.settings.get_faction(provider) if provider else None
                    if selected is None or not selected.faction_id or not selected.api_keys:
                        raise ValueError("Choose a provider with a configured faction ID and key pool.")
                    default_success, default_failure = contract_default_prices(self.store, selected.tag)
                    success_price = default_success if success_price is None else success_price
                    failure_price = default_failure if failure_price is None else failure_price
                    if None in (target_faction_id, start_at, amount, success_price, failure_price):
                        raise ValueError(
                            "Provide target_faction_id, start_at, amount, success_price and failure_price "
                            "(prices can default from /ti_revive_settings)."
                        )
                    contract_id = self.operations.start_contract(
                        selected, target_faction_id, start_at, amount, success_price,
                        failure_price, interaction.user.id, now,
                    )
                    text = f"Contract `{contract_id}` started. Historical logs will sync in the background. Use report to view counts and end to close it."
                elif action == "end":
                    if not contract_id:
                        raise ValueError("Provide a contract_id.")
                    self.operations.end_contract(contract_id, now)
                    text = f"Contract `{contract_id}` ended at <t:{now}:f>. Late-synced logs within its window still count."
                elif action == "current":
                    rows = self.operations.contracts(active_only=True)
                    text = "\n".join(
                        f"`{row['contract_id']}` {row['provider_tag']} -> faction {row['target_faction_id']}, "
                        f"since <t:{row['start_at']}:f>, target {row['success_target']} successes"
                        for row in rows
                    ) or "No active revive contracts."
                elif action == "report":
                    if not contract_id:
                        raise ValueError("Provide a contract_id.")
                    row = self.operations.contract_summary(contract_id, now)
                    text = (
                        f"Contract `{row['contract_id']}`: {row['provider_tag']} -> faction {row['target_faction_id']}\n"
                        f"Start: <t:{row['start_at']}:f>\n"
                        f"End: {'<t:' + str(row['end_at']) + ':f>' if row['end_at'] else 'active (manual end)'}\n"
                        f"Successes: {row['successes']}/{row['success_target']} at ${row['success_price']:,} each\n"
                        f"Progress goal reached: {'yes' if row['target_reached'] else 'no'}; no automatic end or billing cap.\n"
                        f"Failures: {row['failures']} at ${row['failure_price']:,} each\n"
                        f"Unknown results (not billed): {row['unknown_results']}\nTotal due: ${row['total_due']:,}\n"
                        "Counts reflect synced logs only; allow background sync to complete."
                    )
                elif action == "estimate":
                    if not contract_id or target_id is None:
                        raise ValueError("Provide contract_id and target_id.")
                    contract = self.operations.contract_summary(contract_id, now)
                    if contract["end_at"] is not None:
                        raise ValueError("Chance estimates require an active contract.")
                    profile = await asyncio.to_thread(self.operations.profile, target_id)
                    if profile["faction_id"] != contract["target_faction_id"]:
                        raise ValueError("That target is not in the contracted target faction.")
                    estimate = await asyncio.to_thread(self.chance_tracker.estimate, target_id, now)
                    text = (
                        f"Contract estimate for {discord.utils.escape_markdown(profile['target_name'])}:\n"
                        f"{estimate.text()}\n"
                        f"Current hospital state: {profile['state']}\n"
                    )
                else:
                    raise ValueError("Unknown contract action.")
            except (ValueError, RuntimeError, OSError, RateLimitError) as exc:
                await interaction.followup.send(str(exc), ephemeral=True)
                return
            await self.send_chunks(interaction, text)

        self.register_settings_command(factions)

    def settings_text(self) -> str:
        timeout = revive_timeout_minutes(self.store)
        minimum = revive_min_chance(self.store)
        regular = revive_ping_role_id(self.store, contract=False)
        contract = revive_ping_role_id(self.store, contract=True)
        lines = [
            f"Request timeout: {f'{timeout} minutes' if timeout else 'disabled'} (claiming restarts the timer)",
            f"Minimum revive chance: {f'{minimum:g}%' if minimum is not None else 'off'} "
            "(skill-100 estimate; unknown estimates are accepted)",
            f"Regular request role: {f'<@&{regular}>' if regular else 'none'}",
            f"Contract request role: {f'<@&{contract}>' if contract else 'none'}",
            "Default contract prices:",
        ]
        for faction in self.settings.list_factions():
            success, failure = contract_default_prices(self.store, faction.tag)
            lines.append(
                f"- {faction.tag}: success {f'${success:,}' if success is not None else 'unset'}, "
                f"failure {f'${failure:,}' if failure is not None else 'unset'}"
            )
        return "\n".join(lines)

    def register_settings_command(self, factions):
        @self.bot.tree.command(name="ti_revive_settings", description="Configure revive request timeouts, pings and contract defaults")
        @app_commands.default_permissions(manage_channels=True)
        @app_commands.choices(
            action=[
                app_commands.Choice(name="Status", value="status"),
                app_commands.Choice(name="Configure", value="configure"),
            ],
            provider=factions,
            clear_role=[
                app_commands.Choice(name="Regular role", value="regular"),
                app_commands.Choice(name="Contract role", value="contract"),
                app_commands.Choice(name="Both roles", value="both"),
            ],
        )
        @app_commands.describe(
            timeout_minutes=f"Minutes before an unrevived request expires (0 disables, max {MAX_REVIVE_TIMEOUT_MINUTES})",
            min_chance="Reject requests whose estimated revive chance is below this percent (0 disables)",
            regular_role="Role pinged for regular revive requests",
            contract_role="Role pinged for contract revive requests",
            clear_role="Stop pinging a role",
            provider="Providing faction for the default contract prices",
            success_price="Default price per successful contract revive for the provider",
            failure_price="Default price per failed contract attempt for the provider",
        )
        async def ti_revive_settings(
            interaction: discord.Interaction,
            action: str = "status",
            timeout_minutes: app_commands.Range[int, 0, MAX_REVIVE_TIMEOUT_MINUTES] | None = None,
            min_chance: app_commands.Range[float, 0.0, 100.0] | None = None,
            regular_role: discord.Role | None = None,
            contract_role: discord.Role | None = None,
            clear_role: str | None = None,
            provider: str | None = None,
            success_price: app_commands.Range[int, 0] | None = None,
            failure_price: app_commands.Range[int, 0] | None = None,
        ):
            if not self.can_manage(interaction):
                await interaction.response.send_message("Manage Channels permission is required.", ephemeral=True)
                return
            if action == "configure":
                if (success_price is not None or failure_price is not None) and provider is None:
                    await interaction.response.send_message(
                        "Choose a provider when setting default contract prices.", ephemeral=True,
                    )
                    return
                changes = []
                if timeout_minutes is not None:
                    self.store.set_setting(REVIVE_TIMEOUT_SETTING, str(int(timeout_minutes)))
                    changes.append("timeout")
                if min_chance is not None:
                    self.store.set_setting(REVIVE_MIN_CHANCE_SETTING, str(float(min_chance)) if min_chance > 0 else "")
                    changes.append("minimum chance")
                if clear_role in ("regular", "both"):
                    self.store.set_setting(REVIVE_REGULAR_ROLE_SETTING, "")
                    changes.append("regular role cleared")
                if clear_role in ("contract", "both"):
                    self.store.set_setting(REVIVE_CONTRACT_ROLE_SETTING, "")
                    changes.append("contract role cleared")
                if regular_role is not None:
                    self.store.set_setting(REVIVE_REGULAR_ROLE_SETTING, str(regular_role.id))
                    changes.append("regular role")
                if contract_role is not None:
                    self.store.set_setting(REVIVE_CONTRACT_ROLE_SETTING, str(contract_role.id))
                    changes.append("contract role")
                success_key, failure_key = contract_price_keys(provider)
                if success_price is not None:
                    self.store.set_setting(success_key, str(int(success_price)))
                    changes.append(f"{provider} success price")
                if failure_price is not None:
                    self.store.set_setting(failure_key, str(int(failure_price)))
                    changes.append(f"{provider} failure price")
                header = f"Updated: {', '.join(changes)}." if changes else "No settings were provided; nothing changed."
            else:
                header = "Revive request settings:"
            await interaction.response.send_message(
                f"{header}\n{self.settings_text()}",
                ephemeral=True,
                allowed_mentions=discord.AllowedMentions.none(),
            )

    @staticmethod
    async def send_chunks(interaction, text):
        for start in range(0, len(text), 1900):
            await interaction.followup.send(
                text[start:start + 1900], ephemeral=True, allowed_mentions=discord.AllowedMentions.none(),
            )
