from crafting.recipe import Recipe
from event_testing.tests import TunableTestSet
from sims4.localization import TunableLocalizedStringFactory
from sims4.tuning.instances import TunedInstanceMetaclass, HashedTunedInstanceMetaclass
from sims4.tuning.tunable import TunableResourceKey, TunableRealSecond, TunableList, TunableReference, Tunable
import services
import sims4.resources

class MusicTrack(metaclass=HashedTunedInstanceMetaclass, manager=services.get_instance_manager(sims4.resources.Types.RECIPE)):
    __qualname__ = 'MusicTrack'
    INSTANCE_TUNABLES = {'music_clip': TunableResourceKey(description='\n            The propx file of the music clip to play.\n            ', needs_tuning=False, default=None, resource_types=[sims4.resources.Types.PROPX]), 'length': TunableRealSecond(description='\n            "The length of the clip in real seconds.  This should be a part\n            of the propx\'s file name."\n            ', needs_tuning=False, default=30, minimum=0), 'buffer': TunableRealSecond(description="\n            A buffer added to the track length.  This is used to prevent the \n            audio from stopping before it's finished.\n            ", needs_tuning=False, default=0), 'check_for_unlock': Tunable(description='\n            "Whether or not to check the Sim\'s Unlock Component to determine\n            if they can play the song.  Currently, only clips that are meant \n            to be unlocked by the Write Song interaction should have this set\n            to true."\n            ', needs_tuning=False, tunable_type=bool, default=False), 'loc_clip_name': TunableLocalizedStringFactory(description="\n            If the clip is of a song, this will be the localized name for it.\n            The name will be shown in the pie menu when picking specific songs\n            to play.  If the clip isn't a song, like clips used for the\n            Practice or Write Song interactions, this does not need to be\n            tuned.\n            "), 'tests': TunableTestSet(description='\n            Tests to verify if this song is available for the Sim to play.\n            '), 'moods': TunableList(description="\n            A list of moods that will be used to determine which song a Sim\n            will play autonomously.  If a Sim doesn't know any songs that\n            their current mood, they'll play anything.\n            ", tunable=TunableReference(manager=services.mood_manager()), needs_tuning=True)}

class MusicStyle(metaclass=TunedInstanceMetaclass, manager=services.get_instance_manager(sims4.resources.Types.RECIPE)):
    __qualname__ = 'MusicStyle'
    INSTANCE_TUNABLES = {'music_tracks': TunableList(TunableReference(description='\n            A particular music track to use as part of this\n            style.\n            ', manager=services.get_instance_manager(sims4.resources.Types.RECIPE), class_restrictions=(MusicTrack,))), 'pie_menu_category': TunableReference(description='\n            The pie menu category for this music style.\n            This can be used to break styles up into genres.\n            ', manager=services.get_instance_manager(sims4.resources.Types.PIE_MENU_CATEGORY))}

class MusicRecipe(Recipe):
    __qualname__ = 'MusicRecipe'
    INSTANCE_TUNABLES = {'music_track_unlock': TunableReference(description='\n            The music track that will be unlocked when the crafting process is\n            complete.\n            ', manager=services.get_instance_manager(sims4.resources.Types.RECIPE), class_restrictions=(MusicTrack,)), 'music_style': TunableReference(description='\n            Which music style the Sim will pull tracks from while writing\n            the song.\n            ', manager=services.get_instance_manager(sims4.resources.Types.RECIPE), class_restrictions=(MusicStyle,))}

