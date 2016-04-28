from event_testing.resolver import DoubleSimResolver
from server.permissions import SimPermissions
from sims4.localization import TunableLocalizedString
from sims4.resources import CompoundTypes
from sims4.tuning.dynamic_enum import DynamicEnum, DynamicEnumLocked, validate_locked_enum_id
from sims4.tuning.instances import HashedTunedInstanceMetaclass
from sims4.tuning.tunable import TunableResourceKey, Tunable, TunableList, TunableEnumEntry, TunableReference, TunableTuple, OptionalTunable, TunableSimMinute, HasTunableReference, TunableRange, TunableThreshold
from sims4.tuning.tunable_base import ExportModes
from ui.ui_dialog_notification import TunableUiDialogNotificationSnippet
import buffs.tunable
import services
import sims.sim_info_types
import sims4.log
import sims4.resources
import sims4.utils
logger = sims4.log.Logger('Relationship', default_owner='rez')

class RelationshipBitType(DynamicEnum):
    __qualname__ = 'RelationshipBitType'
    Invalid = 0
    NoGroup = 1

class RelationshipBitCollectionUid(DynamicEnumLocked, display_sorted=True):
    __qualname__ = 'RelationshipBitCollectionUid'
    Invalid = 0
    All = 1

class RelationshipBit(HasTunableReference, metaclass=HashedTunedInstanceMetaclass, manager=services.relationship_bit_manager()):
    __qualname__ = 'RelationshipBit'
    INSTANCE_TUNABLES = {'display_name': TunableLocalizedString(description='\n            Localized name of this bit\n            ', export_modes=ExportModes.All), 'bit_description': TunableLocalizedString(description='\n            Localized description of this bit\n            ', export_modes=ExportModes.All), 'icon': TunableResourceKey(description='\n            Icon to be displayed for the relationship bit.\n            ', default='PNG:missing_image', resource_types=CompoundTypes.IMAGE, export_modes=ExportModes.All), 'bit_added_notification': OptionalTunable(description='\n            If enabled, a notification will be displayed when this bit is added.\n            ', tunable=TunableUiDialogNotificationSnippet()), 'bit_removed_notification': OptionalTunable(description='\n            If enabled, a notification will be displayed when this bit is removed.\n            ', tunable=TunableUiDialogNotificationSnippet()), 'depth': Tunable(description='\n            The amount of depth provided by the bit.\n            ', tunable_type=int, default=0), 'priority': Tunable(description='\n            Priority of the bit.  This is used when a bit turns on while a\n            mutually exclusive bit is already on.\n            ', tunable_type=float, default=0), 'display_priority': Tunable(description='\n            The priority of this bit with regards to UI.  Only the highest\n            priority bits are displayed.\n            ', tunable_type=int, default=0, export_modes=ExportModes.All), 'visible': Tunable(description="\n            If True, this bit has the potential to be visible when applied,\n            depending on display_priority and the other active bits.  If False,\n            the bit will not be displayed unless it's part of the\n            REL_INSPECTOR_TRACK bit track.\n            ", tunable_type=bool, default=True), 'group_id': TunableEnumEntry(description='\n            The group this bit belongs to.  Two bits of the same group cannot\n            belong in the same set of bits for a given relationship.\n            ', tunable_type=RelationshipBitType, default=RelationshipBitType.NoGroup), 'triggered_track': TunableReference(description='\n            If set, the track that is triggered when this bit is set\n            ', manager=services.statistic_manager(), class_restrictions='RelationshipTrack'), 'required_bits': TunableList(description='\n            List of all bits that are required to be on in order to allow this\n            bit to turn on.\n            ', tunable=TunableReference(services.relationship_bit_manager())), 'timeout': TunableSimMinute(description='\n            The length of time this bit will last in sim minutes.  0 means the\n            bit will never timeout.\n            ', default=0), 'remove_on_threshold': OptionalTunable(tunable=TunableTuple(description='\n                If enabled, this bit will be removed when the referenced track\n                reaches the appropriate threshold.\n                ', track=TunableReference(description='\n                    The track to be tested.\n                    ', manager=services.statistic_manager(), class_restrictions='RelationshipTrack'), threshold=TunableThreshold(description='\n                    The threshold at which to remove this bit.\n                    '))), 'historical_bits': OptionalTunable(tunable=TunableList(tunable=TunableTuple(age_trans_from=TunableEnumEntry(description='\n                        Age we are transitioning out of.\n                        ', tunable_type=sims.sim_info_types.Age, default=sims.sim_info_types.Age.CHILD), new_historical_bit=TunableReference(description='\n                        New historical bit the sim obtains\n                        ', manager=services.get_instance_manager(sims4.resources.Types.RELATIONSHIP_BIT))))), 'collection_ids': TunableList(tunable=TunableEnumEntry(description='\n                The bit collection id this bit belongs to, like family,\n                friends, romance. Default to be All.\n                ', tunable_type=RelationshipBitCollectionUid, default=RelationshipBitCollectionUid.All, export_modes=ExportModes.All)), 'buffs_on_add_bit': TunableList(tunable=TunableTuple(buff_ref=buffs.tunable.TunableBuffReference(description='\n                    Buff that gets added to sim when bit is added.\n                    '), amount=Tunable(description='\n                    If buff is tied to commodity the amount to add to the\n                    commodity.\n                    ', tunable_type=float, default=1), only_add_once=Tunable(description='\n                    If True, the buff should only get added once no matter how\n                    many times this bit is being applied.\n                    ', tunable_type=bool, default=False))), 'buffs_to_add_if_on_active_lot': TunableList(description="\n            List of buffs to add when a sim that I share this relationship with\n            is in the household that owns the lot that I'm on.\n            ", tunable=buffs.tunable.TunableBuffReference(description='\n                Buff that gets added to sim when bit is added.\n                ')), 'permission_requirements': TunableList(tunable=TunableTuple(permission=TunableEnumEntry(description='\n                    The Sim Permission to test to allow setting of the\n                    relationship bit.\n                    ', tunable_type=SimPermissions.Settings, default=SimPermissions.Settings.VisitationAllowed), required_enabled=Tunable(description='\n                    If True, the chosen Sim Permission must be enabled for\n                    relationship bit to be set.  If False, the permission must\n                    be disabled.\n                    ', tunable_type=bool, default=True))), 'autonomy_multiplier': Tunable(description='\n            This value is multiplied to the autonomy score of any interaction\n            performed between the two Sims.  For example, when the Sim decides\n            to socialize, she will start looking at targets to socialize with.\n            If there is a Sim who she shares this bit with, her final score for\n            socializing with that Sim will be multiplied by this value.\n            ', tunable_type=float, default=1), 'prevents_relationship_culling': Tunable(description='\n            If checked, any relationship with this bit applied will never be\n            culled.\n            ', tunable_type=bool, default=False), 'persisted_tuning': Tunable(description='\n            Whether this bit will persist when saving a Sim. \n            \n            For example, a Sims is good_friends should be set to true, but\n            romantic_gettingMarried should not be saved.\n            ', tunable_type=bool, default=True)}
    is_track_bit = False
    is_rel_bit = True
    track_min_score = 0
    track_max_score = 0
    track_mean_score = 0
    trait_replacement_bits = None

    @sims4.utils.classproperty
    def persisted(cls):
        return cls.persisted_tuning

    def __init__(self):
        self._buff_handles = []
        self._conditional_removal_listener = None
        self._appropriate_buffs_handles = []

    def on_add_to_relationship(self, sim, target_sim_info, relationship):
        for buff_data in self.buffs_on_add_bit:
            buff_type = buff_data.buff_ref.buff_type
            if buff_data.only_add_once:
                if buff_type.guid64 in relationship.bit_added_buffs[buff_type.guid64]:
                    pass
                else:
                    relationship.bit_added_buffs[buff_type.guid64].append(buff_type.guid64)
            if buff_type.commodity:
                tracker = sim.get_tracker(buff_type.commodity)
                tracker.add_value(buff_type.commodity, buff_data.amount)
                sim.set_buff_reason(buff_type, buff_data.buff_ref.buff_reason)
            else:
                buff_handle = sim.add_buff(buff_type, buff_reason=buff_data.buff_ref.buff_reason)
                self._buff_handles.append(buff_handle)
        if self.bit_added_notification is not None and sim.is_selectable:
            target_sim = target_sim_info.get_sim_instance()
            if not target_sim or not target_sim.is_selectable:
                self._show_bit_added_dialog(sim, target_sim_info)
            elif not target_sim_info.relationship_tracker.has_bit(sim.id, type(self)):
                self._show_bit_added_dialog(sim, target_sim_info)

    def on_remove_from_relationship(self, sim, target_sim_info):
        for buff_handle in self._buff_handles:
            sim.remove_buff(buff_handle)
        if self.bit_removed_notification is not None and sim.is_selectable:
            target_sim = target_sim_info.get_sim_instance()
            if not target_sim or not target_sim.is_selectable:
                self._show_bit_removed_dialog(sim, target_sim_info)
            elif not target_sim_info.relationship_tracker.has_bit(sim.id, type(self)):
                self._show_bit_removed_dialog(sim, target_sim_info)

    def add_appropriateness_buffs(self, sim_info):
        if not self._appropriate_buffs_handles:
            for buff in self.buffs_to_add_if_on_active_lot:
                handle = sim_info.add_buff(buff.buff_type, buff_reason=buff.buff_reason)
                self._appropriate_buffs_handles.append(handle)

    def remove_appropriateness_buffs(self, sim_info):
        for buff in self._appropriate_buffs_handles:
            sim_info.remove_buff(buff)
        self._appropriate_buffs_handles.clear()

    def add_conditional_removal_listener(self, listener):
        if self._conditional_removal_listener is not None:
            logger.error('Attempting to add a conditional removal listener when one already exists; old one will be overwritten.', owner='rez')
        self._conditional_removal_listener = listener

    def remove_conditional_removal_listener(self):
        listener = self._conditional_removal_listener
        self._conditional_removal_listener = None
        return listener

    def __repr__(self):
        return '<({}) Type: {}.{}>'.format(self.__name__, self.__mro__[1].__module__, self.__mro__[1].__name__)

    @classmethod
    def _cls_repr(cls):
        return '<({}) Type: {}.{}>'.format(cls.__name__, cls.__mro__[1].__module__, cls.__mro__[1].__name__)

    @classmethod
    def _verify_tuning_callback(cls):
        if cls.historical_bits is not None:
            for bit in cls.historical_bits:
                pass
        if cls.remove_on_threshold and cls.remove_on_threshold.track is None:
            logger.error('Tuning Error: Remove On Threshold was tuned without a corresponding relationship track.')

    def _show_bit_added_dialog(self, sim, target_sim_info):
        dialog = self.bit_added_notification(sim, DoubleSimResolver(sim, target_sim_info))
        dialog.show_dialog(additional_tokens=(sim, target_sim_info))

    def _show_bit_removed_dialog(self, sim, target_sim_info):
        dialog = self.bit_removed_notification(sim, DoubleSimResolver(sim, target_sim_info))
        dialog.show_dialog(additional_tokens=(sim, target_sim_info))

    @classmethod
    def matches_bit(cls, bit_type):
        return cls is bit_type

class SocialContextBit(RelationshipBit):
    __qualname__ = 'SocialContextBit'
    INSTANCE_TUNABLES = {'size_limit': OptionalTunable(description='\n            If enabled, this bit will only be available if the owner Sim is in a\n            social context with the specified number of Sims. If there are more\n            Sims than the specified limit, the bit will transform to another\n            form, i.e. to a different bit.\n            ', tunable=TunableTuple(size=TunableRange(description='\n                    The maximum number of Sims that can share a social context\n                    in order for this bit to be visible.\n                    ', tunable_type=int, default=2, minimum=0), transformation=RelationshipBit.TunableReference(description='\n                    The bit that is going to replace this bit if the size limit\n                    is violated.\n                    ', class_restrictions='SocialContextBit'))), 'attention_cost': Tunable(description='\n            Any Sim in this social context will add this amount to the attention\n            cost of any social super interaction they are running.\n            ', tunable_type=float, default=0)}

    def on_add_to_relationship(self, sim, target_sim_info, relationship):
        sim.on_social_context_changed()
        target_sim = target_sim_info.get_sim_instance()
        if target_sim is not None:
            target_sim.on_social_context_changed()
        return super().on_add_to_relationship(sim, target_sim_info, relationship)

    def on_remove_from_relationship(self, sim, target_sim_info):
        sim.on_social_context_changed()
        return super().on_remove_from_relationship(sim, target_sim_info)

class RelationshipBitCollection(metaclass=HashedTunedInstanceMetaclass, manager=services.relationship_bit_manager()):
    __qualname__ = 'RelationshipBitCollection'
    INSTANCE_TUNABLES = {'name': TunableLocalizedString(export_modes=ExportModes.All, description='Name to be displayed for the collection.'), 'icon': TunableResourceKey('PNG:missing_image', resource_types=CompoundTypes.IMAGE, export_modes=ExportModes.All, description='Icon to be displayed for the collection.'), 'collection_id': TunableEnumEntry(RelationshipBitCollectionUid, RelationshipBitCollectionUid.Invalid, export_modes=ExportModes.All, description='The unique id of the relationship bit')}
    is_rel_bit = False

    @classmethod
    def _verify_tuning_callback(cls):
        validate_locked_enum_id(RelationshipBitCollection, cls.collection_id, cls, RelationshipBitCollectionUid.Invalid)

    @classmethod
    def matches_bit(cls, bit_type):
        return cls.collection_id in bit_type.collection_ids

