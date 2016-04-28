from animation.animation_ac_cache import read_ac_cache_from_resource
from paths import USE_CACHED_CONSTRAINTS
from sims4.tuning.instance_manager import InstanceManager
import sims4.log
logger = sims4.log.Logger('InteractionManager', default_owner='manus')
BUILD_AC_CACHE = False
USE_AC_CACHE = True

class InteractionInstanceManager(InstanceManager):
    __qualname__ = 'InteractionInstanceManager'
    _ac_cache = {}

    def purge_cache(self):
        self._ac_cache.clear()

    def on_start(self):
        super().on_start()
        if BUILD_AC_CACHE:
            self._build_animation_constraint_cache()
        elif should_use_animation_constaint_cache():
            self._use_animation_constraint_cache()

    def _build_animation_constraint_cache(self):
        for cls in self.types.values():
            if cls._auto_constraints is not None:
                self._ac_cache[cls.__name__] = cls._auto_constraints
            else:
                self._ac_cache[cls.__name__] = {}

    def _use_animation_constraint_cache(self):
        if self._ac_cache:
            logger.error('Animation Constraint Cache is already set up. Illegal request to re-populate the cache.')
            return
        self._ac_cache.update(read_ac_cache_from_resource())
        if not self._ac_cache:
            return
        for cls in self.types.values():
            name = cls.__name__
            cached_constraints = self._ac_cache.get(name)
            if cached_constraints is None:
                logger.error('Cached animation constraints not available for {}'.format(name))
            else:
                while cls._auto_constraints is None:
                    cls._auto_constraints = self._ac_cache[name]

def should_use_animation_constaint_cache():
    return USE_AC_CACHE and (not BUILD_AC_CACHE and USE_CACHED_CONSTRAINTS)

def get_animation_constraint_cache_debug_information():
    return [('USE_CACHED_CONSTRAINTS', str(USE_CACHED_CONSTRAINTS), 'Localwork Ignored Or Empty'), ('BUILD_AC_CACHE', str(BUILD_AC_CACHE), 'Whether we are currently building AC Cache'), ('USE_AC_CACHE', str(USE_AC_CACHE), 'Tuning to enable AC Cache'), ('AC_CACHE SIZE', len(InteractionInstanceManager._ac_cache), 'dict size of _ac_cache')]

