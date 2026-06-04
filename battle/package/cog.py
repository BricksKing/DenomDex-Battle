from typing import TYPE_CHECKING

import discord

from discord import app_commands
from discord.ext import commands


from bd_models.models import BallInstance, Player

import asyncio

if TYPE_CHECKING:
    from ballsdex.core.bot import BallsDexBot


class BattlesCog(commands.Cog):
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
    async def duel(self, interaction: discord.Interaction, opp: discord.Member):
        await interaction.response.defer() 

        if opp.bot:
            await interaction.followup.send("I am OP, you cannot duel me you weakling.")
            return

        if opp.id == interaction.user.id:
            await interaction.followup.send("You cannot battle yourself.")
            return

        key = self.battle_key(interaction.user.id, opp.id)

        self.active_duels[key] = {
            "player_one": interaction.user.id,
            "player_two": opp.id,
        }

        await interaction.followup.send(f"Key generated `{key}`")

        await asyncio.sleep(10)

        self.active_duels.pop(key, None)

        await interaction.followup.send("Key deleted")
