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
    swap_deck_slots,
    get_deck_embed,
    deck_is_ready,
    search_owned_ball_instances,
)

import asyncio

if TYPE_CHECKING:
    from ballsdex.core.bot import BallsDexBot


@sync_to_async
def incoming_duels_enabled(discord_id: int) -> bool:
    player, _ = Player.objects.get_or_create(
        discord_id=discord_id,
    )

    settings, _ = BattleSettings.objects.get_or_create(
        player=player,
    )

    return settings.incoming_duels

@sync_to_async
def set_incoming_duels(discord_id: int, enabled: bool) -> BattleSettings:
    player, _ = Player.objects.get_or_create(
        discord_id=discord_id,
    )

    settings, _ = BattleSettings.objects.get_or_create(
        player=player,
    )

    settings.incoming_duels = enabled
    settings.save(update_fields=["incoming_duels", "updated_at"])

    return settings

@sync_to_async
def set_incoming_duels(discord_id: int, enabled: bool) -> BattleSettings:
    player, _ = Player.objects.get_or_create(
        discord_id=discord_id,
    )

    settings, _ = BattleSettings.objects.get_or_create(
        player=player,
    )

    settings.incoming_duels = enabled
    settings.save(update_fields=["incoming_duels", "updated_at"])

    return settings



class DuelConfirmation(discord.ui.View):
    def __init__(self, challenger: discord.Member, opponent: discord.Member, timeout: int=30):
        super().__init__(timeout=timeout)
        self.challenger = challenger
        self.opponent = opponent
        self.accepted = False

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.opponent.id:
            await interaction.response.send_message(
                "Only the challenged player can respond to this duel.",
                ephemeral=True,
            )
            return False

        return True

    
    

    @discord.ui.button(label="Accept", style=discord.ButtonStyle.green)
    async def accept(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):
        self.accepted = True

        for item in self.children:
            item.disabled = True

        await interaction.response.edit_message(
            content=f"{self.opponent.id} accepted the duel!",
            view=self,
        )

        self.stop()

    @discord.ui.button(label="Decline", style=discord.ButtonStyle.red)
    async def decline(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):

        self.accepted = False

        for item in self.children:
            item.disabled = True

        await interaction.response.edit_message(
            content=f"{self.opponent.id} declined the duel.",
            view=self,
        )

        self.stop()

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True

        if self.message:
            await self.message.edit(view=self)


class Battles(commands.Cog):
    def __init__(self, bot: "BallsDexBot"):
        self.bot = bot
        self.active_duels: dict[tuple[int, int], DuelState] = {}
    

    def battle_key(self, user_a: int, user_b: int) -> tuple[int, int]:
        return tuple(sorted((user_a, user_b)))

    async def get_player(self, discord_user: discord.User | discord.Member) -> Player | None:
        try:
            return await Player.objects.aget(discord_id=discord_user.id)
        except Player.DoesNotExist:
            return None

    

    async def ball_instance_autocomplete(self,interaction: discord.Interaction,current: str,) -> list[app_commands.Choice[str]]:
        results = await search_owned_ball_instances(
            interaction.user.id,
            current,
        )

        return [
            app_commands.Choice(name=name[:100], value=value)
            for name, value in results
        ]



    battle = app_commands.Group(
        name="battle",
        description="Battle commands",
    )

    deck = app_commands.Group(
        name="deck",
        description="Duel commands"
    )


    @app_commands.command(
        name = "duel",
        description = "start a battle with another user."
    )
    async def duel(self, interaction: discord.Interaction, opponent: discord.Member):
        await interaction.response.defer() 

        if opponent.bot:
            await interaction.followup.send("I am OP, you cannot duel me you weakling.")
            return

        if opponent.id == interaction.user.id:
            await interaction.followup.send("You cannot battle yourself.")
            return

        allowed = await incoming_duels_enabled(opponent.id)

        if not allowed:
            await interaction.followup.send(
                f"{opponent.name} is not accepting duel requests right now."
            )
            return

        challenger_ready, challenger_msg = await deck_is_ready(interaction.user.id)

        if not challenger_ready:
            await interaction.followup.send(
                challenger_msg,
                ephemeral=True,
            )
            return

        opponent_ready, opponent_msg = await deck_is_ready(opponent.id)

        if not opponent_ready:
            await interaction.followup.send(
                f"{opponent.name} cannot battle yet: {opponent_msg}",
                ephemeral=True,
            )
            return



        key = self.battle_key(interaction.user.id, opponent.id)

        view = DuelConfirmation(challenger=interaction.user, opponent=opponent, timeout=30)

        message = await interaction.followup.send(
            f"{opponent.mention}, {interaction.user.mention} has challenged you to a duel.\n"
            "Do you accept?", 
            view=view,
        ) 
        
        view.message = message

        await view.wait()

        if not view.accepted:
            await interaction.followup.send("Duel was cancelled.")
            return


        if key in self.active_duels:
            await interaction.followup.send("You are already in an active duel with this person.")
            return
        self.active_duels[key] = {
            "player_one": interaction.user.id,
            "player_two": opponent.id,
        }

        await interaction.followup.send(f"Key generated `{key}`")

        await asyncio.sleep(10)

        self.active_duels.pop(key, None)

        await interaction.followup.send("Key deleted")




    @battle.command(name="settings",description="Change your battle settings.",)
    @app_commands.describe(incoming_duels="Allow or block incoming duel requests.")
    async def battle_settings(
        self,
        interaction: discord.Interaction,
        incoming_duels: bool,
    ):
        await interaction.response.defer(ephemeral=True)

        settings = await set_incoming_duels(
            interaction.user.id,
            incoming_duels,
        )

        status = "enabled" if settings.incoming_duels else "disabled"

        await interaction.followup.send(
            f"Incoming duels are now **{status}**.",
            ephemeral=True,
    )




    @deck.command(name="view",description="View your battle deck.",)
    async def deck_view(self,interaction: discord.Interaction,):
        await interaction.response.defer(ephemeral=True)

        embed = await get_deck_embed(interaction.user.id)

        await interaction.followup.send(
            embed=embed,
            ephemeral=True,
        )

    @deck.command(
        name="add",
        description="Add a ball to your battle deck.",
    )
    @app_commands.describe(
        ball_instance_id="The ID of the ball instance.",
        slot_type="Active or bench.",
        position="Active: 1-6. Bench: 1-2.",
    )
    @app_commands.autocomplete(
        ball_instance_id=ball_instance_autocomplete,
    )
    @app_commands.choices(
        slot_type=[
            app_commands.Choice(name="Active", value=BattleDeckSlot.ACTIVE),
            app_commands.Choice(name="Bench", value=BattleDeckSlot.BENCH),
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

        await interaction.followup.send(
            result,
            ephemeral=True,
        )

    @deck.command(name="remove",description="Remove a ball from your battle deck.",)
    @app_commands.describe(ball_instance_id="The ID of the ball instance to remove.",)
    @app_commands.autocomplete(
        ball_instance_id=ball_instance_autocomplete,
    )
    async def deck_remove(
        self,
        interaction: discord.Interaction,
        ball_instance_id: str,
    ):
        await interaction.response.defer(ephemeral=True)

        result = await remove_ball_from_deck(
            discord_id=interaction.user.id,
            ball_instance_id=ball_instance_id,
        )

        await interaction.followup.send(
            result,
            ephemeral=True,
        )

    @deck.command(
        name="swap",
        description="Swap two slots in your battle deck.",
    )
    @app_commands.describe(
        first_slot_type="First slot type.",
        first_position="First slot position.",
        second_slot_type="Second slot type.",
        second_position="Second slot position.",
    )
    @app_commands.choices(
        first_slot_type=[
            app_commands.Choice(name="Active", value=BattleDeckSlot.ACTIVE),
            app_commands.Choice(name="Bench", value=BattleDeckSlot.BENCH),
        ],
        second_slot_type=[
            app_commands.Choice(name="Active", value=BattleDeckSlot.ACTIVE),
            app_commands.Choice(name="Bench", value=BattleDeckSlot.BENCH)
        ,]
        ,)
    async def deck_swap(self,interaction: discord.Interaction,first_slot_type: app_commands.Choice[str],first_position: int,second_slot_type: app_commands.Choice[str],second_position: int,):
        await interaction.response.defer(ephemeral=True)

        result = await swap_deck_slots(
            discord_id=interaction.user.id,
            first_slot_type=first_slot_type.value,
            first_position=first_position,
            second_slot_type=second_slot_type.value,
            second_position=second_position,
        )

        await interaction.followup.send(
            result,
            ephemeral=True,
        )
