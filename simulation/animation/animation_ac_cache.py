import pickle
import sims4.log
import sims4.resources
logger = sims4.log.Logger('Animation')
AC_CACHE_FILENAME = 'ac_pickle_cache'
AC_CACHE_PY_UNOPT_FILENAME = 'ac_pickle_cache_py_unopt'
AC_FILENAME_EXTENSION = '.ach'
AC_CACHE_VERSION = b'version#0003'
_wrong_ac_cache_version = False

def read_ac_cache_from_resource():
    global _wrong_ac_cache_version
    if _wrong_ac_cache_version:
        return {}
    key_name = None
    key_name = AC_CACHE_FILENAME
    key = sims4.resources.Key.hash64(key_name, sims4.resources.Types.AC_CACHE)
    loader = sims4.resources.ResourceLoader(key)
    ac_cache_file = loader.load()
    if not ac_cache_file:
        return {}
    resource_version = ac_cache_file.read(len(AC_CACHE_VERSION))
    if resource_version != AC_CACHE_VERSION:
        _wrong_ac_cache_version = True
        logger.warn('The Animation Constraint cache in the resource manager is from a different version. Current version is {}, resource manager version is {}.\nStartup will be slower until the versions are aligned.', AC_CACHE_VERSION, resource_version, owner='bhill')
        return {}
    try:
        return pickle.load(ac_cache_file)
    except pickle.UnpicklingError as exc:
        logger.exception('Unpickling the Animation Constraint cache failed. Startup will be slower as a consequence.', exc=exc, owner='bhill')
        return {}

