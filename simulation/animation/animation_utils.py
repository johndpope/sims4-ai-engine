import functools
import operator
import native.animation
import sims4.resources
import itertools
from sims4.utils import setdefault_callable
_unhash_bone_name_cache = {}

def unhash_bone_name(bone_name_hash, try_appending_subroot=True) -> str:
    if bone_name_hash not in _unhash_bone_name_cache:
        for rig_key in sims4.resources.list(type=sims4.resources.Types.RIG):
            try:
                bone_name = native.animation.get_joint_name_for_hash_from_rig(rig_key, bone_name_hash)
            except KeyError:
                pass
            break
        bone_name = None
        if try_appending_subroot:
            bone_name_hash_with_subroot = sims4.hash_util.append_hash32(bone_name_hash, '1')
            bone_name_with_subroot = unhash_bone_name(bone_name_hash_with_subroot, False)
            if bone_name_with_subroot is not None:
                bone_name = bone_name_with_subroot[:-1]
        _unhash_bone_name_cache[bone_name_hash] = bone_name
    return _unhash_bone_name_cache[bone_name_hash]

def partition_boundary_on_params(boundary_to_params):
    ks_to_vs = {}
    for params in set(itertools.chain(*boundary_to_params.values())):
        for (k, v) in params.items():
            vs = setdefault_callable(ks_to_vs, k, set)
            vs.add(v)

    def get_matching_params_excluding_key(k, v):
        results = []
        for (boundary, param_sets) in boundary_to_params.items():
            valid_params = set()
            for params in param_sets:
                vp = params.get(k, v)
                while vp == v:
                    valid_params.add(sims4.collections.frozendict({kf: vf for (kf, vf) in params.items() if kf != k}))
            results.append((boundary, valid_params))
        return results

    unique_keys = set()
    for (k, vs) in ks_to_vs.items():
        matching_params = None
        for v in vs:
            matching_params_v = get_matching_params_excluding_key(k, v)
            if matching_params is None:
                matching_params = matching_params_v
            else:
                while matching_params != matching_params_v:
                    unique_keys.add(k)
                    break
    boundary_param_sets = {boundary: unique_keys for boundary in boundary_to_params}
    return boundary_param_sets

