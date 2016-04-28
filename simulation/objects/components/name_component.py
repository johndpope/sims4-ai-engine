import random
from protocolbuffers import SimObjectAttributes_pb2 as protocols
from interactions import ParticipantType
from interactions.utils.interaction_elements import XevtTriggeredElement
from objects.client_object_mixin import ClientObjectMixin
from objects.components import Component, types, componentmethod, componentmethod_with_fallback
from sims4.localization import TunableLocalizedStringFactory, LocalizationHelperTuning
from sims4.tuning.tunable import HasTunableFactory, Tunable, TunableReference, OptionalTunable, TunableList, TunableTuple, AutoFactoryInit, TunableEnumEntry
from singletons import DEFAULT
import services
import sims4.callback_utils
import sims4.log
logger = sims4.log.Logger('NameComponent')
_set_recipe_name = ClientObjectMixin.ui_metadata.generic_setter('recipe_name')
_set_recipe_decription = ClientObjectMixin.ui_metadata.generic_setter('recipe_description')

class NameComponent(Component, HasTunableFactory, component_name=types.NAME_COMPONENT, persistence_key=protocols.PersistenceMaster.PersistableData.NameComponent):
    __qualname__ = 'NameComponent'
    DEFAULT_AFFORDANCE = TunableReference(services.affordance_manager(), description='The affordance generated by all NameComponents.')
    FACTORY_TUNABLES = {'allow_name': Tunable(description='\n            If set, the user is allowed to give a custom name to this\n            object.\n            ', tunable_type=bool, default=True), 'allow_description': Tunable(description='\n            If set, the user is allowed to give a custom description to this\n            object.\n            ', tunable_type=bool, default=False), 'affordance': OptionalTunable(tunable=TunableReference(description='\n                The affordance provided by this Name component. Use it if you want\n                to provide a custom affordance instead of the default one, which\n                will not be used if this is set.\n                ', manager=services.affordance_manager()), disabled_name='use_default'), 'templates': TunableList(description='\n            The list of the template content for this component.\n            ', tunable=TunableTuple(template_name=TunableLocalizedStringFactory(description='\n                    The template name for the component.\n                    '), template_description=TunableLocalizedStringFactory(description='\n                    The template description for the component.\n                    ')))}

    def __init__(self, *args, allow_name=None, allow_description=None, affordance=None, templates=[], **kwargs):
        super().__init__(*args, **kwargs)
        self.allow_name = allow_name
        self.allow_description = allow_description
        self._affordance = affordance
        self._templates = templates
        self._template_name = None
        self._template_description = None
        self._on_name_changed = None

    def get_template_name_and_description(self):
        if self._template_name is None or self._template_description is None:
            self._set_template_content()
        (template_name, template_description) = self.owner.get_template_content_overrides()
        template_name = template_name if template_name is not DEFAULT else self._template_name
        template_description = template_description if template_description is not DEFAULT else self._template_description
        return (template_name, template_description)

    def _set_template_content(self):
        if self._templates:
            selected_template = random.choice(self._templates)
            self._template_name = selected_template.template_name
            self._template_description = selected_template.template_description

    def save(self, persistence_master_message):
        if self.owner.custom_name is None and self.owner.custom_description is None:
            return
        persistable_data = protocols.PersistenceMaster.PersistableData()
        persistable_data.type = protocols.PersistenceMaster.PersistableData.NameComponent
        name_component_data = persistable_data.Extensions[protocols.PersistableNameComponent.persistable_data]
        if self.owner.custom_name is not None:
            name_component_data.name = self.owner.custom_name
        if self.owner.custom_description is not None:
            name_component_data.description = self.owner.custom_description
        persistence_master_message.data.extend([persistable_data])

    def load(self, persistable_data):
        name_component_data = persistable_data.Extensions[protocols.PersistableNameComponent.persistable_data]
        if name_component_data.HasField('name'):
            self.owner.custom_name = name_component_data.name
        if name_component_data.HasField('description'):
            self.owner.custom_description = name_component_data.description

    @componentmethod_with_fallback(lambda : False)
    def has_custom_name(self):
        if self.owner.custom_name:
            return True
        return False

    @componentmethod_with_fallback(lambda : False)
    def has_custom_description(self):
        if self.owner.custom_description:
            return True
        return False

    @componentmethod
    def set_custom_name(self, name):
        if self.allow_name:
            self.owner.custom_name = name if name else None
            self._call_name_changed_callback()
            if self.owner.update_object_tooltip() is None and isinstance(self.owner, ClientObjectMixin):
                _set_recipe_name(self.owner, LocalizationHelperTuning.get_raw_text(name))
            return True
        return False

    @componentmethod
    def set_custom_description(self, description):
        if self.allow_description:
            self.owner.custom_description = description if description else None
            self._call_name_changed_callback()
            if self.owner.update_object_tooltip() is None and isinstance(self.owner, ClientObjectMixin):
                _set_recipe_decription(self.owner, LocalizationHelperTuning.get_raw_text(description))
            return True
        return False

    @componentmethod
    def add_name_changed_callback(self, callback):
        if self._on_name_changed is None:
            self._on_name_changed = sims4.callback_utils.CallableList()
        self._on_name_changed.append(callback)

    @componentmethod
    def remove_name_changed_callback(self, callback):
        if callback in self._on_name_changed:
            self._on_name_changed.remove(callback)
            if not self._on_name_changed:
                self._on_name_changed = None

    def _call_name_changed_callback(self):
        if self._on_name_changed is not None:
            self._on_name_changed()

    def component_super_affordances_gen(self, **kwargs):
        yield self._affordance or self.DEFAULT_AFFORDANCE

    def component_interactable_gen(self):
        yield self

    def populate_localization_token(self, token):
        if self.owner.custom_name is not None:
            token.custom_name = self.owner.custom_name
        if self.owner.custom_description is not None:
            token.custom_description = self.owner.custom_description

class NameTransfer(XevtTriggeredElement, HasTunableFactory, AutoFactoryInit):
    __qualname__ = 'NameTransfer'
    FACTORY_TUNABLES = {'description': 'Transfer name between two participants at the beginning/end of an interaction or on XEvent.', 'participant_sending_name': TunableEnumEntry(description='\n            The participant who has the name that is being transferred.\n            ', tunable_type=ParticipantType, default=ParticipantType.Actor), 'participant_receiving_name': TunableEnumEntry(description='\n            The participant who is receiving the name being transferred.\n            ', tunable_type=ParticipantType, default=ParticipantType.Object), 'transfer_description': Tunable(description='\n            If checked, the description will also be transferred along with the name.\n            ', tunable_type=bool, default=True)}

    def _do_behavior(self):
        sender = self.interaction.get_participant(self.participant_sending_name)
        receiver = self.interaction.get_participant(self.participant_receiving_name)
        if sender is None or receiver is None:
            logger.error('Cannot transfer name between None participants. Sender: {}, Receiver: {}, Interaction: {}'.format(sender, receiver, self.interaction), owner='rmccord')
            return
        sender_name_component = sender.name_component
        receiver_name_component = receiver.name_component
        if receiver_name_component is None:
            logger.error('Receiver of Name Transfer does not have a Name Component. Receiver: {}, Interaction: {}'.format(sender, receiver, self.interaction), owner='rmccord')
            return
        if sender_name_component.has_custom_name():
            receiver_name_component.set_custom_name(sender.custom_name)
        if self.transfer_description and sender_name_component.has_custom_description():
            receiver_name_component.set_custom_description(sender.custom_description)

