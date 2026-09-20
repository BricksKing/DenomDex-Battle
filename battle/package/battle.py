from dataclasses import dataclass, field


class BattleError(ValueError):
    """Raised when a player attempts an invalid battle action."""


@dataclass
class BattleBall:
    instance_id: int
    name: str
    max_hp: int
    attack_power: int
    hp: int = field(init=False)

    def __post_init__(self) -> None:
        self.hp = self.max_hp

    @property
    def is_alive(self) -> bool:
        return self.hp > 0


@dataclass
class BattleTeam:
    user_id: int
    balls: list[BattleBall]
    active: list[int] = field(default_factory=lambda: [0, 1])
    reserve: list[int] = field(default_factory=lambda: [2, 3, 4, 5])

    def __post_init__(self) -> None:
        if len(self.balls) != 6:
            raise ValueError("A prototype battle team must contain exactly 6 balls.")

    @property
    def defeated(self) -> bool:
        return not any(ball.is_alive for ball in self.balls)


class BattleSession:
    """In-memory prototype state. No battle state is persisted to the database."""

    def __init__(self, first_team: BattleTeam, second_team: BattleTeam):
        self.teams = {
            first_team.user_id: first_team,
            second_team.user_id: second_team,
        }
        self.turn_order = [first_team.user_id, second_team.user_id]
        self.turn_index = 0
        self.winner_id: int | None = None
        self.log = "The duel has started."

    @property
    def current_player_id(self) -> int:
        return self.turn_order[self.turn_index]

    @property
    def is_finished(self) -> bool:
        return self.winner_id is not None

    def team_for(self, user_id: int) -> BattleTeam:
        try:
            return self.teams[user_id]
        except KeyError as exc:
            raise BattleError("You are not part of this duel.") from exc

    def opponent_of(self, user_id: int) -> BattleTeam:
        self.team_for(user_id)
        opponent_id = next(player_id for player_id in self.turn_order if player_id != user_id)
        return self.teams[opponent_id]

    def _check_turn(self, user_id: int) -> None:
        self.team_for(user_id)
        if self.is_finished:
            raise BattleError("This duel has already ended.")
        if user_id != self.current_player_id:
            raise BattleError("It is not your turn.")

    def _advance_turn(self) -> None:
        self.turn_index = (self.turn_index + 1) % len(self.turn_order)

    def attack(self, user_id: int, attacker_slot: int, target_slot: int) -> str:
        self._check_turn(user_id)
        team = self.team_for(user_id)
        opponent = self.opponent_of(user_id)

        if attacker_slot not in (0, 1) or target_slot not in (0, 1):
            raise BattleError("Choose an active ball.")

        attacker = team.balls[team.active[attacker_slot]]
        target = opponent.balls[opponent.active[target_slot]]

        if not attacker.is_alive:
            raise BattleError(f"{attacker.name} has fainted and cannot attack.")
        if not target.is_alive:
            raise BattleError(f"{target.name} has already fainted.")

        damage = min(attacker.attack_power, target.hp)
        target.hp -= damage
        message = f"{attacker.name} attacked {target.name} for {damage} damage."

        if not target.is_alive:
            message += f" {target.name} fainted."
            for reserve_slot, incoming_index in enumerate(opponent.reserve):
                incoming = opponent.balls[incoming_index]
                if incoming.is_alive:
                    opponent.reserve[reserve_slot] = opponent.active[target_slot]
                    opponent.active[target_slot] = incoming_index
                    message += f" {incoming.name} automatically entered the battle."
                    break

        if opponent.defeated:
            self.winner_id = user_id
            message += " The battle is over."
        else:
            self._advance_turn()

        self.log = message
        return message

    def swap(self, user_id: int, active_slot: int, reserve_slot: int) -> str:
        self._check_turn(user_id)
        team = self.team_for(user_id)

        if active_slot not in (0, 1) or reserve_slot not in (0, 1, 2, 3):
            raise BattleError("Choose a valid active and reserve slot.")

        incoming_index = team.reserve[reserve_slot]
        incoming = team.balls[incoming_index]
        if not incoming.is_alive:
            raise BattleError(f"{incoming.name} has fainted and cannot be swapped in.")

        outgoing_index = team.active[active_slot]
        outgoing = team.balls[outgoing_index]
        team.active[active_slot] = incoming_index
        team.reserve[reserve_slot] = outgoing_index

        self.log = f"{outgoing.name} swapped out for {incoming.name}."
        self._advance_turn()
        return self.log

    def surrender(self, user_id: int) -> int:
        self.team_for(user_id)
        if self.is_finished:
            raise BattleError("This duel has already ended.")

        self.winner_id = self.opponent_of(user_id).user_id
        self.log = f"<@{user_id}> surrendered."
        return self.winner_id

