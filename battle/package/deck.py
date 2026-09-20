import discord

from asgiref.sync import sync_to_async
from django.db import transaction

from bd_models.models import BallInstance, Player
from ..models import BattleDeck, BattleDeckSlot


DECK_NAME = "Default Deck"
ACTIVE_SLOTS = 2
RESERVE_SLOTS = 4


def get_ball_name(ball_instance: BallInstance) -> str:
    ball = ball_instance.ball

    return (
        getattr(ball, "country", None)
        or getattr(ball, "name", None)
        or str(ball)
    )


def get_instance_display_id(instance: BallInstance) -> str:
    # BallsDex-style BallInstance ID: integer primary key shown as uppercase hex
    return f"{instance.pk:X}"


def get_instance_battle_stats(instance: BallInstance) -> tuple[int, int]:
    """Calculate the instance's effective HP and ATK, including its bonuses."""
    ball = instance.ball
    health = ball.health + int(ball.health * instance.health_bonus / 100)
    attack = ball.attack + int(ball.attack * instance.attack_bonus / 100)
    return health, attack


def parse_instance_hex(instance_id: str) -> int | None:
    clean_id = (
        instance_id.strip()
        .replace("#", "")
        .replace(".", "")
        .replace(" ", "")
    )

    if not clean_id:
        return None

    try:
        return int(clean_id, 16)
    except ValueError:
        return None


@sync_to_async
def search_owned_ball_instances(
    discord_id: int,
    query: str,
) -> list[tuple[str, str]]:
    player = Player.objects.filter(discord_id=discord_id).first()

    if not player:
        return []

    qs = (
        BallInstance.objects.filter(player=player)
        .select_related("ball")
        .order_by("id")
    )

    query = query.strip()

    if query:
        clean_query = query.replace("#", "").replace(".", "").replace(" ", "")

        parsed_id = parse_instance_hex(clean_query)

        if parsed_id is not None:
            qs = qs.filter(pk=parsed_id)
        else:
            qs = qs.filter(ball__country__icontains=query)

    results = []

    for instance in qs[:25]:
        ball_name = get_ball_name(instance)
        display_id = get_instance_display_id(instance)

        results.append(
            (
                f"{ball_name} #{display_id}",
                display_id,
            )
        )

    return results


@sync_to_async
def get_or_create_deck(discord_id: int) -> BattleDeck:
    player, _ = Player.objects.get_or_create(discord_id=discord_id)

    deck, _ = BattleDeck.objects.get_or_create(
        player=player,
        name=DECK_NAME,
        defaults={"selected": True},
    )

    return deck


@sync_to_async
def add_ball_to_deck(
    discord_id: int,
    ball_instance_id: str,
    slot_type: str,
    position: int,
    replace: bool = False,
) -> dict:
    player = Player.objects.filter(
        discord_id=discord_id,
    ).first()

    if not player:
        return {
            "status": "error",
            "message": "You do not have a player account.",
        }

    deck, _ = BattleDeck.objects.get_or_create(
        player=player,
        name=DECK_NAME,
        defaults={"selected": True},
    )

    # Validate position
    if slot_type == BattleDeckSlot.ACTIVE:
        if not 1 <= position <= ACTIVE_SLOTS:
            return {
                "status": "error",
                "message": f"Active slots must be from 1 to {ACTIVE_SLOTS}.",
            }

    elif slot_type == BattleDeckSlot.BENCH:
        if not 1 <= position <= RESERVE_SLOTS:
            return {
                "status": "error",
                "message": f"Reserve slots must be from 1 to {RESERVE_SLOTS}.",
            }

    else:
        return {
            "status": "error",
            "message": "Invalid slot type.",
        }

    parsed_id = parse_instance_hex(ball_instance_id)

    if parsed_id is None:
        return {
            "status": "error",
            "message": "Invalid ball instance ID.",
        }

    ball_instance = (
        BallInstance.objects
        .select_related("ball")
        .filter(
            player=player,
            pk=parsed_id,
        )
        .first()
    )

    if not ball_instance:
        return {
            "status": "error",
            "message": "You do not own that ball instance.",
        }

    ball_name = get_ball_name(ball_instance)
    display_id = get_instance_display_id(ball_instance)

    # Check whether this ball is already somewhere in the deck
    current_slot = (
        BattleDeckSlot.objects
        .filter(
            deck=deck,
            ball_instance=ball_instance,
        )
        .first()
    )

    # They selected the slot it's already in
    if (
        current_slot
        and current_slot.slot_type == slot_type
        and current_slot.position == position
    ):
        return {
            "status": "error",
            "message": (
                f"**{ball_name}** `#{display_id}` is already "
                f"in **{slot_type} slot {position}**."
            ),
        }

    # Check target slot
    target_slot = (
        BattleDeckSlot.objects
        .select_related(
            "ball_instance",
            "ball_instance__ball",
        )
        .filter(
            deck=deck,
            slot_type=slot_type,
            position=position,
        )
        .first()
    )

    # Destination contains another ball
    if target_slot and not replace:
        return {
            "status": "occupied",

            "new_name": ball_name,
            "new_id": display_id,

            "old_name": get_ball_name(target_slot.ball_instance),
            "old_id": get_instance_display_id(target_slot.ball_instance),

            "slot_type": slot_type,
            "position": position,

            # Lets cog know whether we're moving an existing deck ball
            "moving": current_slot is not None,
        }

    with transaction.atomic():

        # If we're replacing somebody at the destination,
        # remove the destination ball first.
        if target_slot and replace:
            target_slot.delete()

        # If this ball already exists in the deck,
        # MOVE its existing slot instead of creating another one.
        if current_slot:
            old_slot_type = current_slot.slot_type
            old_position = current_slot.position

            current_slot.slot_type = slot_type
            current_slot.position = position

            current_slot.save(
                update_fields=[
                    "slot_type",
                    "position",
                ]
            )

            return {
                "status": "moved",
                "message": (
                    f"Moved **{ball_name}** `#{display_id}` "
                    f"from **{old_slot_type} slot {old_position}** "
                    f"to **{slot_type} slot {position}**."
                ),
            }

        # Ball wasn't already in deck, create a new slot
        BattleDeckSlot.objects.create(
            deck=deck,
            ball_instance=ball_instance,
            slot_type=slot_type,
            position=position,
        )

    return {
        "status": "added",
        "message": (
            f"Added **{ball_name}** `#{display_id}` "
            f"to **{slot_type} slot {position}**."
        ),
    }

@sync_to_async
def remove_ball_from_deck(
    discord_id: int,
    ball_instance_id: str,
) -> str:
    player, _ = Player.objects.get_or_create(discord_id=discord_id)

    deck = BattleDeck.objects.filter(
        player=player,
        name=DECK_NAME,
    ).first()

    if not deck:
        return "You do not have a battle deck yet."

    parsed_id = parse_instance_hex(ball_instance_id)

    if parsed_id is None:
        return "Invalid ball instance ID."

    ball_instance = (
        BallInstance.objects.select_related("ball")
        .filter(
            player=player,
            pk=parsed_id,
        )
        .first()
    )

    if not ball_instance:
        return "You do not own that ball instance."

    slot = (
        BattleDeckSlot.objects.filter(
            deck=deck,
            ball_instance=ball_instance,
        )
        .select_related("ball_instance", "ball_instance__ball")
        .first()
    )

    if not slot:
        return "That ball is not in your deck."

    ball_name = get_ball_name(slot.ball_instance)
    display_id = get_instance_display_id(slot.ball_instance)

    slot.delete()

    return f"Removed **{ball_name}** `#{display_id}` from your deck."


@sync_to_async
def get_deck_embed(discord_id: int) -> discord.Embed:
    player, _ = Player.objects.get_or_create(discord_id=discord_id)

    deck = BattleDeck.objects.filter(
        player=player,
        name=DECK_NAME,
    ).first()

    embed = discord.Embed(
        title="Battle Deck",
        description="2 active balls and 4 reserve balls.",
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

    for position in sorted(set(range(1, ACTIVE_SLOTS + 1)) | set(active_slots)):
        slot = active_slots.get(position)

        if not slot:
            active_lines.append(f"`{position}.` Empty")
            continue

        ball_name = get_ball_name(slot.ball_instance)
        display_id = get_instance_display_id(slot.ball_instance)

        active_lines.append(
            f"`{position}.` **{ball_name}** `#{display_id}`"
            + (" — move to reserve or remove" if position > ACTIVE_SLOTS else "")
        )

    bench_lines = []

    for position in sorted(set(range(1, RESERVE_SLOTS + 1)) | set(bench_slots)):
        slot = bench_slots.get(position)

        if not slot:
            bench_lines.append(f"`{position}.` Empty")
            continue

        ball_name = get_ball_name(slot.ball_instance)
        display_id = get_instance_display_id(slot.ball_instance)

        bench_lines.append(
            f"`{position}.` **{ball_name}** `#{display_id}`"
            + (" — move to a valid reserve slot or remove" if position > RESERVE_SLOTS else "")
        )

    embed.add_field(
        name="Active",
        value="\n".join(active_lines),
        inline=False,
    )

    embed.add_field(
        name="Reserve",
        value="\n".join(bench_lines),
        inline=False,
    )

    return embed


@sync_to_async
def deck_is_ready(discord_id: int) -> tuple[bool, str]:
    player, _ = Player.objects.get_or_create(discord_id=discord_id)

    deck = BattleDeck.objects.filter(
        player=player,
        name=DECK_NAME,
    ).first()

    if not deck:
        return False, "You do not have a battle deck."

    active_count = BattleDeckSlot.objects.filter(
        deck=deck,
        slot_type=BattleDeckSlot.ACTIVE,
        ball_instance__player=player,
        ball_instance__deleted=False,
    ).count()

    bench_count = BattleDeckSlot.objects.filter(
        deck=deck,
        slot_type=BattleDeckSlot.BENCH,
        ball_instance__player=player,
        ball_instance__deleted=False,
    ).count()

    if active_count > ACTIVE_SLOTS:
        return False, (
            f"Your saved deck has {active_count} active balls; the new limit is {ACTIVE_SLOTS}. "
            "Use /battle deck view to see their IDs, then /battle deck add to move "
            f"the extra active balls into reserve slots 1–{RESERVE_SLOTS}. "
            "If a reserve slot is occupied, confirm its replacement, "
            "or use /battle deck remove to remove an extra ball from the deck."
        )

    if active_count != ACTIVE_SLOTS:
        return False, f"You need {ACTIVE_SLOTS} active balls. You currently have {active_count}/{ACTIVE_SLOTS}."

    if bench_count != RESERVE_SLOTS:
        return False, f"You need {RESERVE_SLOTS} reserve balls. You currently have {bench_count}/{RESERVE_SLOTS}."

    return True, "Deck is ready."


@sync_to_async
def get_battle_lineup(discord_id: int) -> list[dict]:
    """Return active slots first, followed by reserve slots."""
    player = Player.objects.filter(discord_id=discord_id).first()
    if not player:
        return []

    deck = BattleDeck.objects.filter(player=player, name=DECK_NAME).first()
    if not deck:
        return []

    slots = list(
        BattleDeckSlot.objects.filter(
            deck=deck,
            ball_instance__player=player,
            ball_instance__deleted=False,
        )
        .select_related("ball_instance", "ball_instance__ball")
    )
    active = sorted(
        (slot for slot in slots if slot.slot_type == BattleDeckSlot.ACTIVE),
        key=lambda slot: slot.position,
    )
    reserve = sorted(
        (slot for slot in slots if slot.slot_type == BattleDeckSlot.BENCH),
        key=lambda slot: slot.position,
    )

    # Match the readiness check: gaps in saved position numbers are harmless.
    if len(active) != ACTIVE_SLOTS or len(reserve) != RESERVE_SLOTS:
        return []

    lineup = []
    for slot in active + reserve:
        instance = slot.ball_instance
        health, attack = get_instance_battle_stats(instance)
        lineup.append(
            {
                "instance_id": instance.pk,
                "name": get_ball_name(instance),
                "health": health,
                "attack": attack,
            }
        )

    return lineup

