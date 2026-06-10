from django.db import models
from bd_models.models import Player

class BattleSettings(models.Model):
    player = models.OneToOneField(
        Player,
        on_delete=models.CASCADE,
        related_name="battle_settings",

    )

    incoming_duels = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)

    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Battle settings for {self.player}"
