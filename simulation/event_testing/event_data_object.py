from date_and_time import TimeSpan, DateAndTime
from interactions.utils.outcome_enums import OutcomeResult
import enum
import event_testing.event_data_const as data_const
import event_testing.test_events as test_events
import services
import sims4.log
logger = sims4.log.Logger('Event Data Object')

class EventDataObject:
    __qualname__ = 'EventDataObject'

    def __init__(self):
        self._data = {}
        self._data[data_const.DataType.ObjectiveCount] = ObjectiveCountData()
        self._data[data_const.DataType.RelationshipData] = RelationshipData()
        self._data[data_const.DataType.SimoleanData] = SimoleonData()
        self._data[data_const.DataType.TimeData] = TimeData()
        self._data[data_const.DataType.TravelData] = TravelData()
        self._data[data_const.DataType.BuffData] = BuffData()
        self._data[data_const.DataType.CareerData] = CareerData()
        self._data[data_const.DataType.TagData] = TagData()
        self._data[data_const.DataType.RelativeStartingData] = RelativeStartingData()

    @property
    def data(self):
        return self._data

    def increment_objective_count(self, objective_uid):
        self._data[data_const.DataType.ObjectiveCount].increment_objective_count(objective_uid)

    def add_objective_id(self, objective_uid, id_to_add):
        self._data[data_const.DataType.ObjectiveCount].add_id(objective_uid, id_to_add)

    def set_objective_complete(self, objective_uid):
        self._data[data_const.DataType.ObjectiveCount].set_objective_complete(objective_uid)

    def get_objective_count(self, objective_uid):
        return self._data[data_const.DataType.ObjectiveCount].get_objective_count(objective_uid)

    def get_objective_count_data(self):
        return self._data[data_const.DataType.ObjectiveCount].get_data()

    def set_starting_values(self, obj_guid64, values):
        self._data[data_const.DataType.RelativeStartingData].set_starting_values(obj_guid64, values)

    def get_starting_values(self, obj_guid64):
        return self._data[data_const.DataType.RelativeStartingData].get_starting_values(obj_guid64)

    def reset_objective_count(self, objective_uid):
        self._data[data_const.DataType.ObjectiveCount].reset_objective_count(objective_uid)

    def add_time_data(self, time_type, time_add):
        self._data[data_const.DataType.TimeData].add_time_data(time_type, time_add)

    def get_time_data(self, time_type):
        return self._data[data_const.DataType.TimeData].get_time_data(time_type)

    @test_events.DataMapHandler(test_events.TestEvent.SimTravel)
    def add_zone_traveled(self, zone_id=None, **kwargs):
        self._data[data_const.DataType.TravelData].add_travel_data(zone_id)

    def get_zones_traveled(self):
        return self._data[data_const.DataType.TravelData].get_travel_amount()

    @test_events.DataMapHandler(test_events.TestEvent.AddRelationshipBit)
    def add_relationship_bit_event(self, relationship_bit=None, sim_id=None, target_sim_id=None, **kwargs):
        self._data[data_const.DataType.RelationshipData].add_relationship_bit(relationship_bit, sim_id, target_sim_id)

    @test_events.DataMapHandler(test_events.TestEvent.RemoveRelationshipBit)
    def remove_relationship_bit_event(self, relationship_bit=None, sim_id=None, target_sim_id=None, **kwargs):
        self._data[data_const.DataType.RelationshipData].remove_relationship_bit(relationship_bit, sim_id, target_sim_id)

    def get_total_relationships(self, relationship_bit):
        return self._data[data_const.DataType.RelationshipData].get_total_relationship_number(relationship_bit)

    def get_current_total_relationships(self, relationship_bit):
        return self._data[data_const.DataType.RelationshipData].get_current_relationship_number(relationship_bit)

    @test_events.DataMapHandler(test_events.TestEvent.BuffBeganEvent)
    def add_buff_event(self, sim_id=None, buff=None, **kwargs):
        self._data[data_const.DataType.BuffData].buff_added(sim_id, buff)

    @test_events.DataMapHandler(test_events.TestEvent.BuffEndedEvent)
    def remove_buff_event(self, sim_id=None, buff=None, **kwargs):
        self._data[data_const.DataType.BuffData].buff_removed(sim_id, buff)

    @test_events.DataMapHandler(test_events.TestEvent.BuffUpdateEvent)
    def buff_update_event(self, sim_id=None, buff=None, **kwargs):
        self._data[data_const.DataType.BuffData].buff_removed(sim_id, buff)
        self._data[data_const.DataType.BuffData].buff_added(sim_id, buff)

    def get_total_buff_uptime(self, buff):
        return self._data[data_const.DataType.BuffData].get_total_buff_time_span(buff)

    def get_total_buff_data(self, buff):
        return self._data[data_const.DataType.BuffData].get_total_buff_data(buff)

    def get_buff_time_dictionary(self):
        return self._data[data_const.DataType.BuffData].get_buff_time_dictionary()

    @test_events.DataMapHandler(test_events.TestEvent.SimoleonsEarned)
    def add_simoleons_earned(self, simoleon_data_type=None, amount=None, **kwargs):
        if amount <= 0:
            return
        self._data[data_const.DataType.SimoleanData].add_simoleons(simoleon_data_type, amount)

    def get_simoleons_earned(self, simoleon_data_type):
        return self._data[data_const.DataType.SimoleanData].get_simoleon_data(simoleon_data_type)

    @test_events.DataMapHandler(test_events.TestEvent.WorkdayComplete)
    def add_career_data_event(self, career=None, time_worked=None, money_made=None, **kwargs):
        self._data[data_const.DataType.CareerData].add_career_data(career, time_worked, money_made)

    def get_career_data(self, career):
        return self._data[data_const.DataType.CareerData].get_career_data(career)

    def get_career_data_by_name(self, career_name):
        return self._data[data_const.DataType.CareerData].get_career_data_by_name(career_name)

    def get_all_career_data(self):
        return self._data[data_const.DataType.CareerData]._careers

    @test_events.DataMapHandler(test_events.TestEvent.InteractionComplete)
    def add_tag_time_from_interaction(self, interaction=None, **kwargs):
        if interaction is None:
            return
        type = data_const.DataType.TagData
        for tag in interaction.get_category_tags():
            time_update = interaction.consecutive_running_time_span
            if interaction.id in self._data[type].interactions and tag in self._data[type].interactions[interaction.id]:
                time_update -= self._data[type].interactions[interaction.id][tag]
            self._data[type].time_added(tag, time_update)

    @test_events.DataMapHandler(test_events.TestEvent.InteractionUpdate)
    def add_tag_time_update_from_interaction(self, interaction=None, **kwargs):
        if interaction is None:
            return
        type = data_const.DataType.TagData
        if interaction.id not in self._data[type].interactions:
            self._data[type].interactions[interaction.id] = {}
        for tag in interaction.get_category_tags():
            previous = TimeSpan(0)
            if tag in self._data[type].interactions[interaction.id]:
                previous = self._data[type].interactions[interaction.id][tag]
            time_update = interaction.consecutive_running_time_span - previous
            self._data[type].time_added(tag, time_update)
            self._data[type].interactions[interaction.id][tag] = interaction.consecutive_running_time_span

    @test_events.DataMapHandler(test_events.TestEvent.SimoleonsEarned)
    def add_tag_simoleons_earned(self, tags=(), amount=0, **kwargs):
        if amount <= 0 or tags is None:
            return
        for tag in tags:
            self._data[data_const.DataType.TagData].simoleons_added(tag, amount)

    def get_total_tag_interaction_time_elapsed(self, tag):
        return self._data[data_const.DataType.TagData].get_total_interaction_time_elapsed(tag)

    def get_total_tag_simoleons_earned(self, tag):
        return self._data[data_const.DataType.TagData].get_total_simoleons_earned(tag)

    def save(self, complete_event_data_blob):
        for data in self._data.values():
            data.save(complete_event_data_blob.data)

    def load(self, complete_event_data_blob):
        for data in self._data.values():
            data.load(complete_event_data_blob.data)

class ObjectiveCountData:
    __qualname__ = 'ObjectiveCountData'

    class Data:
        __qualname__ = 'ObjectiveCountData.Data'

        def __init__(self):
            self._count = 0
            self._ids = set()

        def get_count(self):
            if self._ids:
                return len(self._ids)
            return self._count

        def increment(self):
            pass

        def add_id(self, id_to_add):
            self._ids.add(id_to_add)

        def set_completed(self):
            if not self._ids:
                return
            self._count = len(self._ids)
            self._ids.clear()

        def reset(self):
            self._count = 0
            self._ids.clear()

        def save(self, save_data):
            save_data.amount = self._count
            save_data.ids.extend(self._ids)

        def load(self, save_data):
            self._count = save_data.amount
            self._ids = {id_to_add for id_to_add in save_data.ids}

    def __init__(self):
        self._stored_objective_count_data = {}

    def get_data(self):
        return self._stored_objective_count_data

    def get_objective_count(self, objective_uid):
        if objective_uid in self._stored_objective_count_data:
            return self._stored_objective_count_data[objective_uid].get_count()
        return 0

    def reset_objective_count(self, objective_uid):
        if objective_uid in self._stored_objective_count_data:
            self._stored_objective_count_data[objective_uid].reset()

    def increment_objective_count(self, objective_uid):
        if objective_uid not in self._stored_objective_count_data:
            self._stored_objective_count_data[objective_uid] = ObjectiveCountData.Data()
        self._stored_objective_count_data[objective_uid].increment()

    def add_id(self, objective_uid, id_to_add):
        if objective_uid not in self._stored_objective_count_data:
            self._stored_objective_count_data[objective_uid] = ObjectiveCountData.Data()
        self._stored_objective_count_data[objective_uid].add_id(id_to_add)

    def set_objective_complete(self, objective_uid):
        if objective_uid in self._stored_objective_count_data:
            self._stored_objective_count_data[objective_uid].set_completed()

    def save(self, event_data_blob):
        for (objective_uid, objective_data) in self._stored_objective_count_data.items():
            objective_save_data = event_data_blob.objective_data.add()
            objective_save_data.enum = objective_uid
            objective_data.save(objective_save_data)

    def load(self, event_data_blob):
        for objective_data in event_data_blob.objective_data:
            self._stored_objective_count_data[objective_data.enum] = ObjectiveCountData.Data()
            self._stored_objective_count_data[objective_data.enum].load(objective_data)

class CareerData:
    __qualname__ = 'CareerData'

    class Data:
        __qualname__ = 'CareerData.Data'

        def __init__(self):
            self._time_worked = 0
            self._money_earned = 0

        def increment_data(self, time_worked, money_earned):
            pass

        def set_data(self, time_worked, money_earned):
            self._time_worked = time_worked
            self._money_earned = money_earned

        def get_hours_worked(self):
            date_and_time = DateAndTime(self._time_worked)
            return date_and_time.absolute_hours()

        def get_money_earned(self):
            return self._money_earned

    def __init__(self):
        self._careers = {}

    def get_career_data(self, career):
        career_name = type(career).__name__
        return self.get_career_data_by_name(career_name)

    def get_career_data_by_name(self, career_name):
        if career_name not in self._careers:
            self._careers[career_name] = CareerData.Data()
        return self._careers[career_name]

    def set_career_data_by_name(self, career_name, time_worked, money_earned):
        if career_name not in self._careers:
            self._careers[career_name] = CareerData.Data()
        self._careers[career_name].set_data(time_worked, money_earned)

    def add_career_data(self, career, time_worked, money_earned):
        self.get_career_data(career).increment_data(time_worked, money_earned)

    def save(self, event_data_blob):
        for career_name in self._careers.keys():
            career_data = event_data_blob.career_data.add()
            career_data.name = career_name
            career_data.time = self._careers[career_name]._time_worked
            career_data.money = self._careers[career_name]._money_earned

    def load(self, event_data_blob):
        for career in event_data_blob.career_data:
            self.set_career_data_by_name(career.name, career.time, career.money)

class SimoleonData:
    __qualname__ = 'SimoleonData'

    def __init__(self):
        self._stored_simoleon_data = {}
        for item in data_const.SimoleonData:
            self._stored_simoleon_data[item] = 0

    def get_simoleon_data(self, simoleon_type):
        return self._stored_simoleon_data[simoleon_type]

    def add_simoleons(self, simoleon_type, amount):
        self._stored_simoleon_data[simoleon_type] += amount

    def save(self, event_data_blob):
        for (enum, amount) in self._stored_simoleon_data.items():
            simoleon_data = event_data_blob.simoleon_data.add()
            simoleon_data.enum = enum
            simoleon_data.amount = amount

    def load(self, event_data_blob):
        for simoleon_data in event_data_blob.simoleon_data:
            self._stored_simoleon_data[simoleon_data.enum] = simoleon_data.amount

class TimeData:
    __qualname__ = 'TimeData'

    def __init__(self):
        self._stored_time_data = {}
        for item in data_const.TimeData:
            self._stored_time_data[item] = 0

    def get_time_data(self, time_type):
        return self._stored_time_data[time_type]

    def add_time_data(self, time_type, amount):
        self._stored_time_data[time_type] += amount

    def save(self, event_data_blob):
        for (enum, amount) in self._stored_time_data.items():
            time_data = event_data_blob.time_data.add()
            time_data.enum = enum
            time_data.amount = amount

    def load(self, event_data_blob):
        for time_data in event_data_blob.time_data:
            self._stored_time_data[time_data.enum] = time_data.amount

class TravelData:
    __qualname__ = 'TravelData'

    def __init__(self):
        self._lots_traveled = set()

    def get_travel_amount(self):
        return len(self._lots_traveled)

    def add_travel_data(self, zone_id):
        if zone_id is not None:
            self._lots_traveled.add(zone_id)

    def save(self, event_data_blob):
        for lot in self._lots_traveled:
            event_data_blob.travel_data.append(lot)

    def load(self, event_data_blob):
        for lot in event_data_blob.travel_data:
            self._lots_traveled.add(lot)

class RelationshipData:
    __qualname__ = 'RelationshipData'

    class Data:
        __qualname__ = 'RelationshipData.Data'

        def __init__(self):
            self._stored_relationship_data = {}
            for item in data_const.RelationshipData:
                self._stored_relationship_data[item] = 0

    def __init__(self):
        self._relationships = {}

    def get_relationship_data(self, relationship):
        return self.get_relationship_data_by_id(relationship.guid64)

    def get_relationship_data_by_id(self, bit_instance_id):
        if bit_instance_id not in self._relationships:
            self._relationships[bit_instance_id] = RelationshipData.Data()
        return self._relationships[bit_instance_id]._stored_relationship_data

    def set_relationship_data_by_id(self, bit_instance_id, enum, quantity):
        data = self.get_relationship_data_by_id(bit_instance_id)
        data[enum] = quantity

    def add_relationship_bit(self, new_relationship_bit, sim_id, target_sim_id):
        new_relationship_data = self.get_relationship_data(new_relationship_bit)
        new_relationship_data[data_const.RelationshipData.CurrentRelationships] += 1
        new_relationship_data[data_const.RelationshipData.TotalRelationships] += 1

    def remove_relationship_bit(self, removed_relationship_bit, sim_id, target_sim_id):
        removed_relationship_data = self.get_relationship_data(removed_relationship_bit)
        removed_relationship_data[data_const.RelationshipData.CurrentRelationships] -= 1

    def get_current_relationship_number(self, relationship):
        return self.get_relationship_data(relationship)[data_const.RelationshipData.CurrentRelationships]

    def get_total_relationship_number(self, relationship):
        return self.get_relationship_data(relationship)[data_const.RelationshipData.TotalRelationships]

    def save(self, event_data_blob):
        for relationship_id in self._relationships.keys():
            relationship_data = event_data_blob.relationship_data.add()
            for (enum, data) in self.get_relationship_data_by_id(relationship_id).items():
                this_enum = relationship_data.enums.add()
                this_enum.enum = enum
                this_enum.amount = data
            relationship_data.relationship_id = relationship_id

    def load(self, event_data_blob):
        for relationship in event_data_blob.relationship_data:
            for enum in relationship.enums:
                self.set_relationship_data_by_id(relationship.relationship_id, enum.enum, enum.amount)

class BuffData:
    __qualname__ = 'BuffData'

    class Data:
        __qualname__ = 'BuffData.Data'

        def __init__(self):
            self._stored_buff_data = {}
            for item in data_const.BuffData:
                if item == data_const.BuffData.LastTimeBuffStarted:
                    self._stored_buff_data[item] = {}
                else:
                    self._stored_buff_data[item] = TimeSpan.ZERO

    def __init__(self):
        self._buffs = {}

    def get_buff_data(self, buff):
        buff_name = buff.__name__
        return self.get_buff_data_by_name(buff_name)

    def get_buff_data_only(self, buff):
        buff_name = buff.__name__
        if buff_name not in self._buffs:
            return TimeSpan.ZERO
        return self._buffs[buff_name]._stored_buff_data

    def get_buff_data_by_name(self, buff_name):
        if buff_name not in self._buffs:
            self._buffs[buff_name] = BuffData.Data()
        return self._buffs[buff_name]._stored_buff_data

    def set_buff_data_by_name(self, buff_name, enum, quantity):
        data = self.get_buff_data_by_name(buff_name)
        data[enum] = TimeSpan(quantity)

    def buff_added(self, sim_id, buff):
        buff_data = self.get_buff_data(buff)
        start_stamp = buff_data[data_const.BuffData.LastTimeBuffStarted].get(sim_id)
        if start_stamp is None:
            start_stamp = DateAndTime(0)
        elif start_stamp > DateAndTime(0):
            return
        buff_data[data_const.BuffData.LastTimeBuffStarted][sim_id] = services.time_service().sim_now

    def buff_removed(self, sim_id, buff):
        buff_data = self.get_buff_data(buff)
        if sim_id not in buff_data[data_const.BuffData.LastTimeBuffStarted]:
            return
        last_buff_start_time = buff_data[data_const.BuffData.LastTimeBuffStarted][sim_id]
        if last_buff_start_time == DateAndTime(0):
            return
        buff_data[data_const.BuffData.TotalBuffTimeElapsed] = buff_data[data_const.BuffData.TotalBuffTimeElapsed] + (services.time_service().sim_now - last_buff_start_time)
        buff_data[data_const.BuffData.LastTimeBuffStarted][sim_id] = DateAndTime(0)

    def get_total_buff_time_span(self, buff):
        buff_data = self.get_buff_data(buff)
        return buff_data[data_const.BuffData.TotalBuffTimeElapsed]

    def get_total_buff_data(self, buff):
        buff_data = self.get_buff_data_only(buff)
        if buff_data is TimeSpan.ZERO:
            return buff_data
        return buff_data[data_const.BuffData.TotalBuffTimeElapsed]

    def get_buff_time_dictionary(self):
        buff_dict = {}
        for (buff_name, buff_time) in self._buffs:
            buff_dict[buff_name] = buff_time._stored_buff_data[data_const.BuffData.TotalBuffTimeElapsed]
        return buff_dict

    def refresh_start_times(self):
        for buff in self._buffs.values():
            time_elapsed = DateAndTime(0)
            for (sim_id, last_time_started) in buff._stored_buff_data[data_const.BuffData.LastTimeBuffStarted].items():
                if last_time_started == DateAndTime(0):
                    pass
                else:
                    time_elapsed += services.time_service().sim_now - last_time_started
                    buff._stored_buff_data[data_const.BuffData.LastTimeBuffStarted][sim_id] = last_time_started = services.time_service().sim_now
            buff._stored_buff_data[data_const.BuffData.TotalBuffTimeElapsed] += TimeSpan(time_elapsed.absolute_ticks())

    def save(self, event_data_blob):
        self.refresh_start_times()
        for buff_name in self._buffs.keys():
            buff_data = event_data_blob.buff_data.add()
            for (enum, data) in self.get_buff_data_by_name(buff_name).items():
                if enum is data_const.BuffData.LastTimeBuffStarted:
                    pass
                this_enum = buff_data.enums.add()
                this_enum.enum = enum
                this_enum.amount = data.in_ticks()
            buff_data.name = buff_name

    def load(self, event_data_blob):
        for buff in event_data_blob.buff_data:
            for enum in buff.enums:
                if enum.enum is data_const.BuffData.LastTimeBuffStarted:
                    pass
                self.set_buff_data_by_name(buff.name, enum.enum, enum.amount)

class RelativeStartingData:
    __qualname__ = 'RelativeStartingData'

    def __init__(self):
        self._objective_relative_values = {}

    def set_starting_values(self, obj_guid64, values):
        self._objective_relative_values[obj_guid64] = values

    def get_starting_values(self, obj_guid64):
        if obj_guid64 in self._objective_relative_values:
            return self._objective_relative_values[obj_guid64]

    def save(self, event_data_blob):
        for (objective_guid64, start_values) in self._objective_relative_values.items():
            obj_start_value = event_data_blob.relative_start_data.add()
            obj_start_value.objective_guid64 = objective_guid64
            obj_start_value.starting_values.extend(start_values)

    def load(self, event_data_blob):
        for obj_value_pair in event_data_blob.relative_start_data:
            self.set_starting_values(obj_value_pair.objective_guid64, obj_value_pair.starting_values)

class TagData:
    __qualname__ = 'TagData'

    class Data:
        __qualname__ = 'TagData.Data'

        def __init__(self):
            self._stored_tag_data = {}
            for item in data_const.TagData:
                if item == data_const.TagData.TimeElapsed:
                    self._stored_tag_data[item] = TimeSpan.ZERO
                else:
                    self._stored_tag_data[item] = 0

    def __init__(self):
        self._tags = {}
        self.interactions = {}

    def get_tag_data(self, tag):
        if tag not in self._tags:
            self._tags[tag] = TagData.Data()
        return self._tags[tag]._stored_tag_data

    def set_tag_data(self, tag, enum, quantity):
        data = self.get_tag_data(tag)
        if enum == data_const.TagData.TimeElapsed:
            data[enum] = TimeSpan(quantity)
        else:
            data[enum] = quantity

    def time_added(self, tag, time_quantity):
        tag_data = self.get_tag_data(tag)
        tag_data[data_const.TagData.TimeElapsed] += time_quantity

    def simoleons_added(self, tag, quantity):
        tag_data = self.get_tag_data(tag)
        tag_data[data_const.TagData.SimoleonsEarned] += quantity

    def get_total_interaction_time_elapsed(self, tag):
        tag_data = self.get_tag_data(tag)
        return tag_data[data_const.TagData.TimeElapsed]

    def get_total_simoleons_earned(self, tag):
        tag_data = self.get_tag_data(tag)
        return tag_data[data_const.TagData.SimoleonsEarned]

    def save(self, event_data_blob):
        for tag in self._tags.keys():
            tag_data = event_data_blob.tag_data.add()
            for (enum, data) in self.get_tag_data(tag).items():
                this_enum = tag_data.enums.add()
                this_enum.enum = enum
                if enum == data_const.TagData.TimeElapsed:
                    this_enum.amount = data.in_ticks()
                else:
                    this_enum.amount = data
            tag_data.tag_enum = tag

    def load(self, event_data_blob):
        for tag in event_data_blob.tag_data:
            for enum in tag.enums:
                self.set_tag_data(tag.tag_enum, enum.enum, enum.amount)

