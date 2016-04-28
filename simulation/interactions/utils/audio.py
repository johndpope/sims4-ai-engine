from audio.primitive import TunablePlayAudio, play_tunable_audio
from element_utils import CleanupType, build_element, build_critical_section_with_finally
from interactions import ParticipantType
from interactions.utils.interaction_elements import XevtTriggeredElement
from sims4.tuning.tunable import TunableFactory, TunableEnumFlags, Tunable, HasTunableFactory, AutoFactoryInit, TunableEnumEntry
import sims4.log
logger = sims4.log.Logger('Audio')

class TunableAudioModificationElement(TunableFactory):
    __qualname__ = 'TunableAudioModificationElement'

    @staticmethod
    def factory(interaction, subject, tag_name, effect_name, sequence=(), **kwargs):
        target = interaction.get_participant(subject)
        if target is not None:

            def start(*_, **__):
                target.append_audio_effect(tag_name, effect_name)

            def stop(*_, **__):
                target.remove_audio_effect(tag_name)

        return build_critical_section_with_finally(start, sequence, stop)

    FACTORY_TYPE = factory

    def __init__(self, **kwargs):
        super().__init__(subject=TunableEnumFlags(ParticipantType, ParticipantType.Actor, description='Object the audio effect will be placed on.'), tag_name=Tunable(str, 'x', description='Name of the animation tag this effect will trigger on.'), effect_name=Tunable(str, None, description='Name of the audio modification that will be applied'), **kwargs)

class ApplyAudioEffect(HasTunableFactory, AutoFactoryInit):
    __qualname__ = 'ApplyAudioEffect'

    @staticmethod
    def _verify_tunable_callback(instance_class, tunable_name, source, effect_name=None, tag_name=None):
        if not effect_name:
            logger.error('Audio Effect for {} does not have a valid effect specified'.format(instance_class))
        if not tag_name:
            logger.error('Audio Effect for {} does not have a valid tag specified'.format(instance_class))

    FACTORY_TUNABLES = {'effect_name': Tunable(description='\n            Name of the audio modification that will be applied.\n            ', tunable_type=str, default=None), 'tag_name': Tunable(description='\n            Name of the animation tag this effect will trigger on.\n            ', tunable_type=str, default='x'), 'verify_tunable_callback': _verify_tunable_callback}

    def __init__(self, target, **kwargs):
        super().__init__(**kwargs)
        self.target = target
        self._running = False

    def _run(self):
        self.start()
        return True

    @property
    def running(self):
        return self._running

    @property
    def is_attached(self):
        return self._running

    def start(self):
        if not self.running:
            self.target.append_audio_effect(self.tag_name, self.effect_name)
            self._running = True

    def stop(self, *_, **__):
        if self.running:
            self.target.remove_audio_effect(self.tag_name)
            self._running = False

class TunableAudioSting(XevtTriggeredElement, HasTunableFactory, AutoFactoryInit):
    __qualname__ = 'TunableAudioSting'

    @staticmethod
    def _verify_tunable_callback(instance_class, tunable_name, source, audio_sting=None, **kwargs):
        if audio_sting is None:
            logger.error("Attempting to play audio sting that hasn't been tuned on {}", source)

    FACTORY_TUNABLES = {'verify_tunable_callback': _verify_tunable_callback, 'description': 'Play an Audio Sting at the beginning/end of an interaction or on XEvent.', 'audio_sting': TunablePlayAudio(description='\n            The audio sting that gets played on the subject.\n            '), 'stop_audio_on_end': Tunable(description="\n            If checked AND the timing is not set to END, the audio sting will\n            turn off when the interaction finishes. Otherwise, the audio will\n            play normally and finish when it's done.\n            ", tunable_type=bool, default=False), 'subject': TunableEnumEntry(ParticipantType, ParticipantType.Actor, description='The participant who the audio sting will be played on.')}

    def _build_outer_elements(self, sequence):

        def stop_audio(e):
            if hasattr(self, '_sound'):
                self._sound.stop()

        if self.stop_audio_on_end and self.timing is not self.AT_END:
            return build_element([sequence, stop_audio], critical=CleanupType.OnCancelOrException)
        return sequence

    def _do_behavior(self):
        subject = self.interaction.get_participant(self.subject)
        if subject is not None or not self.stop_audio_on_end:
            self._sound = play_tunable_audio(self.audio_sting, subject)
        else:
            logger.error('Expecting to start and stop a TunableAudioSting during {} on a subject that is None.'.format(self.interaction), owner='rmccord')

