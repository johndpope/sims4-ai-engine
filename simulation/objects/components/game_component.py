import random
from interactions import ParticipantType
from interactions.utils.loot_ops import BaseGameLootOperation
from objects.components import Component, types
from objects.components.state import ObjectStateValue
from objects.system import create_object, get_child_objects
from element_utils import build_critical_section_with_finally
from sims4.localization import TunableLocalizedStringFactory
from sims4.tuning.instances import TunedInstanceMetaclass
from sims4.tuning.tunable import TunableFactory, TunableInterval, TunableEnumEntry, TunableList, TunableReference, Tunable, TunableTuple, TunableRange, OptionalTunable, TunableVariant
from statistics.skill import Skill
from statistics.statistic import Statistic
import enum
import gsi_handlers
import interactions.utils
import services
import sims4.log
logger = sims4.log.Logger('GameComponent')

class GameTargetType(enum.Int):
    __qualname__ = 'GameTargetType'
    OPPOSING_SIM = 0
    OPPOSING_TEAM = 1
    ALL_OPPOSING_TEAMS = 2

class GameRules(metaclass=TunedInstanceMetaclass, manager=services.get_instance_manager(sims4.resources.Types.GAME_RULESET)):
    __qualname__ = 'GameRules'
    INSTANCE_TUNABLES = {'game_name': TunableLocalizedStringFactory(description='\n            Name of the game.\n            ', default=1860708663), 'teams_per_game': TunableInterval(description='\n            An interval specifying the number of teams allowed per game.\n            \n            Joining Sims are put on a new team if the maximum number of teams\n            has not yet been met, otherwise they are put into the team with the\n            fewest number of players.\n            ', tunable_type=int, default_lower=2, default_upper=2, minimum=1), 'players_per_game': TunableInterval(description='\n            An interval specifying the number of players allowed per game.\n            \n            If the maximum number of players has not been met, Sims can\n            continue to join a game.  Joining Sims are put on a new team if the\n            maximum number of teams as specified in the "teams_per_game"\n            tunable has not yet been met, otherwise they are put into the team\n            with the fewest number of players.\n            ', tunable_type=int, default_lower=2, default_upper=2, minimum=1), 'players_per_turn': TunableRange(description='\n            An integer specifying number of players from the active team who\n            take their turn at one time.\n            ', tunable_type=int, default=1, minimum=1), 'initial_state': ObjectStateValue.TunableReference(description="\n            The game's starting object state.\n            "), 'score_info': TunableTuple(description="\n            Tunables that affect the game's score.\n            ", winning_score=Tunable(description='\n                An integer value specifying at what score the game will end.\n                ', tunable_type=int, default=100), score_increase=TunableInterval(description='\n                An interval specifying the minimum and maximum score increases\n                possible in one turn. A random value in this interval will be\n                generated each time score loot is given.\n                ', tunable_type=int, default_lower=35, default_upper=50, minimum=0), skill_level_bonus=Tunable(description="\n                A bonus number of points based on the Sim's skill level in the\n                relevant_skill tunable that will be added to score_increase.\n                \n                ex: If this value is 2 and the Sim receiving score has a\n                relevant skill level of 4, they will receive 8 (2 * 4) extra\n                points.\n                ", tunable_type=float, default=2), relevant_skill=Skill.TunableReference(description="\n                The skill relevant to this game.  Each Sim's proficiency in\n                this skill will effect the score increase they get.\n                "), use_effective_skill_level=Tunable(description='\n                If checked, we will use the effective skill level rather than\n                the actual skill level of the relevant_skill tunable.\n                ', tunable_type=bool, default=True), progress_stat=Statistic.TunableReference(description='\n                The statistic that advances the progress state of this game.\n                ')), 'clear_score_on_player_join': Tunable(description='\n            Tunable that, when checked, will clear the game score when a player joins.\n            \n            This essentially resets the game.\n            ', tunable_type=bool, default=False), 'alternate_target_object': OptionalTunable(description='\n            Tunable that, when enabled, means the game should create an alternate object\n            in the specified slot on setup that will be modified as the game goes on\n            and destroyed when the game ends.\n            ', tunable=TunableTuple(target_game_object=TunableReference(description='\n                    The definition of the object that will be created/destroyed/altered\n                    by the game.\n                    ', manager=services.definition_manager()), parent_slot=TunableVariant(description='\n                    The slot on the parent object where the target_game_object object should go. This\n                    may be either the exact name of a bone on the parent object or a\n                    slot type, in which case the first empty slot of the specified type\n                    in which the child object fits will be used.\n                    ', by_name=Tunable(description='\n                        The exact name of a slot on the parent object in which the target\n                        game object should go.  \n                        ', tunable_type=str, default='_ctnm_'), by_reference=TunableReference(description='\n                        A particular slot type in which the target game object should go.  The\n                        first empty slot of this type found on the parent will be used.\n                        ', manager=services.get_instance_manager(sims4.resources.Types.SLOT_TYPE)))))}

class GameComponent(Component, component_name=types.GAME_COMPONENT):
    __qualname__ = 'GameComponent'
    _PLAYERS = 0
    _SCORE = 1
    _NEXT_PLAYER = 2
    FACTORY_TUNABLES = {'description': 'Manage information about the games that the attached object can play.', 'games': TunableList(TunableReference(manager=services.get_instance_manager(sims4.resources.Types.GAME_RULESET)), description='The games that the attached object can play.')}

    def __init__(self, owner, games, **kwargs):
        super().__init__(owner)
        self.owner = owner
        self.games = games
        self._teams = []
        self.active_sims = []
        self.active_team = None
        self.winning_team = None
        self.current_game = None
        self.current_target = None
        self.has_started = False
        self.requires_setup = False
        self.target_object = None

    @property
    def number_of_players(self):
        return sum(len(team[self._PLAYERS]) for team in self._teams)

    @property
    def number_of_teams(self):
        return len(self._teams)

    def get_team_name(self, team_number):
        return 'Team #' + str(team_number + 1)

    def is_joinable(self, sim=None):
        if self.current_game is None or self.number_of_players < self.current_game.players_per_game.upper_bound:
            if sim is None:
                return True
            for team in self._teams:
                while sim in team[self._PLAYERS]:
                    return False
            return True
        return False

    @property
    def game_state_dirty(self):
        if self.target_object is None:
            return False
        if self.current_game.initial_state is not None and not self.target_object.state_component.state_value_active(self.current_game.initial_state):
            return True
        return False

    @property
    def game_has_ended(self):
        if self.current_game is not None and self.winning_team is None:
            return False
        return True

    @property
    def progress_stat(self):
        max_score = max(team[self._SCORE] for team in self._teams)
        progress = max_score/self.current_game.score_info.winning_score
        progress *= self.current_game.score_info.progress_stat.max_value_tuning
        return progress

    def get_game_target(self, actor_sim=None):
        if self.number_of_teams <= 1 or self.active_team is None:
            return
        if actor_sim is None:
            actor_team = self.active_team
        else:
            for (actor_team, team) in enumerate(self._teams):
                while actor_sim in team[self._PLAYERS]:
                    break
            return
        random_team = random.randrange(self.number_of_teams - 1)
        if random_team >= actor_team:
            random_team += 1
        random_sim = random.choice(self._teams[random_team][self._PLAYERS])
        return random_sim

    def _build_active_sims(self):
        del self.active_sims[:]
        (self.active_sims, next_player) = self._generate_active_sims()
        self._teams[self.active_team][self._NEXT_PLAYER] = next_player

    def _generate_active_sims(self):
        temporary_active_sims = []
        team = self._teams[self.active_team][self._PLAYERS]
        next_player = self._teams[self.active_team][self._NEXT_PLAYER]
        next_player %= len(team)
        i = 0
        while i < self.current_game.players_per_turn:
            temporary_active_sims.append(team[next_player])
            i += 1
            next_player += 1
            next_player %= len(team)
        return (temporary_active_sims, next_player)

    def _rebalance_teams(self):
        excess_index = None
        starvation_index = None
        min_value = int(self.number_of_players/self.number_of_teams)
        i = 0
        for team in self._teams:
            team_length = len(team[self._PLAYERS])
            if excess_index is None and team_length > min_value:
                excess_index = i
            elif team_length < min_value:
                starvation_index = i
            if excess_index is not None and starvation_index is not None:
                self._teams[starvation_index][self._PLAYERS].append(self._teams[excess_index][self._PLAYERS].pop())
                break
            i += 1
        if starvation_index is not None and excess_index is None:
            logger.error('Unable to re-balance teams. No excess index index found.', owner='tastle')
        if gsi_handlers.game_component_handlers.game_log_archiver.enabled:
            gsi_handlers.game_component_handlers.archive_game_log_entry(self.target_object, 'Rebalanced teams.')

    def clear_scores(self):
        for team in self._teams:
            team[self._SCORE] = 0
        self.winning_team = None
        if gsi_handlers.game_component_handlers.game_log_archiver.enabled:
            gsi_handlers.game_component_handlers.archive_game_log_entry(self.target_object, 'Cleared all scores.')

    def add_team(self, sims):
        if self.current_game is None:
            logger.error('Cannot add a team when no game is running.', owner='tastle')
            return
        if self.number_of_teams >= self.current_game.teams_per_game.upper_bound:
            logger.error('Cannot add a team to a game that already has the maximum number of allowed teams.', owner='tastle')
            return
        self._teams.append([sims, 0, 0])
        if gsi_handlers.game_component_handlers.game_log_archiver.enabled:
            team_name = self.get_team_name(len(self._teams) - 1)
            team_str = 'Added team: ' + team_name
            gsi_handlers.game_component_handlers.archive_game_log_entry(self.target_object, team_str)

    def add_player(self, sim):
        if self.current_game is None:
            logger.error('Cannot add a player when no game is running.', owner='tastle')
            return
        if self.number_of_players >= self.current_game.players_per_game.upper_bound:
            logger.error('Cannot add any players to a game that already has the maximum number of allowed players.', owner='tastle')
            return
        if gsi_handlers.game_component_handlers.game_log_archiver.enabled:
            player_str = 'Added player: ' + str(sim)
            gsi_handlers.game_component_handlers.archive_game_log_entry(self.target_object, player_str)
        if self.game_state_dirty and not self.has_started:
            self.requires_setup = True
        if self.number_of_teams < self.current_game.teams_per_game.upper_bound:
            self.add_team([sim])
            return
        previous_number_of_players = len(self._teams[0][self._PLAYERS])
        for team in reversed(self._teams):
            while len(team[self._PLAYERS]) <= previous_number_of_players:
                team[self._PLAYERS].append(sim)
                return
        self._teams[0][self._PLAYERS].append(sim)
        if self.current_game.clear_score_on_player_join:
            self.clear_scores()

    def remove_player(self, sim):
        for team in self._teams:
            if sim not in team[self._PLAYERS]:
                pass
            if gsi_handlers.game_component_handlers.game_log_archiver.enabled:
                player_str = 'Removed player: ' + str(sim)
                gsi_handlers.game_component_handlers.archive_game_log_entry(self.target_object, player_str)
            team[self._PLAYERS].remove(sim)
            if self.winning_team is None:
                self._rebalance_teams()
            if not team[self._PLAYERS]:
                self._teams.remove(team)
            if not self.has_started or self.current_game is not None and self.number_of_players < self.current_game.players_per_game.lower_bound:
                self.has_started = False
                self.active_team = None
                del self.active_sims[:]
                if self.game_state_dirty:
                    self.requires_setup = True
            if not self.number_of_teams:
                self.end_game()
            elif self.active_team is not None and self.active_team <= self.number_of_teams:
                self.active_team = random.randrange(self.number_of_teams)
                self._build_active_sims()
            break

    def is_sim_turn(self, sim):
        if self.active_team is not None and self.can_play() and sim in self.active_sims:
            return True
        return False

    def can_play(self):
        if self.current_game is None:
            return False
        team_len = self.number_of_teams
        player_len = self.number_of_players
        teams_per_game = self.current_game.teams_per_game
        if not teams_per_game.lower_bound <= team_len <= teams_per_game.upper_bound:
            return False
        players_per_game = self.current_game.players_per_game
        if not players_per_game.lower_bound <= player_len <= players_per_game.upper_bound:
            return False
        return True

    def take_turn(self, sim=None):
        if gsi_handlers.game_component_handlers.game_log_archiver.enabled and self.active_team is not None:
            team_name = self.get_team_name(self.active_team)
            turn_str = str(sim) + ' (' + team_name + ') ' + 'just finished taking their turn'
            gsi_handlers.game_component_handlers.archive_game_log_entry(self.target_object, turn_str)
        if not self.can_play():
            return False
        if sim and sim in self.active_sims:
            self.active_sims.remove(sim)
        if self.active_sims:
            return False
        if self.active_team is None:
            self.clear_scores()
            self.active_team = random.randrange(self.number_of_teams)
            self.has_started = True
        self._build_active_sims()
        return True

    def set_current_game(self, game):
        if self.current_game is not None:
            self.end_game()
        self.current_game = game
        if self.current_game.alternate_target_object is None:
            self.target_object = self.owner
        if gsi_handlers.game_component_handlers.game_log_archiver.enabled:
            game_str = 'Setting current game to ' + str(self.current_game)
            gsi_handlers.game_component_handlers.archive_game_log_entry(self.target_object, game_str)
            target_str = 'Target Object is ' + str(self.target_object)
            gsi_handlers.game_component_handlers.archive_game_log_entry(self.target_object, target_str)

    def increase_score(self, sim):
        if self.target_object is None:
            return
        for (team_number, team) in enumerate(self._teams):
            if sim not in team[self._PLAYERS]:
                pass
            if self.active_team is not None and team_number != self.active_team:
                return
            score_info = self.current_game.score_info
            score_increase = sims4.random.uniform(score_info.score_increase.lower_bound, score_info.score_increase.upper_bound)
            relevant_skill = score_info.relevant_skill
            if relevant_skill is not None:
                if score_info.use_effective_skill_level:
                    skill_level = sim.get_effective_skill_level(relevant_skill)
                else:
                    skill = sim.get_stat_instance(relevant_skill)
                    skill_level = skill if skill is not None else 0
                score_increase += score_info.skill_level_bonus*skill_level
            team[self._SCORE] += score_increase
            if gsi_handlers.game_component_handlers.game_log_archiver.enabled:
                team_name = self.get_team_name(team_number)
                increase_str = str(sim) + ' scored ' + str(score_increase) + ' points for ' + team_name
                gsi_handlers.game_component_handlers.archive_game_log_entry(self.target_object, increase_str)
                score_str = 'Score for ' + team_name + ' is now ' + str(team[self._SCORE]) + ' / ' + str(score_info.winning_score)
                gsi_handlers.game_component_handlers.archive_game_log_entry(self.target_object, score_str)
            if team[self._SCORE] >= score_info.winning_score:
                self.winning_team = team[self._PLAYERS]
                if gsi_handlers.game_component_handlers.game_log_archiver.enabled:
                    team_name = self.get_team_name(team_number)
                    win_str = team_name + ' has won the game'
                    gsi_handlers.game_component_handlers.archive_game_log_entry(self.target_object, win_str)
            if score_info.progress_stat is not None:
                self.target_object.statistic_tracker.set_value(score_info.progress_stat, self.progress_stat)
        logger.error('The given Sim {} is not a member of any team, so we cannot increase its score.', sim, owner='tastle')

    def end_game(self):
        if gsi_handlers.game_component_handlers.game_log_archiver.enabled:
            game_over_str = 'Game ' + str(self.current_game) + ' has ended'
            gsi_handlers.game_component_handlers.archive_game_log_entry(self.target_object, game_over_str)
        if self.target_object is not None and self.target_object is not self.owner:
            self.target_object.fade_and_destroy()
        self.target_object = None
        self.current_game = None
        self.active_team = None
        self.winning_team = None
        self.has_started = False
        del self._teams[:]
        del self.active_sims[:]

    def setup_game(self):
        self.requires_setup = False
        if self.target_object is not None:
            return
        if gsi_handlers.game_component_handlers.game_log_archiver.enabled:
            setup_str = 'Game ' + str(self.current_game) + ' has been set up'
            gsi_handlers.game_component_handlers.archive_game_log_entry(self.target_object, setup_str)
        self.clear_scores()
        slot_hash = None
        alternate_target_object = self.current_game.alternate_target_object
        parent_slot = alternate_target_object.parent_slot
        if isinstance(parent_slot, str):
            slot_hash = sims4.hash_util.hash32(parent_slot)
        for child in get_child_objects(self.owner):
            while child.definition is alternate_target_object.target_game_object:
                slot = child.parent_slot
                if slot_hash is not None:
                    if slot_hash == slot.slot_name_hash:
                        self.target_object = child
                        return
                        if parent_slot in slot.slot_types:
                            self.target_object = child
                            return
                elif parent_slot in slot.slot_types:
                    self.target_object = child
                    return
        created_object = create_object(alternate_target_object.target_game_object)
        self.target_object = created_object
        self.owner.slot_object(parent_slot=parent_slot, slotting_object=created_object)

TunableGameComponent = TunableFactory.create_auto_factory(GameComponent)

def get_game_references(interaction):
    target_group = interaction.get_participant(ParticipantType.SocialGroup)
    target_object = target_group.anchor if target_group is not None else None
    if target_object is not None:
        game = target_object.game_component
        if game is not None:
            return (game, target_object)
    return (None, None)

class SetupGame(BaseGameLootOperation):
    __qualname__ = 'SetupGame'

    @property
    def loot_type(self):
        return interactions.utils.LootType.GAME_SETUP

    def _apply_to_subject_and_target(self, subject, target, resolver):
        (game, _) = get_game_references(resolver)
        if game is None:
            return False
        game.setup_game()

class TakeTurn(BaseGameLootOperation):
    __qualname__ = 'TakeTurn'

    @property
    def loot_type(self):
        return interactions.utils.LootType.TAKE_TURN

    def _apply_to_subject_and_target(self, subject, target, resolver):
        (game, _) = get_game_references(resolver)
        if game is None:
            return False
        subject_obj = self._get_object_from_recipient(subject)
        game.take_turn(subject_obj)
        return True

class TeamScore(BaseGameLootOperation):
    __qualname__ = 'TeamScore'

    @property
    def loot_type(self):
        return interactions.utils.LootType.TEAM_SCORE

    def _apply_to_subject_and_target(self, subject, target, resolver):
        (game, _) = get_game_references(resolver)
        if game is None:
            return False
        subject_obj = self._get_object_from_recipient(subject)
        game.increase_score(subject_obj)
        return True

class GameOver(BaseGameLootOperation):
    __qualname__ = 'GameOver'

    @property
    def loot_type(self):
        return interactions.utils.LootType.GAME_OVER

    def _apply_to_subject_and_target(self, subject, target, resolver):
        (game, _) = get_game_references(resolver)
        if game is None:
            return False
        if game.winning_team is not None:
            game.end_game()
            return True
        return False

class ResetGame(BaseGameLootOperation):
    __qualname__ = 'ResetGame'

    @property
    def loot_type(self):
        return interactions.utils.LootType.GAME_RESET

    def _apply_to_subject_and_target(self, subject, target, resolver):
        (game, _) = get_game_references(resolver)
        if game is None:
            return False
        game.clear_scores()

class TunableJoinGame(TunableFactory):
    __qualname__ = 'TunableJoinGame'

    @staticmethod
    def factory(interaction, game, ensure_setup, sequence=()):

        def join_game(interaction, game, ensure_setup):
            sim = interaction.sim
            if sim is not None:
                (target_game, _) = get_game_references(interaction)
                if target_game is not None:
                    if target_game.current_game is None:
                        target_game.set_current_game(game)
                    if target_game.current_game is game:
                        target_game.add_player(sim)
                        target_game.take_turn()
                    if ensure_setup:
                        target_game.setup_game()

        def leave_game(interaction):
            sim = interaction.sim
            if sim is not None:
                (target_game, _) = get_game_references(interaction)
                if target_game is not None:
                    target_game.remove_player(sim)

        if game is None:
            return sequence
        sequence = build_critical_section_with_finally(lambda _: join_game(interaction, game, ensure_setup), sequence, lambda _: leave_game(interaction))
        return sequence

    FACTORY_TYPE = factory

    def __init__(self, description='Join a game as part of this interaction, and leave it when the interaction finishes.', **kwargs):
        super().__init__(game=TunableReference(description='\n                A reference to the game created when this interaction is run.\n                ', manager=services.get_instance_manager(sims4.resources.Types.GAME_RULESET)), ensure_setup=Tunable(description='\n                Tunable that, when checked, will make sure the game gets setup.\n                ', tunable_type=bool, default=False), description=description, **kwargs)

class TunableSetGameTarget(TunableFactory):
    __qualname__ = 'TunableSetGameTarget'

    @staticmethod
    def factory(interaction, sequence=()):
        interaction = interaction
        old_target = interaction.target

        def set_new_target():
            (game, _) = get_game_references(interaction)
            if game is None:
                return
            new_target = game.get_game_target(actor_sim=interaction.sim)
            if new_target is not None:
                interaction.set_target(new_target)

        def revert_target():
            interaction.set_target(old_target)

        sequence = build_critical_section_with_finally(lambda _: set_new_target(), sequence, lambda _: revert_target())
        return sequence

    FACTORY_TYPE = factory

    def __init__(self, description="Set an interaction's target to the appropriate reactive Sim for the given game and change it back when the interaction finishes.", **kwargs):
        super().__init__(description=description, **kwargs)

