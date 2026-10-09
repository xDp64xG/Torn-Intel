"""Discord controls and delivery for per-faction retal and chain-saving watchers."""

from __future__ import annotations

import asyncio
import logging
import time

import discord
from discord import app_commands

from repositories.faction_watch_repository import FactionWatchRepository
from services.faction_watchers import ChainWatchConfig, RetalTracker, evaluate_chain


class DiscordFactionWatchers:
    def __init__(self, bot, settings, gateway, store, can_manage, logger=None):
        self.bot = bot
        self.settings = settings
        self.gateway = gateway
        self.store = store
        self.can_manage = can_manage
        self.logger = logger or logging.getLogger(__name__)
        self.repository = FactionWatchRepository(settings.database_path)
        self.retal_tracker = RetalTracker(gateway, self.repository)
        self.tasks = {}
        self.wakeups = {}
        self.register_commands()

    @staticmethod
    def key(kind, tag, name):
        return f"{kind}_{tag}_{name}"

    def get(self, kind, tag, name, default=None):
        value = self.store.get_setting(self.key(kind, tag, name))
        return value if value is not None else default

    def set(self, kind, tag, name, value):
        self.store.set_setting(self.key(kind, tag, name), str(value))

    def chain_config(self, tag):
        return ChainWatchConfig(**{
            name: int(self.get("chain_saver", tag, name, default))
            for name, default in (("minimum", 10), ("warning", 120), ("urgent", 60), ("final", 30))
        })

    def wake(self, kind, tag):
        event = self.wakeups.get((kind, tag))
        if event is not None:
            event.set()

    def start(self):
        for faction in self.settings.list_factions():
            for kind in ("retal", "chain_saver"):
                key = kind, faction.tag
                task = self.tasks.get(key)
                if task is None or task.done():
                    if task is not None and not task.cancelled() and task.exception():
                        self.logger.error(f"[{faction.tag}] {kind} task stopped: {task.exception()}")
                    self.wakeups[key] = asyncio.Event()
                    self.tasks[key] = asyncio.create_task(self.run_faction(kind, faction))

    async def run_faction(self, kind, faction):
        event = self.wakeups[kind, faction.tag]
        while not self.bot.is_closed():
            event.clear()
            started_at = time.monotonic()
            delay = 30 if kind == "retal" else 240
            try:
                if self.get(kind, faction.tag, "enabled") == "1":
                    if kind == "retal":
                        await self.poll_retals(faction)
                        delay = max(1, 30 - (time.monotonic() - started_at))
                    else:
                        delay = await self.poll_chain(faction)
            except Exception as exc:
                self.logger.warning(f"[{faction.tag}] {kind} watcher failed: {type(exc).__name__}: {exc}")
                delay = 30
            if self.bot.is_closed():
                break
            try:
                await asyncio.wait_for(event.wait(), timeout=delay)
            except asyncio.TimeoutError:
                pass

    async def channel(self, channel_id):
        channel = self.bot.get_channel(int(channel_id))
        if channel is None:
            channel = await self.bot.fetch_channel(int(channel_id))
        return channel

    @staticmethod
    def retal_embed(tag, row):
        colors = {"pending": 0xf1c40f, "fulfilled": 0x2ecc71, "missed": 0xe74c3c}
        embed = discord.Embed(
            title=f"[{tag}] Retal {row['status'].title()}",
            color=colors[row["status"]],
        )
        target = discord.utils.escape_markdown(row["attacker_name"])
        faction_name = discord.utils.escape_markdown(row["attacker_faction"])
        defender_name = discord.utils.escape_markdown(row["defender_name"])
        embed.description = (
            f"[{target} ({row['attacker_id']})]"
            f"(https://www.torn.com/profiles.php?XID={row['attacker_id']})\n"
            f"Faction: {faction_name}\n"
            f"Attacked: {defender_name}\n"
            f"Result: {row['result']}\n"
            f"Retal deadline: <t:{row['expires_at']}:R>"
        )
        if row["fulfilled_by"]:
            fulfilled_by = discord.utils.escape_markdown(row["fulfilled_by"])
            fulfilled_by_id = row.get("fulfilled_by_id")
            if fulfilled_by_id:
                fulfilled_by = (
                    f"[{fulfilled_by} ({fulfilled_by_id})]"
                    f"(https://www.torn.com/profiles.php?XID={fulfilled_by_id})"
                )
            embed.add_field(name="Retal bonus taken by", value=fulfilled_by, inline=False)
        embed.set_footer(text=f"Attack {row['attack_id']} | Five-minute retal window")
        return embed

    @staticmethod
    def retal_links(row):
        """(label, url) pairs for the quick-action buttons on an open retal."""
        attacker_id = int(row["attacker_id"])
        links = [
            ("Retal", f"https://www.torn.com/loader.php?sid=attack&user2ID={attacker_id}"),
        ]
        if row.get("attack_code"):
            links.append(("Attack log", f"https://www.torn.com/loader.php?sid=attackLog&ID={row['attack_code']}"))
        links.append(("Profile", f"https://www.torn.com/profiles.php?XID={attacker_id}"))
        faction_id = int(row.get("attacker_faction_id") or 0)
        if faction_id > 0:
            links.append(("Faction", f"https://www.torn.com/factions.php?step=profile&ID={faction_id}"))
        return links

    def retal_view(self, row):
        if row["status"] != "pending":
            return None
        view = discord.ui.View(timeout=None)
        for label, url in self.retal_links(row):
            view.add_item(discord.ui.Button(label=label, url=url, style=discord.ButtonStyle.link))
        return view

    def configured_role(self, kind, tag, guild):
        role_id = self.get(kind, tag, "role_id")
        if not role_id:
            return None
        role = guild.get_role(int(role_id)) if guild is not None else None
        if role is None:
            raise ValueError(f"Configured {kind} role {role_id} is missing from the alert server.")
        return role

    async def poll_retals(self, faction):
        tag = faction.tag
        activated_at = int(self.get("retal", tag, "activated_at"))
        now = int(time.time())
        since = int(self.get("retal", tag, "cursor", activated_at))
        await asyncio.to_thread(
            self.retal_tracker.check, faction, self.get("retal", tag, "mode", "all"),
            since, now, activated_at,
        )
        if (
            self.get("retal", tag, "enabled") == "0"
            or int(self.get("retal", tag, "activated_at")) != activated_at
        ):
            return
        self.set("retal", tag, "cursor", now)
        for row in self.repository.notifications(tag):
            try:
                channel_id = row["channel_id"] or int(self.get("retal", tag, "channel_id"))
                channel = await self.channel(channel_id)
                embed = self.retal_embed(tag, row)
                view = self.retal_view(row)
                message = None
                if row["message_id"]:
                    try:
                        message = await channel.fetch_message(row["message_id"])
                    except discord.NotFound:
                        self.logger.warning(f"[{tag}] Retal message {row['message_id']} was deleted; reposting.")
                if message is not None:
                    await message.edit(embed=embed, view=view, allowed_mentions=discord.AllowedMentions.none())
                else:
                    role = None
                    if row["status"] == "pending":
                        try:
                            role = self.configured_role("retal", tag, getattr(channel, "guild", None))
                        except ValueError as exc:
                            self.logger.warning(f"[{tag}] {exc} Posting the retal without a mention.")
                    send_kwargs = {
                        "content": role.mention if role else None,
                        "embed": embed,
                        "allowed_mentions": discord.AllowedMentions(
                            everyone=False, users=False, roles=[role], replied_user=False,
                        ) if role else discord.AllowedMentions.none(),
                    }
                    if view is not None:
                        send_kwargs["view"] = view
                    message = await channel.send(**send_kwargs)
                self.repository.mark_posted(tag, row["attack_id"], channel.id, message.id, row["status"])
            except Exception as exc:
                self.logger.warning(f"[{tag}] Retal delivery failed for {row['attack_id']}: {type(exc).__name__}: {exc}")

    async def poll_chain(self, faction):
        tag = faction.tag
        config = self.chain_config(tag)
        channel_id = self.get("chain_saver", tag, "channel_id")
        payload = await asyncio.to_thread(self.gateway.faction_chain, pool=tag)
        if (
            self.get("chain_saver", tag, "enabled") == "0"
            or config != self.chain_config(tag)
            or channel_id != self.get("chain_saver", tag, "channel_id")
        ):
            return 1
        stage, state, delay = evaluate_chain(
            payload, config, self.repository.chain_state(tag), time.time(),
        )
        if stage is not None:
            channel = await self.channel(int(channel_id))
            chain = payload["chain"]
            labels = {1: "Warning", 2: "Urgent", 3: "Final warning"}
            embed = discord.Embed(
                title=f"[{tag}] Chain Saver - {labels[stage]}",
                description=(
                    f"Chain: **{int(chain['current']):,} hits**\n"
                    f"Time remaining: **{int(chain['timeout'])} seconds**\n"
                    f"[Open faction](https://www.torn.com/factions.php?step=profile&ID={faction.faction_id})"
                ),
                color=0xe74c3c if stage == 3 else 0xf1c40f,
            )
            role_id = self.get("chain_saver", tag, "role_id")
            role = channel.guild.get_role(int(role_id)) if role_id else None
            if role_id and role is None:
                raise ValueError(f"Configured chain-saving role {role_id} is missing from the alert server.")
            await channel.send(
                content=role.mention if role else None,
                embed=embed,
                allowed_mentions=discord.AllowedMentions(
                    everyone=False, users=False, roles=[role], replied_user=False,
                ) if role else discord.AllowedMentions.none(),
            )
        self.repository.save_chain_state(tag, state)
        return delay

    def register_commands(self):
        faction_choices = [
            app_commands.Choice(name=f"{faction.tag} - {faction.name}"[:100], value=faction.tag)
            for faction in self.settings.list_factions()[:25]
        ]
        action_choices = [
            app_commands.Choice(name=name.title(), value=name)
            for name in ("on", "off", "status", "configure")
        ]

        @self.bot.tree.command(name="ti_retal", description="Configure per-faction retaliation alerts")
        @app_commands.default_permissions(manage_channels=True)
        @app_commands.choices(
            faction=faction_choices,
            action=action_choices,
            mode=[
                app_commands.Choice(name="All retals", value="all"),
                app_commands.Choice(name="Ranked-war retals only", value="war"),
            ],
        )
        @app_commands.describe(
            faction="Faction key pool to watch",
            action="Turn on/off, view status, or configure settings",
            channel="Channel for new retal alerts",
            mode="All incoming attacks or only ranked-war attacks",
            role="Role to mention when a new retal is available",
            clear_role="Remove the configured retal role mention",
        )
        async def ti_retal(
            interaction: discord.Interaction,
            faction: str,
            action: str = "status",
            channel: discord.TextChannel | None = None,
            mode: str | None = None,
            role: discord.Role | None = None,
            clear_role: bool = False,
        ):
            await self.configure(
                interaction, "retal", faction, action, channel,
                mode=mode, role=role, clear_role=clear_role,
            )

        @self.bot.tree.command(name="ti_chain_saver", description="Configure per-faction chain-saving warnings")
        @app_commands.default_permissions(manage_channels=True)
        @app_commands.choices(faction=faction_choices, action=action_choices)
        @app_commands.describe(
            faction="Faction key pool to watch",
            action="Turn on/off, view status, or configure settings",
            channel="Channel for chain-saving alerts",
            role="Role to mention on each warning",
            clear_role="Remove the configured role mention",
            minimum="Minimum chain size to watch (default 10)",
            warning="First warning below this many seconds (default 120)",
            urgent="Second warning below this many seconds (default 60)",
            final="Final warning below this many seconds (default 30)",
        )
        async def ti_chain_saver(
            interaction: discord.Interaction,
            faction: str,
            action: str = "status",
            channel: discord.TextChannel | None = None,
            role: discord.Role | None = None,
            clear_role: bool = False,
            minimum: int | None = None,
            warning: int | None = None,
            urgent: int | None = None,
            final: int | None = None,
        ):
            await self.configure(
                interaction, "chain_saver", faction, action, channel,
                role=role, clear_role=clear_role, minimum=minimum,
                warning=warning, urgent=urgent, final=final,
            )

    async def configure(
        self, interaction, kind, tag, action, channel, *,
        mode=None, role=None, clear_role=False, **thresholds,
    ):
        faction = self.settings.get_faction(tag)
        if faction is None or not faction.faction_id:
            await interaction.response.send_message("Choose a configured faction with a Torn faction ID.", ephemeral=True)
            return
        if interaction.guild is None or not self.can_manage(interaction):
            await interaction.response.send_message("Run this in a server with Manage Channels permission.", ephemeral=True)
            return
        if action not in ("on", "off", "status", "configure"):
            await interaction.response.send_message("Unknown watcher action.", ephemeral=True)
            return
        if action == "status":
            channel_id = self.get(kind, tag, "channel_id")
            enabled = self.get(kind, tag, "enabled") == "1"
            text = f"[{tag}] {kind}: {'on' if enabled else 'off'}\nChannel: "
            text += f"<#{channel_id}>" if channel_id else "not configured"
            role_id = self.get(kind, tag, "role_id")
            if kind == "retal":
                text += f"\nMode: {self.get(kind, tag, 'mode', 'all')}\nPoll: 30s; window: 5 minutes"
            else:
                config = self.chain_config(tag)
                text += (
                    f"\nMinimum: {config.minimum} hits\nWarnings: {config.warning}/{config.urgent}/{config.final}s"
                )
            text += f"\nRole: {'<@&' + role_id + '>' if role_id else 'none'}"
            await interaction.response.send_message(
                text, ephemeral=True, allowed_mentions=discord.AllowedMentions.none(),
            )
            return
        if action == "off":
            self.set(kind, tag, "enabled", "0")
            self.wake(kind, tag)
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
        if mode is not None and mode not in ("all", "war"):
            await interaction.followup.send("Choose mode all or war.", ephemeral=True)
            return
        if role is not None and clear_role:
            await interaction.followup.send("Use role or clear_role, not both.", ephemeral=True)
            return
        if role is not None and (role.guild.id != target.guild.id or role.is_default()):
            await interaction.followup.send("Choose a non-everyone role in the alert server.", ephemeral=True)
            return
        if role is not None and not (role.mentionable or permissions.mention_everyone):
            await interaction.followup.send(
                "Make the role mentionable or give the bot Mention Everyone permission to ping it.", ephemeral=True,
            )
            return
        if kind == "chain_saver":
            current = self.chain_config(tag)
            try:
                config = ChainWatchConfig(**{
                    name: thresholds[name] if thresholds.get(name) is not None else getattr(current, name)
                    for name in ("minimum", "warning", "urgent", "final")
                })
            except ValueError as exc:
                await interaction.followup.send(str(exc), ephemeral=True)
                return
            changed = config != current
            for name in ("minimum", "warning", "urgent", "final"):
                self.set(kind, tag, name, getattr(config, name))
            if changed:
                self.repository.save_chain_state(tag, {})
        self.set(kind, tag, "channel_id", target.id)
        if mode is not None:
            self.set(kind, tag, "mode", mode)
        if role is not None or clear_role:
            self.set(kind, tag, "role_id", role.id if role else "")
        if action == "on":
            if kind == "retal" and self.get(kind, tag, "enabled") != "1":
                now = int(time.time())
                self.set(kind, tag, "activated_at", now)
                self.set(kind, tag, "cursor", now)
            self.set(kind, tag, "enabled", "1")
        self.wake(kind, tag)
        enabled = self.get(kind, tag, "enabled") == "1"
        await interaction.followup.send(
            f"[{tag}] {kind} settings saved; {'on' if enabled else 'off'}. Alerts go to {target.mention}.",
            ephemeral=True, allowed_mentions=discord.AllowedMentions.none(),
        )
