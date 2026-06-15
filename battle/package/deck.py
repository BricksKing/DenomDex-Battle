import discord

from asgiref.sync import sync_to_async
from django.db import transaction

from bd_models.models import BallInstance, Player
from ..models import BattleDeck, BattleDeckSlot


DECK_NAME = "Default Deck"


def get_ball_name(ball_instance: BallInstance) -> str:
    ball = ball_instance.ball

    return (
        getattr(ball, "country", None)
        or getattr(ball, "name", None)
        or str(ball)
    )



@sync_to_async
def search_owned_ball_instances(discord_id: int, query: str) -> list[tuple[str, int]]:
    player = Player.objects.filter(discord_id=discord_id).first()

    if not player:
        return []

    qs = (
        BallInstance.objects.filter(player=player)
        .select_related("ball")
        .order_by("id")
    )

    if query:
        qs = qs.filter(ball__country__icontains=query)

    results = []

    for instance in qs[:25]:
        ball = instance.ball
        ball_name = (
            getattr(ball, "country", None)
            or getattr(ball, "name", None)
            or str(ball)
        )

        results.append(
            (
                f"{ball_name} #{instance.id}",
                instance.id,
            )
        )

    return results


@sync_to_async
def get_or_create_deck(discord_id: int) -> BattleDeck:
    player, _ = Player.objects.get_or_create(
        discord_id=discord_id,
    )

    deck, _ = BattleDeck.objects.get_or_create(
        player=player,
        name=DECK_NAME,
        defaults={
            "selected": True,
        },
    )

    return deck


@sync_to_async
def add_ball_to_deck(
    discord_id: int,
    ball_instance_id: int,
    slot_type: str,
    position: int,
) -> str:
    player, _ = Player.objects.get_or_create(
        discord_id=discord_id,
    )

    deck, _ = BattleDeck.objects.get_or_create(
        player=player,
        name=DECK_NAME,
        defaults={
            "selected": True,
        },
    )

    if slot_type == BattleDeckSlot.ACTIVE:
        if position < 1 or position > 6:
            return "Active slots must be from 1 to 6."

    elif slot_type == BattleDeckSlot.BENCH:
        if position < 1 or position > 2:
            return "Bench slots must be from 1 to 2."

    else:
        return "Invalid slot type."

    try:
        ball_instance = BallInstance.objects.select_related("ball").get(
            id=ball_instance_id,
            player=player,
        )
    except BallInstance.DoesNotExist:
        return "You do not own that ball instance."

    if BattleDeckSlot.objects.filter(
        deck=deck,
        ball_instance=ball_instance,
    ).exists():
        return "That ball is already in your deck."

    # Replace whatever was already in that slot.
    BattleDeckSlot.objects.filter(
        deck=deck,
        slot_type=slot_type,
        position=position,
    ).delete()

    BattleDeckSlot.objects.create(
        deck=deck,
        ball_instance=ball_instance,
        slot_type=slot_type,
        position=position,
    )

    ball_name = get_ball_name(ball_instance)

    return f"Added **{ball_name}** `#{ball_instance.id}` to **{slot_type} slot {position}**."


@sync_to_async
def remove_ball_from_deck(
    discord_id: int,
    ball_instance_id: int,
) -> str:
    player, _ = Player.objects.get_or_create(
        discord_id=discord_id,
    )

    deck = BattleDeck.objects.filter(
        player=player,
        name=DECK_NAME,
    ).first()

    if not deck:
        return "You do not have a battle deck yet."

    slot = BattleDeckSlot.objects.filter(
        deck=deck,
        ball_instance_id=ball_instance_id,
    ).select_related("ball_instance", "ball_instance__ball").first()

    if not slot:
        return "That ball is not in your deck."

    ball_name = get_ball_name(slot.ball_instance)
    slot.delete()

    return f"Removed **{ball_name}** `#{ball_instance_id}` from your deck."


@sync_to_async
def swap_deck_slots(
    discord_id: int,
    first_slot_type: str,
    first_position: int,
    second_slot_type: str,
    second_position: int,
) -> str:
    player, _ = Player.objects.get_or_create(
        discord_id=discord_id,
    )

    deck = BattleDeck.objects.filter(
        player=player,
        name=DECK_NAME,
    ).first()

    if not deck:
        return "You do not have a battle deck yet."

    valid_first = (
        first_slot_type == BattleDeckSlot.ACTIVE and 1 <= first_position <= 6
    ) or (
        first_slot_type == BattleDeckSlot.BENCH and 1 <= first_position <= 2
    )

    valid_second = (
        second_slot_type == BattleDeckSlot.ACTIVE and 1 <= second_position <= 6
    ) or (
        second_slot_type == BattleDeckSlot.BENCH and 1 <= second_position <= 2
    )

    if not valid_first:
        return "The first slot is invalid."

    if not valid_second:
        return "The second slot is invalid."

    first = BattleDeckSlot.objects.filter(
        deck=deck,
        slot_type=first_slot_type,
        position=first_position,
    ).first()

    second = BattleDeckSlot.objects.filter(
        deck=deck,
        slot_type=second_slot_type,
        position=second_position,
    ).first()

    if not first:
        return "The first slot is empty."

    if not second:
        return "The second slot is empty."

    if first.id == second.id:
        return "Those are the same slot."

    with transaction.atomic():
        # Move first slot temporarily so the unique slot constraint does not conflict.
        first.slot_type = "temp"
        first.position = 99
        first.save(update_fields=["slot_type", "position"])

        second.slot_type = first_slot_type
        second.position = first_position
        second.save(update_fields=["slot_type", "position"])

        first.slot_type = second_slot_type
        first.position = second_position
        first.save(update_fields=["slot_type", "position"])

    return "Swapped those two deck slots."


@sync_to_async
def get_deck_embed(discord_id: int) -> discord.Embed:
    player, _ = Player.objects.get_or_create(
        discord_id=discord_id,
    )

    deck = BattleDeck.objects.filter(
        player=player,
        name=DECK_NAME,
    ).first()

    embed = discord.Embed(
        title="Battle Deck",
        description="6 active balls and 2 benched balls.",
    )

    if not deck:
        embed.add_field(
            name="Deck",
            value="You do not have a battle deck yet.",
            inline=False,
        )
        return embed

    slots = list(
        BattleDeckSlot.objects.filter(deck=deck)
        .select_related("ball_instance", "ball_instance__ball")
        .order_by("slot_type", "position")
    )

    active_slots = {
        slot.position: slot
        for slot in slots
        if slot.slot_type == BattleDeckSlot.ACTIVE
    }

    bench_slots = {
        slot.position: slot
        for slot in slots
        if slot.slot_type == BattleDeckSlot.BENCH
    }

    active_lines = []

    for position in range(1, 7):
        slot = active_slots.get(position)

        if not slot:
            active_lines.append(f"`{position}.` Empty")
            continue

        ball_name = get_ball_name(slot.ball_instance)

        active_lines.append(
            f"`{position}.` **{ball_name}** `#{slot.ball_instance.id}`"
        )

    bench_lines = []

    for position in range(1, 3):
        slot = bench_slots.get(position)

        if not slot:
            bench_lines.append(f"`{position}.` Empty")
            continue

        ball_name = get_ball_name(slot.ball_instance)

        bench_lines.append(
            f"`{position}.` **{ball_name}** `#{slot.ball_instance.id}`"
        )

    embed.add_field(
        name="Active",
        value="\n".join(active_lines),
        inline=False,
    )

    embed.add_field(
        name="Bench",
        value="\n".join(bench_lines),
        inline=False,
    )

    return embed


@sync_to_async
def deck_is_ready(discord_id: int) -> tuple[bool, str]:
    player, _ = Player.objects.get_or_create(
        discord_id=discord_id,
    )

    deck = BattleDeck.objects.filter(
        player=player,
        name=DECK_NAME,
    ).first()

    if not deck:
        return False, "You do not have a battle deck."

    active_count = BattleDeckSlot.objects.filter(
        deck=deck,
        slot_type=BattleDeckSlot.ACTIVE,
    ).count()

    bench_count = BattleDeckSlot.objects.filter(
        deck=deck,
        slot_type=BattleDeckSlot.BENCH,
    ).count()

    if active_count < 6:
        return False, f"You need 6 active balls. You currently have {active_count}/6."

    if bench_count < 2:
        return False, f"You need 2 benched balls. You currently have {bench_count}/2."

    return True, "Deck is ready."
