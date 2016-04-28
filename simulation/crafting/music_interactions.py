import random
import alarms
from audio.primitive import PlaySound
import build_buy
import clock
from crafting.crafting_interactions import CraftingPhaseSuperInteractionMixin, CraftingPhaseStagingSuperInteraction
from crafting.music import MusicStyle
from event_testing.resolver import SingleSimResolver
from interactions.aop import AffordanceObjectPair
from interactions.base.immediate_interaction import ImmediateSuperInteraction
from interactions.base.super_interaction import SuperInteraction
from interactions.interaction_finisher import FinishingType
from interactions.social.social_super_interaction import SocialSuperInteraction
import services
import sims4
from element_utils import build_critical_section_with_finally
from sims4.tuning.tunable import Tunable, TunableList, TunableReference, TunableRange
from sims4.utils import flexmethod
from singletons import DEFAULT
from tag import Tag
from ui.ui_dialog_generic import UiDialogTextInputOk
logger = sims4.log.Logger('Interactions')

class PlayAudioSuperInteraction(SuperInteraction):
    __qualname__ = 'PlayAudioSuperInteraction'
    INSTANCE_SUBCLASSES_ONLY = True
    SCRIPT_EVENT_ID_START_AUDIO = 100
    SCRIPT_EVENT_ID_STOP_AUDIO = 101
    INSTANCE_TUNABLES = {'play_multiple_clips': Tunable(description='\n            If true, the Sim will continue playing until the interaction is\n            cancelled or exit conditions are met. \n            ', needs_tuning=False, tunable_type=bool, default=False), 'music_styles': TunableList(TunableReference(description='\n            Which music styles are available for this interaction.\n            ', manager=services.get_instance_manager(sims4.resources.Types.RECIPE), class_restrictions=(MusicStyle,))), 'use_buffer': Tunable(description="\n            If true, this interaction will add the buffer tuned on the music\n            track to the length of the track.  This is tunable because some\n            interactions, like Practice, use shorter audio clips that don't\n            require the buffer.\n            ", needs_tuning=False, tunable_type=bool, default=True)}

    def __init__(self, aop, context, track=None, pie_menu_category=None, unlockable_name=None, **kwargs):
        super().__init__(aop, context, **kwargs)
        self._track = track
        self.pie_menu_category = pie_menu_category
        self._unlockable_name = unlockable_name
        self._sound_alarm = None
        self._sound = None

    def build_basic_content(self, sequence=(), **kwargs):
        self.animation_context.register_event_handler(self._create_sound_alarm, handler_id=self.SCRIPT_EVENT_ID_START_AUDIO)
        self.animation_context.register_event_handler(self._cancel_sound_alarm, handler_id=self.SCRIPT_EVENT_ID_STOP_AUDIO)
        return super().build_basic_content(sequence, **kwargs)

    def on_reset(self):
        self._cancel_sound_alarm()
        super().on_reset()

    def _create_sound_alarm(self, *args, **kwargs):
        track_length = self._get_track_length()
        if self._sound_alarm is None:
            self._sound_alarm = alarms.add_alarm(self, track_length, self._sound_alarm_callback)
        if self._sound is None:
            self._sound = PlaySound(self._instrument, self._track.music_clip.instance)
        self._sound.start()

    def _sound_alarm_callback(self, handle):
        if self.play_multiple_clips:
            self._cancel_sound_alarm()
            if hasattr(self, 'recipe'):
                styles = [self.recipe.music_style]
            else:
                styles = self.music_styles
            self._track = PlayAudioSuperInteraction._get_next_track(styles, self.sim, self.get_resolver())
            self._create_sound_alarm()
        else:
            self.cancel(FinishingType.NATURAL, cancel_reason_msg='Sound alarm triggered and the song finished naturally.')

    def _cancel_sound_alarm(self, *args, **kwargs):
        if self._sound_alarm is not None:
            alarms.cancel_alarm(self._sound_alarm)
            self._sound_alarm = None
        if self._sound is not None:
            self._sound.stop()
            self._sound = None

    def _get_track_length(self):
        real_seconds = self._track.length
        if self.use_buffer:
            real_seconds += self._track.buffer
        interval = clock.interval_in_real_seconds(real_seconds)
        return interval

    @property
    def _instrument(self):
        return self.target

    @staticmethod
    def _get_next_track(styles, sim, resolver):
        valid_tracks = []
        for style in styles:
            for track in style.music_tracks:
                if track.check_for_unlock and sim.sim_info.unlock_tracker.is_unlocked(track):
                    valid_tracks.append(track)
                else:
                    while not track.check_for_unlock and track.tests.run_tests(resolver):
                        valid_tracks.append(track)
        sim_mood = sim.get_mood()
        valid_mood_tracks = tuple(track for track in valid_tracks if sim_mood in track.moods)
        return random.choice(valid_mood_tracks or valid_tracks)

class PlayAudioSuperInteractionTieredMenu(PlayAudioSuperInteraction):
    __qualname__ = 'PlayAudioSuperInteractionTieredMenu'

    @flexmethod
    def get_pie_menu_category(cls, inst, pie_menu_category=None, **interaction_parameters):
        if inst is not None:
            return inst.pie_menu_category
        return pie_menu_category

    @flexmethod
    def _get_name(cls, inst, target=DEFAULT, context=DEFAULT, track=None, unlockable_name=None, **kwargs):
        loc_args = ()
        if track is not None:
            if unlockable_name is not None:
                loc_args = unlockable_name
            return track.loc_clip_name(loc_args)
        inst_or_cls = inst if inst is not None else cls
        return super(SuperInteraction, inst_or_cls)._get_name(target=target, context=context, **kwargs)

    @classmethod
    def potential_interactions(cls, target, context, **kwargs):
        sim = context.sim
        resolver = SingleSimResolver(sim.sim_info)
        for style in cls.music_styles:
            for track in style.music_tracks:
                while track.tests.run_tests(resolver):
                    if not track.check_for_unlock:
                        yield AffordanceObjectPair(cls, target, cls, None, track=track, pie_menu_category=style.pie_menu_category, **kwargs)
                    else:
                        unlocks = sim.sim_info.unlock_tracker.get_unlocks(track)
                        if unlocks:
                            while True:
                                for unlock in unlocks:
                                    yield AffordanceObjectPair(cls, target, cls, None, track=unlock.tuning_class, pie_menu_category=style.pie_menu_category, unlockable_name=unlock.name, **kwargs)

class PlayAudioSuperInteractionNonTieredMenu(PlayAudioSuperInteraction):
    __qualname__ = 'PlayAudioSuperInteractionNonTieredMenu'

    def __init__(self, aop, context, **kwargs):
        super().__init__(aop, context, **kwargs)
        if 'phase' in kwargs:
            phase = kwargs['phase']
            styles = [phase.recipe.music_style]
        else:
            styles = self.music_styles
        self._track = PlayAudioSuperInteraction._get_next_track(styles, context.sim, self.get_resolver())

class PlayAudioSocialSuperInteraction(PlayAudioSuperInteractionNonTieredMenu, SocialSuperInteraction):
    __qualname__ = 'PlayAudioSocialSuperInteraction'

    @property
    def _instrument(self):
        if self.carry_target is not None:
            return self.carry_target
        return self.target

class PlayAudioCraftingPhaseStagingSuperInteraction(PlayAudioSuperInteractionNonTieredMenu, CraftingPhaseStagingSuperInteraction):
    __qualname__ = 'PlayAudioCraftingPhaseStagingSuperInteraction'

TEXT_INPUT_SONG_NAME = 'song_name'

class UnluckMusicTrackSuperInteraction(CraftingPhaseSuperInteractionMixin, SuperInteraction):
    __qualname__ = 'UnluckMusicTrackSuperInteraction'
    INSTANCE_TUNABLES = {'dialog': UiDialogTextInputOk.TunableFactory(description='\n            Text entry dialog to name the song the Sim wrote.\n            ', text_inputs=(TEXT_INPUT_SONG_NAME,))}

    def _run_interaction_gen(self, timeline):

        def on_response(dialog):
            if not dialog.accepted:
                self.cancel(FinishingType.DIALOG, cancel_reason_msg='Name Song dialog timed out from client.')
                return
            name = dialog.text_input_responses.get(TEXT_INPUT_SONG_NAME)
            self.sim.sim_info.unlock_tracker.add_unlock(self.phase.recipe.music_track_unlock, name)

        dialog = self.dialog(self.sim, self.get_resolver())
        dialog.show_dialog(on_response=on_response)

        def _destroy_target():
            self.process.current_ico.destroy(source=self, cause='Destroying target of unlock music track SI')

        self.add_exit_function(_destroy_target)
        return True

class LicenseSongSuperInteraction(SuperInteraction):
    __qualname__ = 'LicenseSongSuperInteraction'
    INSTANCE_TUNABLES = {'music_styles': TunableList(TunableReference(description='\n            Which music styles are available for this interaction.  This\n            should be only the Written Music Style for the particular\n            instrument.\n            ', manager=services.get_instance_manager(sims4.resources.Types.RECIPE), class_restrictions=(MusicStyle,), reload_dependent=True))}

    @classmethod
    def _verify_tuning_callback(cls):
        for style in cls.music_styles:
            for track in style.music_tracks:
                while not track.check_for_unlock:
                    logger.error("MusicTrack {} does not have check_for_unlock set to False.  This is required for MusicTracks that can be 'Licensed'.", track.__name__)

    def __init__(self, aop, context, track=None, unlockable_name=None, **kwargs):
        super().__init__(aop, context, unlockable_name=unlockable_name, **kwargs)
        self._track = track
        self._unlockable_name = unlockable_name

    @flexmethod
    def _get_name(cls, inst, target=DEFAULT, context=DEFAULT, track=None, unlockable_name=None, **kwargs):
        if unlockable_name is not None:
            return track.loc_clip_name(unlockable_name)
        inst_or_cls = inst if inst is not None else cls
        return super(SuperInteraction, inst_or_cls)._get_name(target=target, context=context, **kwargs)

    @classmethod
    def potential_interactions(cls, target, context, **kwargs):
        if context.sim is None:
            return
        for style in cls.music_styles:
            for track in style.music_tracks:
                unlocks = context.sim.sim_info.unlock_tracker.get_unlocks(track)
                while unlocks:
                    while True:
                        for unlock in unlocks:
                            yield AffordanceObjectPair(cls, target, cls, None, track=unlock.tuning_class, pie_menu_category=style.pie_menu_category, unlockable_name=unlock.name, **kwargs)

class HackBringToTearsImmediateInteraction(ImmediateSuperInteraction):
    __qualname__ = 'HackBringToTearsImmediateInteraction'

    def _run_interaction_gen(self, timeline):
        violin = None
        violin_tag = set([Tag.Instrument_Violin])
        inventory = self.sim.inventory_component
        for item in inventory:
            object_tags = set(build_buy.get_object_all_tags(item.definition.id))
            while object_tags & violin_tag:
                violin = item
                break
        if violin is not None:
            self.context.carry_target = violin
            yield super()._run_interaction_gen(timeline)
        return False

