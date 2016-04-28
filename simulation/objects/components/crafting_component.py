import operator
import random
from clock import interval_in_sim_minutes
from crafting.crafting_process import CraftingProcess, logger
from crafting.crafting_tunable import CraftingTuning
from event_testing import test_events
from objects.client_object_mixin import ClientObjectMixin
from objects.components import Component, componentmethod, types, componentmethod_with_fallback
from objects.components.tooltip_component import TooltipProvidingComponentMixin
from protocolbuffers import SimObjectAttributes_pb2 as protocols, UI_pb2 as ui_protocols
from sims4.callback_utils import CallableList
from singletons import DEFAULT
import services
import sims4.math
_set_recipe_name = ClientObjectMixin.ui_metadata.generic_setter('recipe_name')
_set_recipe_decription = ClientObjectMixin.ui_metadata.generic_setter('recipe_description')
_set_crafter_sim_id = ClientObjectMixin.ui_metadata.generic_setter('crafter_sim_id')
_set_crafted_by_text = ClientObjectMixin.ui_metadata.generic_setter('crafted_by_text')
_set_quality = ClientObjectMixin.ui_metadata.generic_setter('quality')
_set_servings = ClientObjectMixin.ui_metadata.generic_setter('servings')
_set_spoiled_time = ClientObjectMixin.ui_metadata.generic_setter('spoiled_time')
_set_percentage_left = ClientObjectMixin.ui_metadata.generic_setter('percentage_left')
_set_style_name = ClientObjectMixin.ui_metadata.generic_setter('style_name')
_set_simoleon_value = ClientObjectMixin.ui_metadata.generic_setter('simoleon_value')
_set_main_icon = ClientObjectMixin.ui_metadata.generic_setter('main_icon')
_set_sub_icons = ClientObjectMixin.ui_metadata.generic_setter('sub_icons')
_set_quality_description = ClientObjectMixin.ui_metadata.generic_setter('quality_description')
_set_inscription = ClientObjectMixin.ui_metadata.generic_setter('inscription')
_set_subtext = ClientObjectMixin.ui_metadata.generic_setter('subtext')

class CraftingComponent(Component, TooltipProvidingComponentMixin, component_name=types.CRAFTING_COMPONENT, persistence_key=protocols.PersistenceMaster.PersistableData.CraftingComponent, allow_dynamic=True):
    __qualname__ = 'CraftingComponent'

    def __init__(self, owner):
        super().__init__(owner)
        self._crafting_process = None
        self._use_base_recipe = False
        self.object_mutated_listeners = CallableList()
        self._servings_statistic_tracker_handle = None
        self._quality_change_callback_added = False
        self._spoil_listener_handle = None
        self._is_final_product = False

    @componentmethod_with_fallback(lambda : (DEFAULT, DEFAULT))
    def get_template_content_overrides(self):
        is_final_product = self._crafting_process.phase is None or self._crafting_process.phase.object_info_is_final_product
        if is_final_product or self.owner.name_component is None:
            return (DEFAULT, DEFAULT)
        name_component = self._crafting_process.recipe.final_product_definition.cls.tuned_components['name']
        if name_component is not None and name_component.templates:
            selected_template = random.choice(name_component.templates)
            return (selected_template.template_name, selected_template.template_description)
        return (DEFAULT, DEFAULT)

    def on_add(self, *_, **__):
        tracker = self.owner.get_tracker(CraftingTuning.SERVINGS_STATISTIC)
        self._servings_statistic_tracker_handle = tracker.add_watcher(self._on_servings_change)
        if self.owner.state_component is not None:
            self.owner.add_state_changed_callback(self._on_object_state_change)
            self._quality_change_callback_added = True
            consumable_state_value = self.owner.get_state_value_from_stat_type(CraftingTuning.CONSUME_STATISTIC)
            if consumable_state_value is not None:
                self._on_object_state_change(self.owner, consumable_state_value.state, consumable_state_value, consumable_state_value)
            quality_state_value = self.owner.get_state_value_from_stat_type(CraftingTuning.QUALITY_STATISTIC)
            if quality_state_value is not None:
                self._on_object_state_change(self.owner, quality_state_value.state, quality_state_value, quality_state_value)

    def on_remove(self, *_, **__):
        if self._servings_statistic_tracker_handle is not None:
            tracker = self.owner.get_tracker(CraftingTuning.SERVINGS_STATISTIC)
            tracker.remove_watcher(self._servings_statistic_tracker_handle)
            self._servings_statistic_tracker_handle = None
        if self._quality_change_callback_added:
            self.owner.remove_state_changed_callback(self._on_object_state_change)
            self._quality_change_callback_added = False
        if self._spoil_listener_handle is not None:
            spoil_tracker = self.owner.get_tracker(CraftingTuning.SPOILED_STATE_VALUE.state.linked_stat)
            spoil_tracker.remove_listener(self._spoil_listener_handle)
        self._remove_hovertip()

    def on_mutated(self):
        self.object_mutated_listeners()
        self.owner.remove_component(types.CRAFTING_COMPONENT.instance_attr)

    @property
    def crafter_sim_id(self):
        if self._crafting_process.crafter_sim_id:
            return self._crafting_process.crafter_sim_id
        return 0

    def _on_servings_change(self, stat_type, old_value, new_value):
        if stat_type is CraftingTuning.SERVINGS_STATISTIC:
            owner = self.owner
            _set_servings(owner, max(int(new_value), 0))
            current_inventory = owner.get_inventory()
            if current_inventory is not None:
                current_inventory.push_inventory_item_update_msg(owner)
            if new_value <= 0:
                self.on_mutated()

    def _on_object_state_change(self, owner, state, old_value, new_value):
        state_value = None
        if state is CraftingTuning.QUALITY_STATE:
            state_value = new_value
        elif state is CraftingTuning.FRESHNESS_STATE:
            if new_value in CraftingTuning.QUALITY_STATE_VALUE_MAP:
                state_value = new_value
            else:
                _set_quality_description(self.owner, None)
                if self.owner.has_state(CraftingTuning.QUALITY_STATE):
                    state_value = self.owner.get_state(CraftingTuning.QUALITY_STATE)
        if state_value is not None:
            value_quality = CraftingTuning.QUALITY_STATE_VALUE_MAP.get(state_value)
            if value_quality is not None:
                if state_value is CraftingTuning.SPOILED_STATE_VALUE:
                    _set_quality_description(self.owner, CraftingTuning.SPOILED_STRING)
                else:
                    _set_quality(self.owner, value_quality.state_star_number)
                    _set_quality_description(owner, None)
        if owner.has_state(CraftingTuning.MASTERWORK_STATE) and owner.get_state(CraftingTuning.MASTERWORK_STATE) is CraftingTuning.MASTERWORK_STATE_VALUE:
            if self._crafting_process is not None:
                recipe = self._get_recipe()
                _set_quality_description(owner, recipe.masterwork_name)
        elif state is CraftingTuning.CONSUMABLE_STATE:
            value_consumable = CraftingTuning.CONSUMABLE_STATE_VALUE_MAP.get(new_value)
            if value_consumable is not None:
                _set_percentage_left(self.owner, value_consumable)
        if new_value is CraftingTuning.CONSUMABLE_EMPTY_STATE_VALUE and old_value is not CraftingTuning.CONSUMABLE_EMPTY_STATE_VALUE:
            self._remove_hovertip()
        if new_value is CraftingTuning.LOCK_FRESHNESS_STATE_VALUE:
            _set_spoiled_time(self.owner, 0)
            if self._spoil_listener_handle is not None:
                spoil_tracker = self.owner.get_tracker(CraftingTuning.SPOILED_STATE_VALUE.state.linked_stat)
                spoil_tracker.remove_listener(self._spoil_listener_handle)
                self._spoil_listener_handle = None

    def _add_hovertip(self):
        if self._is_final_product and self._is_finished():
            self._add_consumable_hovertip()
        else:
            self._add_ico_hovertip()

    def _is_finished(self):
        crafting_process = self._crafting_process
        tracker = None
        stat = CraftingTuning.PROGRESS_STATISTIC
        if crafting_process.current_ico is not None:
            tracker = crafting_process.current_ico.get_tracker(stat)
        if tracker is None:
            tracker = self.owner.get_tracker(stat)
        if tracker is None or not tracker.has_statistic(stat):
            tracker = crafting_process.get_tracker(stat)
        if tracker.has_statistic(stat) and tracker.get_value(stat) != stat.max_value:
            return crafting_process.is_complete
        return True

    def _get_recipe(self):
        recipe = self._crafting_process.recipe
        if self._use_base_recipe:
            recipe = recipe.get_base_recipe()
        return recipe

    def _add_consumable_hovertip(self):
        owner = self.owner
        owner.hover_tip = ui_protocols.UiObjectMetadata.HOVER_TIP_CONSUMABLE_CRAFTABLE
        crafting_process = self._crafting_process
        recipe = self._get_recipe()
        _set_recipe_name(owner, recipe.get_recipe_name(crafting_process.crafter))
        crafter_sim_id = crafting_process.crafter_sim_id
        if crafter_sim_id is not None:
            _set_crafter_sim_id(owner, crafter_sim_id)
        crafted_by_text = crafting_process.get_crafted_by_text()
        if crafted_by_text is not None:
            _set_crafted_by_text(owner, crafted_by_text)
        if owner.has_state(CraftingTuning.QUALITY_STATE):
            value_quality = CraftingTuning.QUALITY_STATE_VALUE_MAP.get(owner.get_state(CraftingTuning.QUALITY_STATE))
            if value_quality is not None:
                _set_quality(self.owner, value_quality.state_star_number)
        if owner.has_state(CraftingTuning.MASTERWORK_STATE) and owner.get_state(CraftingTuning.MASTERWORK_STATE) is CraftingTuning.MASTERWORK_STATE_VALUE:
            _set_quality_description(owner, recipe.masterwork_name)
        inscription = crafting_process.inscription
        if inscription is not None:
            _set_inscription(owner, inscription)
        self._add_spoil_listener()
        subtext = self.owner.get_state_strings()
        if subtext is not None:
            _set_subtext(owner, subtext)
        recipe.update_hovertip(self.owner, crafter=crafting_process.crafter)
        current_inventory = owner.get_inventory()
        if current_inventory is not None:
            current_inventory.push_inventory_item_update_msg(owner)

    def _add_ico_hovertip(self):
        pass

    def _remove_hovertip(self):
        owner = self.owner
        owner.hover_tip = ui_protocols.UiObjectMetadata.HOVER_TIP_DISABLED
        _set_recipe_name(owner, None)
        _set_recipe_decription(owner, None)
        _set_crafter_sim_id(owner, 0)
        _set_crafted_by_text(owner, None)
        _set_quality(owner, 0)
        _set_servings(owner, 0)
        _set_spoiled_time(owner, 0)
        _set_percentage_left(owner, None)
        _set_style_name(owner, None)
        _set_simoleon_value(owner, owner.current_value)
        _set_main_icon(owner, None)
        _set_sub_icons(owner, None)
        _set_quality_description(owner, None)
        _set_subtext(owner, None)

    def _on_spoil_time_changed(self, state, spoiled_time):
        if spoiled_time is not None:
            time_in_ticks = spoiled_time.absolute_ticks()
            _set_spoiled_time(self.owner, time_in_ticks)
            logger.debug('{} will get spoiled at {}', self.owner, spoiled_time)

    def _on_spoiled(self, _):
        pass

    def _add_spoil_listener(self):
        if self.owner.has_state(CraftingTuning.SPOILED_STATE_VALUE.state):
            linked_stat = CraftingTuning.SPOILED_STATE_VALUE.state.linked_stat
            tracker = self.owner.get_tracker(linked_stat)
            if tracker is None:
                return
            threshold = sims4.math.Threshold()
            threshold.value = CraftingTuning.SPOILED_STATE_VALUE.range.upper_bound
            threshold.comparison = operator.lt
            self._spoil_listener_handle = tracker.create_and_activate_listener(linked_stat, threshold, self._on_spoiled, on_callback_alarm_reset=self._on_spoil_time_changed)

    def _on_crafting_process_updated(self):
        self._add_hovertip()
        self.owner.update_commodity_flags()

    @componentmethod
    def set_crafting_process(self, crafting_process, use_base_recipe=False, is_final_product=False):
        self._crafting_process = crafting_process
        self._use_base_recipe = use_base_recipe
        self._is_final_product = is_final_product
        self._on_crafting_process_updated()

    @componentmethod
    def get_crafting_process(self):
        return self._crafting_process

    @componentmethod
    def on_crafting_process_finished(self):
        self._add_hovertip()
        self.owner.update_commodity_flags()
        crafting_process = self._crafting_process
        if crafting_process is None:
            return
        recipe = crafting_process.recipe
        if self._use_base_recipe:
            recipe = recipe.get_base_recipe()
        skill_test = recipe.skill_test
        if crafting_process.crafter_sim_id is None:
            return
        sim_info = services.sim_info_manager().get(crafting_process.crafter_sim_id)
        created_object_quality = self.owner.get_state(CraftingTuning.QUALITY_STATE) if self.owner.has_state(CraftingTuning.QUALITY_STATE) else None
        created_object_masterwork = self.owner.get_state(CraftingTuning.MASTERWORK_STATE) if self.owner.has_state(CraftingTuning.MASTERWORK_STATE) else None
        services.get_event_manager().process_event(test_events.TestEvent.ItemCrafted, sim_info=sim_info, crafted_object=self.owner, skill=skill_test.skill if skill_test is not None else None, quality=created_object_quality, masterwork=created_object_masterwork)

    @componentmethod
    def get_recipe(self):
        return self._crafting_process.recipe

    @componentmethod
    def get_consume_affordance(self):
        if self._is_final_product:
            consumable_component = self.owner.consumable_component
            if consumable_component is not None:
                consume_affordance = consumable_component.consume_affordance
                if consume_affordance is not None:
                    return consume_affordance
            for affordance in self.owner.super_affordances():
                from crafting.crafting_interactions import GrabServingSuperInteraction
                while issubclass(affordance, GrabServingSuperInteraction):
                    return affordance

    def component_super_affordances_gen(self, **kwargs):
        recipe = self.get_recipe()
        if self._use_base_recipe:
            recipe = recipe.get_base_recipe()
        if self._crafting_process.is_complete:
            for sa in recipe.final_product.super_affordances:
                yield sa
        if recipe.resume_affordance:
            yield recipe.resume_affordance
        else:
            yield CraftingTuning.DEFAULT_RESUME_AFFORDANCE

    def component_interactable_gen(self):
        yield self

    def on_client_connect(self, client):
        self._add_hovertip()

    @componentmethod_with_fallback(lambda : False)
    def has_servings_statistic(self):
        tracker = self.owner.get_tracker(CraftingTuning.SERVINGS_STATISTIC)
        if tracker is None or not tracker.has_statistic(CraftingTuning.SERVINGS_STATISTIC):
            return False
        return True

    def save(self, persistence_master_message):
        logger.info('[PERSISTENCE]: ----Start saving crafting component of {0}.', self.owner)
        persistable_data = protocols.PersistenceMaster.PersistableData()
        persistable_data.type = protocols.PersistenceMaster.PersistableData.CraftingComponent
        crafting_save = persistable_data.Extensions[protocols.PersistableCraftingComponent.persistable_data]
        self._crafting_process.save(crafting_save.process)
        crafting_save.use_base_recipe = self._use_base_recipe
        crafting_save.is_final_product = self._is_final_product
        persistence_master_message.data.extend([persistable_data])

    def load(self, crafting_save_message):
        logger.info('[PERSISTENCE]: ----Start loading crafting component of {0}.', self.owner)
        crafting_component_data = crafting_save_message.Extensions[protocols.PersistableCraftingComponent.persistable_data]
        crafting_process = CraftingProcess()
        crafting_process.load(crafting_component_data.process)
        self.set_crafting_process(crafting_process, crafting_component_data.use_base_recipe, crafting_component_data.is_final_product)
        if crafting_process.crafted_value is not None:
            self.owner.state_component.reapply_value_changes()

