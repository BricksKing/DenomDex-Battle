from django.contrib import admin
from .models import BattleSettings, BattleDeck, BattleDeckSlot

@admin.register(BattleSettings)
class BattleSettingsAdmin(admin.ModelAdmin):
    list_display = (
        "player",
        "incoming_duels",
        "created_at",
        "updated_at",
    )

    list_filter = (
        "incoming_duels",
        "created_at",
        "updated_at",
    )

    search_fields = (
        "player__discord_id",
        "player__discord_name",
    )

    readonly_fields = (
        "created_at",
        "updated_at",
    )

    ordering = (
        "-updated_at",
    )

class BattleDeckSlotInline(admin.TabularInline):
    model = BattleDeckSlot
    extra = 0


@admin.register(BattleDeck)
class BattleDeckAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "player",
        "name",
        "selected",
        "created_at",
        "updated_at",
    )

    list_filter = (
        "selected",
        "created_at",
        "updated_at",
    )

    search_fields = (
        "player__discord_id",
        "player__discord_name",
        "name",
    )

    inlines = (
        BattleDeckSlotInline,
    )


@admin.register(BattleDeckSlot)
class BattleDeckSlotAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "deck",
        "ball_instance",
        "slot_type",
        "position",
        "created_at",
    )

    list_filter = (
        "slot_type",
        "created_at",
    )

    search_fields = (
        "deck__player__discord_id",
        "deck__player__discord_name",
        "deck__name",
    )
