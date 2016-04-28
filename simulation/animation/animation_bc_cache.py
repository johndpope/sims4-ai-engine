import pickle
import sims4.log
import sims4.resources
logger = sims4.log.Logger('Animation')
BC_CACHE_FILENAME = 'bc_pickle_cache'
BC_CACHE_PY_UNOPT_FILENAME = 'bc_pickle_cache_py_unopt'
BC_FILENAME_EXTENSION = '.bch'
BC_CACHE_VERSION = b'version#0001'
_wrong_bc_cache_version = False

def read_bc_cache_from_resource():
    global _wrong_bc_cache_version
    if _wrong_bc_cache_version:
        return {}
    key_name = None
    key_name = BC_CACHE_FILENAME
    key = sims4.resources.Key.hash64(key_name, sims4.resources.Types.BC_CACHE)
    loader = sims4.resources.ResourceLoader(key)
    bc_cache_file = loader.load()
    if not bc_cache_file:
        return {}
    resource_version = bc_cache_file.read(len(BC_CACHE_VERSION))
    if resource_version != BC_CACHE_VERSION:
        _wrong_bc_cache_version = True
        logger.warn('The Animation Boundary Condition cache in the resource manager is from a different version. Current version is {}, resource manager version is {}.\nStartup will be slower until the versions are aligned.', BC_CACHE_VERSION, resource_version, owner='bhill')
        return {}
    try:
        return pickle.load(bc_cache_file)
    except pickle.UnpicklingError as exc:
        logger.exception('Unpickling the Animation Boundary Condition cache failed. Startup will be slower as a consequence.', exc=exc, owner='bhill')
        return {}

