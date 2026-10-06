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
            success_price="Price in Torn dollars per successful revive",
            failure_price="Price in Torn dollars per failed attempt",
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
                    if None in (target_faction_id, start_at, amount, success_price, failure_price):
                        raise ValueError("Provide target_faction_id, start_at, amount, success_price and failure_price.")
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

    @staticmethod
    async def send_chunks(interaction, text):
        for start in range(0, len(text), 1900):
            await interaction.followup.send(
                text[start:start + 1900], ephemeral=True, allowed_mentions=discord.AllowedMentions.none(),
            )
