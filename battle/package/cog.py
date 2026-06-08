from typing import TYPE_CHECKING

import discord

from discord import app_commands
from discord.ext import commands


from bd_models.models import BallInstance, Player

import asyncio

if TYPE_CHECKING:
    from ballsdex.core.bot import BallsDexBot

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
            content=f"{self.opponent.mention} accepted the duel!",
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
            content=f"{self.opponent.mention} declined the duel.",
            view=self,
        )

        self.stop()

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True


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

        key = self.battle_key(interaction.user.id, opponent.id)

        view = DuelConfirmation(challenger=interaction.user, opponent=opponent, timeout=30)

        message = await interaction.followup.send(
            f"{opponent.mention}, {interaction.user.mention} has challenged you to a duel.\n"
            "Do you accept?", 
            view=view,
        ) 
        
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
