from django.db import models
from bd_models.models import Player, BallInstance

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


class BattleDeck(models.Model):
    player = models.OneToOneField(
        Player,
        on_delete=models.CASCADE,
        related_name="battle_decks",
    )

    name = models.CharField(
        max_length=32,
        default="Default Deck",
    )

    selected = models.BooleanField(default=True)

    created_at = models.DateTimeField(
        auto_now_add=True,
    )

    updated_at = models.DateTimeField(
        auto_now=True,
    )

    class Meta:
        unique_together = (
            ("player", "name"),
        )

    def __str__(self):
        return f"{self.player} - {self.name}"

class BattleDeckSlot(models.Model):
    ACTIVE = "active"
    BENCH = "bench"

    SLOT_TYPE_CHOICES = (
        (ACTIVE, "Active"),
        (BENCH, "Bench"),
    )

    deck = models.ForeignKey(
        BattleDeck,
        on_delete=models.CASCADE,
        related_name="slots",
    )

    ball_instance = models.ForeignKey(
        BallInstance,
        on_delete=models.CASCADE,
        related_name="battle_deck_slots",
    )

    slot_type = models.CharField(
        max_length=16,
        choices=SLOT_TYPE_CHOICES,
    )

    position = models.PositiveSmallIntegerField()

    created_at = models.DateTimeField(
        auto_now_add=True,
    )

    class Meta:
        unique_together = (
            ("deck", "slot_type", "position"),
            ("deck", "ball_instance"),
        )

    def __str__(self):
        return f"{self.deck} | {self.slot_type} {self.position}"
