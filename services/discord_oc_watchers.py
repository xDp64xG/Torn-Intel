"""Discord alerts for organized-crime payouts and member OC inactivity."""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone

import discord
from discord import app_commands

from repositories.oc_watch_repository import OcWatchRepository
from services.oc_watchers import DAY, as_list, format_duration, normalize_members

CRIMES_URL = "https://www.torn.com/factions.php?step=your#/tab=crimes"
PAYOUT_LOOKBACK_DAYS = 7
MAX_CRIME_PAGES = 10
POLL_SECONDS = 900
DEFAULTS = {
    "oc_payout": {"hours": 24},
    "oc_inactive": {"days": 3, "hour": 18},
}


class DiscordOcWatchers:
    def __init__(self, bot, settings, gateway, store, can_manage, logger=None, discord_user_for_torn_id=None):
        self.bot = bot
        self.settings = settings
        self.gateway = gateway
        self.store = store
        self.can_manage = can_manage
        self.logger = logger or logging.getLogger(__name__)
        self.discord_user_for_torn_id = discord_user_for_torn_id or (lambda _torn_id: None)
        self.repository = OcWatchRepository(settings.database_path)
        self.tasks = {}
        self.wakeups = {}
        self.register_commands()

    @staticmethod
    def key(kind, tag, name):
        return f"{kind}_{tag}_{name}"

    def get(self, kind, tag, name, default=None):
        value = self.store.get_setting(self.key(kind, tag, name))
        return value if value not in (None, "") else default

    def set(self, kind, tag, name, value):
        self.store.set_setting(self.key(kind, tag, name), str(value))

    def number(self, kind, tag, name):
        return int(self.get(kind, tag, name, DEFAULTS[kind][name]))

    def enabled(self, kind, tag):
        return self.get(kind, tag, "enabled") == "1"

    def wake(self, tag):
        event = self.wakeups.get(tag)
        if event is not None:
            event.set()

    def start(self):
        for faction in self.settings.list_factions():
            task = self.tasks.get(faction.tag)
            if task is None or task.done():
                if task is not None and not task.cancelled() and task.exception():
                    self.logger.error(f"[{faction.tag}] OC watcher task stopped: {task.exception()}")
                self.wakeups[faction.tag] = asyncio.Event()
                self.tasks[faction.tag] = asyncio.create_task(self.run_faction(faction))

    async def run_faction(self, faction):
        event = self.wakeups[faction.tag]
        while not self.bot.is_closed():
            event.clear()
            try:
                if self.enabled("oc_payout", faction.tag) or self.enabled("oc_inactive", faction.tag):
                    await self.poll(faction)
            except Exception as exc:
                self.logger.warning(f"[{faction.tag}] OC watcher failed: {type(exc).__name__}: {exc}")
            if self.bot.is_closed():
                break
            try:
                await asyncio.wait_for(event.wait(), timeout=POLL_SECONDS)
            except asyncio.TimeoutError:
                pass

    async def channel(self, channel_id):
        channel = self.bot.get_channel(int(channel_id))
        if channel is None:
            channel = await self.bot.fetch_channel(int(channel_id))
        return channel

    def fetch_completed_crimes(self, tag, from_ts):
        crimes = []
        for page in range(MAX_CRIME_PAGES):
            payload = self.gateway.faction_crimes_v2(
                category="completed", offset=page * 100, limit=100, pool=tag,
                filters="executed_at", from_ts=int(from_ts), sort="DESC",
            )
            if not isinstance(payload, dict) or payload.get("error"):
                raise RuntimeError(f"Torn crimes request failed: {(payload or {}).get('error')}")
            batch = as_list(payload.get("crimes"))
            crimes.extend(batch)
            if len(batch) < 100:
                break
        return crimes

    async def poll(self, faction, now=None):
        tag = faction.tag
        now = int(now or time.time())
        payout_on = self.enabled("oc_payout", tag)
        inactive_on = self.enabled("oc_inactive", tag)
        first_inactive_sync = inactive_on and not self.repository.has_participation(tag)
        crimes = []
        history_from = now
        if payout_on or first_inactive_sync:
            lookback = PAYOUT_LOOKBACK_DAYS
            if first_inactive_sync:
                lookback = max(lookback, self.number("oc_inactive", tag, "days") + 1)
            history_from = now - lookback * DAY
            crimes = await asyncio.to_thread(self.fetch_completed_crimes, tag, history_from)
        if payout_on:
            self.repository.record_crimes(tag, crimes)
            await self.send_payout_reminders(faction, now)
        if inactive_on:
            payload = await asyncio.to_thread(self.gateway.faction_members_v2, pool=tag)
            if not isinstance(payload, dict) or payload.get("error"):
                raise RuntimeError(f"Torn members request failed: {(payload or {}).get('error')}")
            members = normalize_members(payload)
            if members:
                self.repository.sync_participation(tag, members, crimes, now, history_from)
            await self.send_inactive_digest(faction, now)

    def configured_role(self, kind, tag, guild):
        role_id = self.get(kind, tag, "role_id")
        if not role_id or guild is None:
            return None
        return guild.get_role(int(role_id))

    async def send_payout_reminders(self, faction, now):
        tag = faction.tag
        hours = self.number("oc_payout", tag, "hours")
        overdue = self.repository.overdue_payouts(tag, now, hours)
        due = [
            row for row in overdue
            if not row["last_reminded_at"] or now - int(row["last_reminded_at"]) >= hours * 3600
        ]
        if not due:
            return
        channel = await self.channel(self.get("oc_payout", tag, "channel_id"))
        role = self.configured_role("oc_payout", tag, getattr(channel, "guild", None))
        lines = [
            f"**{row['crime_name']}** (T{row['difficulty']}, #{row['crime_id']}) - "
            f"${int(row['money']):,}, completed <t:{row['executed_at']}:R>"
            for row in overdue[:20]
        ]
        if len(overdue) > 20:
            lines.append(f"...and {len(overdue) - 20} more")
        embed = discord.Embed(
            title=f"[{tag}] OC payout reminder",
            description=(
                f"{len(overdue)} successful crime(s) have not been paid out after {hours}h:\n\n"
                + "\n".join(lines)
                + f"\n\n[Open faction crimes]({CRIMES_URL})"
            )[:4000],
            color=0xf1c40f,
        )
        await channel.send(
            content=role.mention if role else None,
            embed=embed,
            allowed_mentions=discord.AllowedMentions(
                everyone=False, users=False, roles=[role], replied_user=False,
            ) if role else discord.AllowedMentions.none(),
        )
        self.repository.mark_reminded(tag, [row["crime_id"] for row in overdue], now)

    def inactive_lines(self, tag, rows):
        lines, user_ids = [], []
        for row in rows:
            discord_id = self.discord_user_for_torn_id(int(row["user_id"]))
            who = f"<@{discord_id}>" if discord_id else row["user_name"]
            if discord_id:
                user_ids.append(int(discord_id))
            idle = format_duration(row["idle_seconds"])
            suffix = "+ (no OC since tracking began)" if row["never_seen_in_oc"] else ""
            lines.append(
                f"- {who} [[{row['user_id']}]](https://www.torn.com/profiles.php?XID={row['user_id']}) "
                f"- {idle}{suffix} without an OC"
            )
        return lines, user_ids

    async def send_inactive_digest(self, faction, now):
        tag = faction.tag
        today = datetime.fromtimestamp(now, timezone.utc)
        if today.hour < self.number("oc_inactive", tag, "hour"):
            return
        stamp = today.strftime("%Y-%m-%d")
        if self.get("oc_inactive", tag, "last_sent") == stamp:
            return
        days = self.number("oc_inactive", tag, "days")
        rows = self.repository.inactive_members(tag, now, days)
        if rows:
            channel = await self.channel(self.get("oc_inactive", tag, "channel_id"))
            lines, user_ids = self.inactive_lines(tag, rows)
            header = (
                f"**[{tag}] OC reminder** - these members have not been in an organized crime for "
                f"{days}+ days. Please join one: <{CRIMES_URL}>"
            )
            chunks, current = [], header
            for line in lines:
                if len(current) + len(line) + 1 > 1900:
                    chunks.append(current)
                    current = line
                else:
                    current += "\n" + line
            chunks.append(current)
            for chunk in chunks:
                await channel.send(
                    content=chunk,
                    allowed_mentions=discord.AllowedMentions(
                        everyone=False, roles=False, replied_user=False,
                        users=[discord.Object(id=user_id) for user_id in user_ids],
                    ),
                    suppress_embeds=True,
                )
        self.set("oc_inactive", tag, "last_sent", stamp)

    def register_commands(self):
        faction_choices = [
            app_commands.Choice(name=f"{faction.tag} - {faction.name}"[:100], value=faction.tag)
            for faction in self.settings.list_factions()[:25]
        ]

        @self.bot.tree.command(name="ti_oc_alerts", description="Configure OC payout reminders and inactivity pings")
        @app_commands.default_permissions(manage_channels=True)
        @app_commands.choices(
            faction=faction_choices,
            feature=[
                app_commands.Choice(name="Payout reminders", value="oc_payout"),
                app_commands.Choice(name="Members not in an OC", value="oc_inactive"),
            ],
            action=[
                app_commands.Choice(name=name.title(), value=name)
                for name in ("on", "off", "status", "configure", "dismiss")
            ],
        )
        @app_commands.describe(
            faction="Faction key pool to watch",
            feature="Payout reminders or members without an OC",
            action="Turn on/off, view status, configure, or dismiss a payout reminder",
            channel="Channel for these alerts",
            role="Role to mention on payout reminders",
            clear_role="Remove the payout reminder role",
            hours="Payout: remind when unpaid this many hours after completion (default 24)",
            days="Inactivity: mention members after this many days without an OC (default 3)",
            hour="Inactivity: UTC hour to post the daily reminder (default 18)",
            crime_id="Payout dismiss: crime ID that was paid manually",
        )
        async def ti_oc_alerts(
            interaction: discord.Interaction,
            faction: str,
            feature: str,
            action: str = "status",
            channel: discord.TextChannel | None = None,
            role: discord.Role | None = None,
            clear_role: bool = False,
            hours: app_commands.Range[int, 1, 168] | None = None,
            days: app_commands.Range[int, 1, 60] | None = None,
            hour: app_commands.Range[int, 0, 23] | None = None,
            crime_id: int | None = None,
        ):
            await self.configure(
                interaction, feature, faction, action, channel, role=role, clear_role=clear_role,
                hours=hours, days=days, hour=hour, crime_id=crime_id,
            )

    def status_text(self, kind, tag):
        channel_id = self.get(kind, tag, "channel_id")
        text = (
            f"[{tag}] {kind}: {'on' if self.enabled(kind, tag) else 'off'}\n"
            f"Channel: {f'<#{channel_id}>' if channel_id else 'not configured'}"
        )
        now = int(time.time())
        if kind == "oc_payout":
            hours = self.number(kind, tag, "hours")
            role_id = self.get(kind, tag, "role_id")
            text += f"\nRemind after: {hours}h (repeats every {hours}h while unpaid)"
            text += f"\nRole: {'<@&' + role_id + '>' if role_id else 'none'}"
            overdue = self.repository.overdue_payouts(tag, now, hours)
            text += f"\nCurrently overdue: {len(overdue)}"
            for row in overdue[:10]:
                text += f"\n- {row['crime_name']} #{row['crime_id']} (${int(row['money']):,})"
        else:
            days = self.number(kind, tag, "days")
            text += f"\nThreshold: {days} days\nDaily post: {self.number(kind, tag, 'hour'):02d}:00 UTC"
            rows = self.repository.inactive_members(tag, now, days)
            text += f"\nCurrently over threshold: {len(rows)}"
            for row in rows[:15]:
                text += f"\n- {row['user_name']} [{row['user_id']}]: {format_duration(row['idle_seconds'])}"
        return text[:1900]

    async def configure(
        self, interaction, kind, tag, action, channel, *,
        role=None, clear_role=False, hours=None, days=None, hour=None, crime_id=None,
    ):
        faction = self.settings.get_faction(tag)
        if faction is None or not faction.faction_id:
            await interaction.response.send_message("Choose a configured faction with a Torn faction ID.", ephemeral=True)
            return
        if interaction.guild is None or not self.can_manage(interaction):
            await interaction.response.send_message("Run this in a server with Manage Channels permission.", ephemeral=True)
            return
        if kind not in DEFAULTS or action not in ("on", "off", "status", "configure", "dismiss"):
            await interaction.response.send_message("Unknown OC alert feature or action.", ephemeral=True)
            return
        if action == "status":
            await interaction.response.send_message(
                self.status_text(kind, tag), ephemeral=True, allowed_mentions=discord.AllowedMentions.none(),
            )
            return
        if action == "dismiss":
            if kind != "oc_payout" or not crime_id:
                await interaction.response.send_message("Dismiss needs feature Payout reminders and a crime_id.", ephemeral=True)
                return
            found = self.repository.dismiss_payout(tag, crime_id)
            await interaction.response.send_message(
                f"[{tag}] Crime #{crime_id} {'will no longer be reminded' if found else 'is not being tracked'}.",
                ephemeral=True,
            )
            return
        if action == "off":
            self.set(kind, tag, "enabled", "0")
            self.wake(tag)
            await interaction.response.send_message(f"[{tag}] {kind} is off; settings are kept.", ephemeral=True)
            return
        if self.gateway is None or not faction.api_keys:
            await interaction.response.send_message(
                f"No faction API pool available. Configure FACTION_{tag}_KEYS first.", ephemeral=True,
            )
            return
        configured_channel_id = self.get(kind, tag, "channel_id")
        if channel is None and not configured_channel_id:
            await interaction.response.send_message("Choose an alert channel for this faction.", ephemeral=True)
            return
        if channel is not None and channel.guild.id != interaction.guild.id:
            await interaction.response.send_message("Choose an alert channel in this server.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        try:
            target = channel or await self.channel(int(configured_channel_id))
        except discord.HTTPException as exc:
            await interaction.followup.send(f"Could not access the alert channel: {exc}", ephemeral=True)
            return
        if target.guild.id != interaction.guild.id:
            await interaction.followup.send("The configured channel belongs to a different server.", ephemeral=True)
            return
        permissions = target.permissions_for(interaction.guild.me)
        if not (permissions.view_channel and permissions.send_messages and permissions.embed_links):
            await interaction.followup.send(
                "The bot needs View Channel, Send Messages, and Embed Links in the alert channel.", ephemeral=True,
            )
            return
        if role is not None and clear_role:
            await interaction.followup.send("Use role or clear_role, not both.", ephemeral=True)
            return
        if role is not None and kind != "oc_payout":
            await interaction.followup.send("Role mentions apply to payout reminders only.", ephemeral=True)
            return
        if role is not None and (role.guild.id != target.guild.id or role.is_default()):
            await interaction.followup.send("Choose a non-everyone role in the alert server.", ephemeral=True)
            return
        if role is not None and not (role.mentionable or permissions.mention_everyone):
            await interaction.followup.send(
                "Make the role mentionable or give the bot Mention Everyone permission to ping it.", ephemeral=True,
            )
            return
        self.set(kind, tag, "channel_id", target.id)
        if role is not None or clear_role:
            self.set(kind, tag, "role_id", role.id if role else "")
        for name, value in (("hours", hours), ("days", days), ("hour", hour)):
            if value is not None and name in DEFAULTS[kind]:
                self.set(kind, tag, name, int(value))
        if action == "on":
            self.set(kind, tag, "enabled", "1")
        self.wake(tag)
        await interaction.followup.send(
            f"Settings saved.\n{self.status_text(kind, tag)}",
            ephemeral=True, allowed_mentions=discord.AllowedMentions.none(),
        )
