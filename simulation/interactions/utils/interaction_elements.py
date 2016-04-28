import collections
import random
import weakref
from element_utils import CleanupType, build_element, build_critical_section, build_critical_section_with_finally
from interactions import ParticipantType
from interactions.utils.success_chance import SuccessChance
from objects import VisibilityState
from objects.client_object_mixin import ClientObjectMixin
from objects.slots import RuntimeSlot
from sims4.tuning.tunable import HasTunableFactory, TunableVariant, TunableTuple, TunableEnumEntry, Tunable, TunableReference, TunableRealSecond, OptionalTunable, TunableRange, TunableSimMinute, AutoFactoryInit
from singletons import EMPTY_SET
import clock
import elements
import services
import sims4.log
import sims4.resources
logger = sims4.log.Logger('Interaction_Elements')

class XevtTriggeredElement(elements.ParentElement, HasTunableFactory, AutoFactoryInit):
    __qualname__ = 'XevtTriggeredElement'
    AT_BEGINNING = 'at_beginning'
    AT_END = 'at_end'
    ON_XEVT = 'on_xevt'
    TIMING_DESCRIPTION = '\n        Determines the exact timing of the behavior, either at the beginning\n        of an interaction, the end, or when an xevt occurs in an animation\n        played as part of the interaction.\n        '
    FakeTiming = collections.namedtuple('FakeTiming', ('timing', 'offset_time', 'criticality', 'xevt_id'))
    LOCKED_AT_BEGINNING = FakeTiming(AT_BEGINNING, None, None, None)
    LOCKED_AT_END = FakeTiming(AT_END, None, None, None)
    LOCKED_ON_XEVT = FakeTiming(ON_XEVT, None, None, None)
    FACTORY_TUNABLES = {'description': '\n            The author of this tunable neglected to provide documentation.\n            Shame!\n            ', 'timing': TunableVariant(description=TIMING_DESCRIPTION, default=AT_END, at_beginning=TunableTuple(description="\n                The behavior should occur at the very beginning of the\n                interaction.  It will not be tightly synchronized visually with\n                animation.  This isn't a very common use case and would most\n                likely be used in an immediate interaction or to change hidden\n                state that is used for bookkeeping rather than visual\n                appearance.\n                ", offset_time=OptionalTunable(description='\n                    If enabled, the interaction will wait this amount of time\n                    after the beginning before running the element\n                    ', tunable=TunableSimMinute(description='The interaction will wait this amount of time after the beginning before running the element', default=2)), locked_args={'timing': AT_BEGINNING, 'criticality': CleanupType.NotCritical, 'xevt_id': None}), at_end=TunableTuple(description='\n                The behavior should occur at the end of the interaction.  It\n                will not be tightly synchronized visually with animation.  An\n                example might be an object that gets dirty every time a Sim uses\n                it (so using a commodity change is overkill) but no precise\n                synchronization with animation is desired, as might be the case\n                with vomiting in the toilet.\n                ', locked_args={'timing': AT_END, 'xevt_id': None, 'offset_time': None}, criticality=TunableEnumEntry(CleanupType, CleanupType.OnCancel)), on_xevt=TunableTuple(description="\n                The behavior should occur synchronized visually with an xevt in\n                an animation played as part of the interaction.  If for some\n                reason such an event doesn't occur, the behavior will occur at\n                the end of the interaction.  This is by far the most common use\n                case, as when a Sim flushes a toilet and the water level should\n                change when the actual flush animation and effects fire.\n                ", locked_args={'timing': ON_XEVT, 'offset_time': None}, criticality=TunableEnumEntry(CleanupType, CleanupType.OnCancel), xevt_id=Tunable(int, 100))), 'success_chance': SuccessChance.TunableFactory(description='\n            The percentage chance that this action will be applied.\n            ')}

    def __init__(self, interaction, *, timing, sequence=(), **kwargs):
        super().__init__(timing=None, **kwargs)
        self.interaction = interaction
        self.sequence = sequence
        self.timing = timing.timing
        self.criticality = timing.criticality
        self.xevt_id = timing.xevt_id
        self.result = None
        self.triggered = False
        self.offset_time = timing.offset_time
        self._XevtTriggeredElement__event_handler_handle = None
        success_chance = self.success_chance.get_chance(interaction.get_resolver())
        self._should_do_behavior = random.random() <= success_chance

    def _register_event_handler(self, element):
        self._XevtTriggeredElement__event_handler_handle = self.interaction.animation_context.register_event_handler(self._behavior_event_handler, handler_id=self.xevt_id)

    def _release_event_handler(self, element):
        self._XevtTriggeredElement__event_handler_handle.release()
        self._XevtTriggeredElement__event_handler_handle = None

    def _behavior_element(self, timeline):
        if not self.triggered:
            self.triggered = True
            if self._should_do_behavior:
                self.result = self._do_behavior()
            else:
                self.result = None
        return self.result

    def _behavior_event_handler(self, *_, **__):
        if not self.triggered:
            self.triggered = True
            if self._should_do_behavior:
                self.result = self._do_behavior()
            else:
                self.result = None

    def _run(self, timeline):
        if self.timing == self.AT_BEGINNING:
            if self.offset_time is None:
                sequence = [self._behavior_element, self.sequence]
            else:
                delayed_sequence = build_element([elements.SleepElement(clock.interval_in_sim_minutes(self.offset_time)), self._behavior_element])
                if self.sequence:
                    sequence = elements.AllElement([delayed_sequence, self.sequence])
                else:
                    sequence = delayed_sequence
        elif self.timing == self.AT_END:
            sequence = [self.sequence, self._behavior_element]
        elif self.timing == self.ON_XEVT:
            sequence = [build_critical_section(self._register_event_handler, self.sequence, self._release_event_handler), self._behavior_element]
        child_element = build_element(sequence, critical=self.criticality)
        child_element = self._build_outer_elements(child_element)
        return timeline.run_child(child_element)

    def _build_outer_elements(self, sequence):
        return sequence

    def _do_behavior(self):
        raise NotImplementedError

class ParentObjectElement(XevtTriggeredElement):
    __qualname__ = 'ParentObjectElement'
    FACTORY_TUNABLES = {'description': "\n        This element parents one participant of an interaction to another in\n        a way that doesn't necessarily depend on animation.  Most parenting\n        should be handled by animation or the posture transition system, so\n        make sure you know why you aren't using one of those systems for\n        your feature before tuning this.\n        \n        Examples include positioning objects that move but aren't carryable by\n        Sims (like the canvas on the easel) or objects that should be positioned\n        as a result of an immediate interaction.\n        ", '_parent_object': TunableEnumEntry(description='\n            The participant of an interaction to which an object will be\n            parented.\n            ', tunable_type=ParticipantType, default=ParticipantType.Object), '_parent_slot': TunableVariant(description='\n            The slot on the parent object where the child object should go. This\n            may be either the exact name of a bone on the parent object or a\n            slot type, in which case the first empty slot of the specified type\n            in which the child object fits will be used.\n            ', by_name=Tunable(description="\n                The exact name of a slot on the parent object in which the child\n                object should go.  No placement validation will be done on this\n                slot, as long as it is empty the child will always be placed\n                there.  This should only be used on slots the player isn't\n                allowed to use in build mode, as in the original design for the\n                service slots on the bar, or by GPEs testing out functionality\n                before modelers and designers have settled on slot types and\n                names for a particular design.\n                ", tunable_type=str, default='_ctnm_'), by_reference=TunableReference(description='\n                A particular slot type in which the child object should go.  The\n                first empty slot found on the parent of the specified type in\n                which the child object fits will be used.  If no such slot is\n                found, the parenting will not occur and the interaction will be\n                canceled.\n                ', manager=services.get_instance_manager(sims4.resources.Types.SLOT_TYPE))), '_child_object': TunableEnumEntry(description='\n            The participant of the interaction which will be parented to the\n            parent object.\n            ', tunable_type=ParticipantType, default=ParticipantType.CarriedObject)}

    def __init__(self, interaction, get_child_object_fn=None, **kwargs):
        super().__init__(interaction, **kwargs)
        _parent_object = kwargs['_parent_object']
        _parent_slot = kwargs['_parent_slot']
        _child_object = kwargs['_child_object']
        self._parent_object = interaction.get_participant(_parent_object)
        self.child_participant_type = _child_object
        if get_child_object_fn is None:
            self._child_participant_type = _child_object
        else:
            self._get_child_object = get_child_object_fn
        if isinstance(_parent_slot, str):
            self._slot_type = None
            self._bone_name_hash = sims4.hash_util.hash32(_parent_slot)
        else:
            self._slot_type = _parent_slot
            self._bone_name_hash = None

    def _get_child_object(self):
        return self.interaction.get_participant(self.child_participant_type)

    def _do_behavior(self):
        child_object = self._get_child_object()
        current_child_object_parent_slot = child_object.parent_slot
        if self._slot_type is not None:
            for runtime_slot in self._parent_object.get_runtime_slots_gen(slot_types={self._slot_type}, bone_name_hash=self._bone_name_hash):
                if runtime_slot == current_child_object_parent_slot:
                    return True
                result = runtime_slot.is_valid_for_placement(obj=child_object)
                if result:
                    runtime_slot.add_child(child_object)
                    return True
                logger.warn("runtime_slot isn't valid for placement: {}", result, owner='nbaker')
            logger.error('The parent object: ({}) does not have the requested slot type: ({}) required for this parenting, or the child ({}) is not valid for this slot type in {}.', self._parent_object, self._slot_type, child_object, self.interaction, owner='nbaker')
            return False
        if self._bone_name_hash is not None:
            if current_child_object_parent_slot is not None and current_child_object_parent_slot.slot_name_hash == self._bone_name_hash:
                return True
            runtime_slot = RuntimeSlot(self._parent_object, self._bone_name_hash, EMPTY_SET)
            if runtime_slot.empty:
                runtime_slot.add_child(child_object, joint_name_or_hash=self._bone_name_hash)
                return True
            logger.error('The parent object: ({}) does not have the requested slot type: ({}) required for this parenting, or the child ({}) is not valid for this slot type in {}.  Slot is empty: {}', self._parent_object, self._bone_name_hash, child_object, self.interaction, runtime_slot.empty, owner='nbaker')
            return False

class FadeChildrenElement(elements.ParentElement, HasTunableFactory):
    __qualname__ = 'FadeChildrenElement'
    FACTORY_TUNABLES = {'opacity': TunableRange(description='\n            The target opacity for the children.\n            ', tunable_type=float, default=0, minimum=0, maximum=1), '_parent_object': TunableEnumEntry(description='\n            The participant of an interaction whose children should be hidden.\n            ', tunable_type=ParticipantType, default=ParticipantType.Object), 'fade_duration': OptionalTunable(TunableRealSecond(description='\n                The number of seconds it should take for objects to fade out and\n                in.\n                ', default=0.25), disabled_name='use_default_fade_duration', enabled_name='use_custom_fade_duration'), 'fade_objects_on_ground': Tunable(description='\n            If checked, objects at height zero will fade. By default, objects \n            at ground level (like stools slotted into counters) will not fade.\n            ', tunable_type=bool, default=False)}

    def __init__(self, interaction, *, opacity, _parent_object, fade_duration, fade_objects_on_ground, sequence=()):
        super().__init__()
        self.interaction = interaction
        self.opacity = opacity
        self.parent_object = interaction.get_participant(_parent_object)
        if fade_duration is None:
            self.fade_duration = ClientObjectMixin.FADE_DURATION
        else:
            self.fade_duration = fade_duration
        self.fade_objects_on_ground = fade_objects_on_ground
        self.sequence = sequence
        self.hidden_objects = weakref.WeakKeyDictionary()

    def _run(self, timeline):

        def begin(_):
            for obj in self.parent_object.children_recursive_gen():
                if self.fade_objects_on_ground or obj.position.y == self.parent_object.position.y:
                    pass
                opacity = obj.opacity
                self.hidden_objects[obj] = opacity
                obj.fade_opacity(self.opacity, self.fade_duration)

        def end(_):
            for (obj, opacity) in self.hidden_objects.items():
                obj.fade_opacity(opacity, self.fade_duration)

        return timeline.run_child(build_critical_section_with_finally(begin, self.sequence, end))

class SetVisibilityStateElement(XevtTriggeredElement):
    __qualname__ = 'SetVisibilityStateElement'
    FACTORY_TUNABLES = {'subject': TunableEnumEntry(description='\n            The participant of this interaction that will change the visibility.\n            ', tunable_type=ParticipantType, default=ParticipantType.Actor), 'visibility': Tunable(description='\n            If checked, the subject will become visible. If unchecked, the\n            subject will become invisible.\n            ', tunable_type=bool, default=True), 'fade': Tunable(description='\n            If checked, the subject will fade in or fade out to match the\n            desired visibility.\n            ', tunable_type=bool, default=False)}

    def _do_behavior(self, *args, **kwargs):
        subject = self.interaction.get_participant(self.subject)
        if subject is not None:
            if self.fade:
                if self.visibility:
                    subject.fade_in()
                else:
                    subject.fade_out()
                    subject.visibility = VisibilityState(self.visibility)
            else:
                subject.visibility = VisibilityState(self.visibility)

class UpdatePhysique(XevtTriggeredElement, HasTunableFactory, AutoFactoryInit):
    __qualname__ = 'UpdatePhysique'
    FACTORY_TUNABLES = {'description': "\n            Basic extra to trigger a visual update of the specified Sims'\n            physiques.\n            ", 'targets': TunableEnumEntry(description='\n            The targets of this physique update.\n            ', tunable_type=ParticipantType, default=ParticipantType.Actor)}

    def _do_behavior(self):
        targets = self.interaction.get_participants(self.targets)
        for target in targets:
            target.sim_info.update_fitness_state()

