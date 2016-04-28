import sims4.callback_utils
import enum

class FinishingType(enum.Int, export=False):
    __qualname__ = 'FinishingType'
    KILLED = Ellipsis
    AUTO_EXIT = Ellipsis
    DISPLACED = Ellipsis
    NATURAL = Ellipsis
    RESET = Ellipsis
    USER_CANCEL = Ellipsis
    SI_FINISHED = Ellipsis
    TARGET_DELETED = Ellipsis
    FAILED_TESTS = Ellipsis
    TRANSITION_FAILURE = Ellipsis
    INTERACTION_INCOMPATIBILITY = Ellipsis
    INTERACTION_QUEUE = Ellipsis
    PRIORITY = Ellipsis
    SOCIALS = Ellipsis
    OBJECT_CHANGED = Ellipsis
    SITUATIONS = Ellipsis
    CRAFTING = Ellipsis
    LIABILITY = Ellipsis
    DIALOG = Ellipsis
    CONDITIONAL_EXIT = Ellipsis
    FIRE = Ellipsis
    WEDDING = Ellipsis
    UNKNOWN = Ellipsis

class InteractionFinisher:
    __qualname__ = 'InteractionFinisher'
    CANCELED = frozenset([FinishingType.USER_CANCEL, FinishingType.SI_FINISHED, FinishingType.TARGET_DELETED, FinishingType.FAILED_TESTS, FinishingType.TRANSITION_FAILURE, FinishingType.INTERACTION_INCOMPATIBILITY, FinishingType.INTERACTION_QUEUE, FinishingType.PRIORITY, FinishingType.SOCIALS, FinishingType.OBJECT_CHANGED, FinishingType.SITUATIONS, FinishingType.CRAFTING, FinishingType.LIABILITY, FinishingType.DIALOG, FinishingType.CONDITIONAL_EXIT, FinishingType.FIRE, FinishingType.WEDDING])

    def __init__(self, interaction):
        self._history = []
        self._pending = []
        self._interaction = interaction
        self._on_finishing_callbacks = sims4.callback_utils.CallableList()

    def on_finishing_move(self, move):
        self._pending.append(move)
        for pending_move in self._pending:
            while pending_move not in self._history:
                self._history.append(pending_move)
        self._on_finishing_callbacks(self._interaction)
        self._pending.clear()

    def on_pending_finishing_move(self, move):
        if self.is_finishing:
            self.on_finishing_move(move)
        else:
            self._pending.append(move)

    def register_callback(self, callback):
        self._on_finishing_callbacks.append(callback)

    def unregister_callback(self, callback):
        if callback in self._on_finishing_callbacks:
            self._on_finishing_callbacks.remove(callback)

    def can_run_subinteraction(self):
        return not self.is_finishing and not self._pending

    @property
    def is_finishing(self):
        return bool(self._history)

    @property
    def has_been_killed(self):
        for move in self._history:
            while move == FinishingType.KILLED:
                return True
        return False

    @property
    def has_been_canceled(self):
        for move in self._history:
            while move in self.CANCELED:
                return True
        return False

    @property
    def has_been_user_canceled(self):
        for move in self._history:
            while move == FinishingType.USER_CANCEL:
                return True
        return False

    @property
    def has_been_reset(self):
        for move in self._history:
            while move == FinishingType.RESET:
                return True
        return False

    @property
    def transition_failed(self):
        return any(move == FinishingType.TRANSITION_FAILURE for move in self._history)

    @property
    def is_finishing_naturally(self):
        return self._history and self._history[0] == FinishingType.NATURAL

    @property
    def finishing_type(self):
        if self._history:
            return self._history[0]

    @property
    def was_initially_displaced(self):
        return self._history and self._history[0] == FinishingType.DISPLACED

    @property
    def has_pending_natural_finisher(self):
        if not self._pending:
            return True
        for pending_move in self._pending:
            while pending_move == FinishingType.NATURAL:
                return True
        return False

    def __repr__(self):
        if not self._history:
            return 'Not Finishing'
        return ','.join([str(move) for move in self._history])

