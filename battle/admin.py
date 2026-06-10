from django.contrib import admin
from .models import BattleSettings

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
