from typing import TYPE_CHECKING

import discord

from discord import app_commands
from discord.ext import commands

from asgiref.sync import sync_to_async

from bd_models.models import BallInstance, Player
from ..models import BattleSettings, BattleDeck, BattleDeckSlot

from .deck import (
    add_ball_to_deck,
    remove_ball_from_deck,
    get_deck_embed,
    deck_is_ready,
    search_owned_ball_instances,
    get_battle_lineup,
)
from .battle import BattleBall, BattleError, BattleSession, BattleTeam

if TYPE_CHECKING:
    from ballsdex.core.bot import BallsDexBot


@sync_to_async
def incoming_duels_enabled(discord_id: int) -> bool:
    player, _ = Player.objects.get_or_create(discord_id=discord_id)

    settings, _ = BattleSettings.objects.get_or_create(player=player)

    return settings.incoming_duels


@sync_to_async
def set_incoming_duels(discord_id: int, enabled: bool) -> BattleSettings:
    player, _ = Player.objects.get_or_create(discord_id=discord_id)

    settings, _ = BattleSettings.objects.get_or_create(player=player)

    settings.incoming_duels = enabled
    settings.save(update_fields=["incoming_duels", "updated_at"])

    return settings


class DuelConfirmation(discord.ui.View):
    def __init__(self, challenger: discord.Member, opponent: discord.Member, timeout: int = 30):
        super().__init__(timeout=timeout)
        self.challenger = challenger
        self.opponent = opponent
        self.accepted = False

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.opponent.id:
            await interaction.response.send_message(
                "Only the challenged player can respond to this duel.", ephemeral=True
            )
            return False

        return True

    @discord.ui.button(label="Accept", style=discord.ButtonStyle.green)
    async def accept(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.accepted = True

        for item in self.children:
            item.disabled = True

        await interaction.response.edit_message(content=f"{self.opponent.id} accepted the duel!", view=self)

        self.stop()

    @discord.ui.button(label="Decline", style=discord.ButtonStyle.red)
    async def decline(self, interaction: discord.Interaction, button: discord.ui.Button):

        self.accepted = False

        for item in self.children:
            item.disabled = True

        await interaction.response.edit_message(content=f"{self.opponent.id} declined the duel.", view=self)

        self.stop()

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True

        if self.message:
            await self.message.edit(view=self)


class DeckReplaceConfirmation(discord.ui.View):
    def __init__(self, user_id: int, timeout: int = 30):
        super().__init__(timeout=timeout)

        self.user_id = user_id
        self.confirmed = False
        self.message: discord.Message | None = None

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message(
                "Only the player editing this deck can use these buttons.", ephemeral=True
            )
            return False

        return True

    @discord.ui.button(label="Confirm", style=discord.ButtonStyle.green)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.confirmed = True

        for item in self.children:
            item.disabled = True

        await interaction.response.edit_message(view=self)

        self.stop()

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.red)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.confirmed = False

        for item in self.children:
            item.disabled = True

        await interaction.response.edit_message(view=self)

        self.stop()

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True

        if self.message:
            await self.message.edit(view=self)


class AttackSelect(discord.ui.Select):
    def __init__(self, battle_view: "BattleView"):
        self.battle_view = battle_view
        session = battle_view.session
        team = session.team_for(session.current_player_id)
        opponent = session.opponent_of(session.current_player_id)
        options = []

        for attacker_slot, attacker_index in enumerate(team.active):
            attacker = team.balls[attacker_index]
            if not attacker.is_alive:
                continue
            for target_slot, target_index in enumerate(opponent.active):
                target = opponent.balls[target_index]
                if target.is_alive:
                    options.append(
                        discord.SelectOption(
                            label=f"{attacker.name} -> {target.name}"[:100],
                            value=f"{attacker_slot}:{target_slot}",
                        )
                    )

        super().__init__(
            placeholder="Attack with an active ball",
            options=options or [discord.SelectOption(label="No valid attack", value="none")],
            disabled=not options,
            row=0,
        )

    async def callback(self, interaction: discord.Interaction):
        if self.values[0] == "none":
            return
        attacker_slot, target_slot = map(int, self.values[0].split(":"))
        await self.battle_view.perform_action(
            interaction,
            lambda: self.battle_view.session.attack(
                interaction.user.id, attacker_slot, target_slot
            ),
        )


class SwapSelect(discord.ui.Select):
    def __init__(self, battle_view: "BattleView"):
        self.battle_view = battle_view
        session = battle_view.session
        team = session.team_for(session.current_player_id)
        options = []

        for active_slot, active_index in enumerate(team.active):
            outgoing = team.balls[active_index]
            for reserve_slot, reserve_index in enumerate(team.reserve):
                incoming = team.balls[reserve_index]
                if incoming.is_alive:
                    options.append(
                        discord.SelectOption(
                            label=f"{outgoing.name} -> {incoming.name}"[:100],
                            value=f"{active_slot}:{reserve_slot}",
                        )
                    )

        super().__init__(
            placeholder="Swap an active ball with a reserve",
            options=options or [discord.SelectOption(label="No valid swap", value="none")],
            disabled=not options,
            row=1,
        )

    async def callback(self, interaction: discord.Interaction):
        if self.values[0] == "none":
            return
        active_slot, reserve_slot = map(int, self.values[0].split(":"))
        await self.battle_view.perform_action(
            interaction,
            lambda: self.battle_view.session.swap(
                interaction.user.id, active_slot, reserve_slot
            ),
        )


class SurrenderButton(discord.ui.Button):
    def __init__(self, battle_view: "BattleView"):
        super().__init__(label="Surrender", style=discord.ButtonStyle.danger, row=2)
        self.battle_view = battle_view

    async def callback(self, interaction: discord.Interaction):
        try:
            self.battle_view.session.surrender(interaction.user.id)
        except BattleError as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)
            return

        await self.battle_view.finish(interaction)


class BattleView(discord.ui.View):
    def __init__(self, session: BattleSession, members: dict[int, discord.Member], on_finish):
        super().__init__(timeout=300)
        self.session = session
        self.members = members
        self.on_finish = on_finish
        self.message: discord.Message | None = None
        self.expired = False
        self.refresh_components()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id not in self.session.teams:
            await interaction.response.send_message(
                "Only the two players in this duel can use these controls.", ephemeral=True
            )
            return False
        return True

    def refresh_components(self) -> None:
        self.clear_items()
        if not self.session.is_finished:
            self.add_item(AttackSelect(self))
            self.add_item(SwapSelect(self))
            self.add_item(SurrenderButton(self))

    def make_embed(self) -> discord.Embed:
        if self.expired:
            title = "Battle expired"
        elif self.session.is_finished:
            title = f"Winner: {self.members[self.session.winner_id].display_name}"
        else:
            current = self.members[self.session.current_player_id]
            title = f"Battle — {current.display_name}'s turn"

        embed = discord.Embed(title=title, description=self.session.log)
        for user_id in self.session.turn_order:
            team = self.session.team_for(user_id)
            active_lines = []
            reserve_lines = []

            for position, ball_index in enumerate(team.active, start=1):
                ball = team.balls[ball_index]
                active_lines.append(
                    f"`A{position}` **{ball.name}** — "
                    f"{ball.hp}/{ball.max_hp} HP • {ball.attack_power} ATK"
                )
            for position, ball_index in enumerate(team.reserve, start=1):
                ball = team.balls[ball_index]
                reserve_lines.append(
                    f"`R{position}` {ball.name} — "
                    f"{ball.hp}/{ball.max_hp} HP • {ball.attack_power} ATK"
                )

            embed.add_field(
                name=self.members[user_id].display_name,
                value="**Active**\n" + "\n".join(active_lines)
                + "\n**Reserve**\n" + "\n".join(reserve_lines),
                inline=True,
            )
        return embed

    async def perform_action(self, interaction: discord.Interaction, action) -> None:
        try:
            action()
        except BattleError as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)
            return

        if self.session.is_finished:
            await self.finish(interaction)
            return

        self.refresh_components()
        await interaction.response.edit_message(embed=self.make_embed(), view=self)

    async def finish(self, interaction: discord.Interaction) -> None:
        self.refresh_components()
        await interaction.response.edit_message(embed=self.make_embed(), view=self)
        await self.on_finish()
        self.stop()

    async def on_timeout(self) -> None:
        if not self.session.is_finished:
            self.expired = True
            self.session.log = "The duel expired after 5 minutes of inactivity."
        self.clear_items()
        if self.message:
            await self.message.edit(embed=self.make_embed(), view=self)
        await self.on_finish()


class Battles(commands.Cog):
    def __init__(self, bot: "BallsDexBot"):
        self.bot = bot
        self.active_duels: dict[tuple[int, int], BattleSession] = {}

    def battle_key(self, user_a: int, user_b: int) -> tuple[int, int]:
        return tuple(sorted((user_a, user_b)))

    def player_is_battling(self, user_id: int) -> bool:
        return any(user_id in key for key in self.active_duels)

    async def get_player(self, discord_user: discord.User | discord.Member) -> Player | None:
        try:
            return await Player.objects.aget(discord_id=discord_user.id)
        except Player.DoesNotExist:
            return None

    async def ball_instance_autocomplete(
        self, interaction: discord.Interaction, current: str
    ) -> list[app_commands.Choice[str]]:
        results = await search_owned_ball_instances(interaction.user.id, current)

        return [app_commands.Choice(name=name[:100], value=value) for name, value in results]

    battle = app_commands.Group(name="battle", description="Battle commands")

    deck = app_commands.Group(name="deck", description="Duel commands")

    @app_commands.command(name="duel", description="start a battle with another user.")
    async def duel(self, interaction: discord.Interaction, opponent: discord.Member):
        await interaction.response.defer()

        if opponent.bot:
            await interaction.followup.send("I am OP, you cannot duel me you weakling.")
            return

        if opponent.id == interaction.user.id:
            await interaction.followup.send("You cannot battle yourself.")
            return

        if self.player_is_battling(interaction.user.id) or self.player_is_battling(opponent.id):
            await interaction.followup.send("One of you is already in an active duel.")
            return

        allowed = await incoming_duels_enabled(opponent.id)

        if not allowed:
            await interaction.followup.send(f"{opponent.name} is not accepting duel requests right now.")
            return

        challenger_ready, challenger_msg = await deck_is_ready(interaction.user.id)

        if not challenger_ready:
            await interaction.followup.send(challenger_msg, ephemeral=True)
            return

        opponent_ready, opponent_msg = await deck_is_ready(opponent.id)

        if not opponent_ready:
            await interaction.followup.send(f"{opponent.name} cannot battle yet: {opponent_msg}", ephemeral=True)
            return

        key = self.battle_key(interaction.user.id, opponent.id)

        view = DuelConfirmation(challenger=interaction.user, opponent=opponent, timeout=30)

        message = await interaction.followup.send(
            f"{opponent.mention}, {interaction.user.mention} has challenged you to a duel.\nDo you accept?", view=view
        )

        view.message = message

        await view.wait()

        if not view.accepted:
            await interaction.followup.send("Duel was cancelled.")
            return

        if self.player_is_battling(interaction.user.id) or self.player_is_battling(opponent.id):
            await interaction.followup.send("One of you entered another duel while this request was open.")
            return

        challenger_lineup = await get_battle_lineup(interaction.user.id)
        opponent_lineup = await get_battle_lineup(opponent.id)
        if len(challenger_lineup) != 6 or len(opponent_lineup) != 6:
            await interaction.followup.send(
                "Could not load both battle decks. Each player needs 2 active balls "
                "and 4 reserves that they still own and that are not deleted. "
                "Check /battle deck view."
            )
            return

        def make_team(user_id: int, lineup: list[dict]) -> BattleTeam:
            return BattleTeam(
                user_id=user_id,
                balls=[
                    BattleBall(
                        instance_id=item["instance_id"],
                        name=item["name"],
                        max_hp=item["health"],
                        attack_power=item["attack"],
                    )
                    for item in lineup
                ],
            )

        session = BattleSession(
            make_team(interaction.user.id, challenger_lineup),
            make_team(opponent.id, opponent_lineup),
        )
        self.active_duels[key] = session

        async def remove_duel():
            if self.active_duels.get(key) is session:
                self.active_duels.pop(key, None)

        battle_view = BattleView(
            session=session,
            members={interaction.user.id: interaction.user, opponent.id: opponent},
            on_finish=remove_duel,
        )
        battle_message = await interaction.followup.send(
            embed=battle_view.make_embed(), view=battle_view
        )
        battle_view.message = battle_message

    @battle.command(name="settings", description="Change your battle settings.")
    @app_commands.describe(incoming_duels="Allow or block incoming duel requests.")
    async def battle_settings(self, interaction: discord.Interaction, incoming_duels: bool):
        await interaction.response.defer(ephemeral=True)

        settings = await set_incoming_duels(interaction.user.id, incoming_duels)

        status = "enabled" if settings.incoming_duels else "disabled"

        await interaction.followup.send(f"Incoming duels are now **{status}**.", ephemeral=True)

    @deck.command(name="view", description="View your battle deck.")
    async def deck_view(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        embed = await get_deck_embed(interaction.user.id)

        await interaction.followup.send(embed=embed, ephemeral=True)

    @deck.command(name="add", description="Add a ball to your battle deck.")
    @app_commands.describe(
        ball_instance_id="Search your owned ball instance.",
        slot_type="Active or reserve.",
        position="Active: 1-2. Reserve: 1-4.",
    )
    @app_commands.autocomplete(ball_instance_id=ball_instance_autocomplete)
    @app_commands.choices(
        slot_type=[
            app_commands.Choice(name="Active", value=BattleDeckSlot.ACTIVE),
            app_commands.Choice(name="Reserve", value=BattleDeckSlot.BENCH),
        ]
    )
    async def deck_add(
        self,
        interaction: discord.Interaction,
        ball_instance_id: str,
        slot_type: app_commands.Choice[str],
        position: int,
    ):
        await interaction.response.defer(ephemeral=True)

        result = await add_ball_to_deck(
            discord_id=interaction.user.id,
            ball_instance_id=ball_instance_id,
            slot_type=slot_type.value,
            position=position,
        )

        # Normal error
        if result["status"] == "error":
            await interaction.followup.send(result["message"], ephemeral=True)
            return

        # Empty slot, so it was added immediately
        if result["status"] in ("added", "moved"):
            await interaction.followup.send(result["message"], ephemeral=True)
            return

        # Slot already has a ball
        if result["status"] == "occupied":
            view = DeckReplaceConfirmation(user_id=interaction.user.id, timeout=30)

            message = await interaction.followup.send(
                (
                    f"**{slot_type.name} slot {position}** already contains "
                    f"**{result['old_name']}** `#{result['old_id']}`.\n\n"
                    f"Replace it with "
                    f"**{result['new_name']}** `#{result['new_id']}`?"
                ),
                view=view,
                ephemeral=True,
            )

            view.message = message

            await view.wait()

            if not view.confirmed:
                return

            # Now actually replace the existing ball
            result = await add_ball_to_deck(
                discord_id=interaction.user.id,
                ball_instance_id=ball_instance_id,
                slot_type=slot_type.value,
                position=position,
                replace=True,
            )

            await interaction.followup.send(result["message"], ephemeral=True)

    @deck.command(name="remove", description="Remove a ball from your battle deck.")
    @app_commands.describe(ball_instance_id="The ID of the ball instance to remove.")
    @app_commands.autocomplete(ball_instance_id=ball_instance_autocomplete)
    async def deck_remove(self, interaction: discord.Interaction, ball_instance_id: str):
        await interaction.response.defer(ephemeral=True)

        result = await remove_ball_from_deck(discord_id=interaction.user.id, ball_instance_id=ball_instance_id)

        await interaction.followup.send(result, ephemeral=True)
