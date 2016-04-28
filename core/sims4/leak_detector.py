import gc
import sys
import types
from sims4.repr_utils import callable_repr
import sims4.log
_full_print = False
logger = sims4.log.Logger('Leak Detector')
global_module_ids = {id(__builtins__), id(sys.modules)}
_termination_points = None
_recursion_depth = 15
_termination_string = 'Leak Detection terminated due to having found at least 10 Potential Leaks.-Mike Duke'

def find_object_refs(obj, valid_refs=set(), termination_points=set(), recursion_depth=15):
    global _recursion_depth, _termination_points
    gc.collect()
    logger.error('Searching for reference chains pointing to {}: {}', id(obj), obj)
    try:
        _recursion_depth = recursion_depth
        _termination_points = {id(e) for e in termination_points}
        _termination_points.update(global_module_ids)
        valid_refs.add(id(locals()))
        valid_refs.add(id(obj))
        refs = _get_refs(obj, valid_refs)
        valid_refs.add(id(refs))
        try:
            i = 0
            while True:
                frame = sys._getframe(i)
                if _full_print:
                    logger.error('Ignoring frame: {}', callable_repr(frame))
                valid_refs.add(id(frame))
                i += 1
        except ValueError:
            pass
        if len(refs) > 0:
            valid_refs.update(id(ref) for ref in refs)
            ret = False
            possible_leak_chains = []
            for ref in refs:
                ret |= _find_leaks(obj, ref, valid_refs, 1, [], possible_leak_chains)
            if ret:
                output = 'Leaked Ref List:\nObject: {}, Type: {}\n'.format(obj, type(obj))
                output += '\n'.join(possible_leak_chains)
                logger.error(output)
            else:
                logger.error('No leaks found. (Some allowed refs exist outside current call stack.)')
        else:
            logger.error('No leaks found. (No refs at all outside current call stack.)')
    except:
        logger.exception('Exception thrown while ref tracking in find_object_refs.-Mike Duke')

def _get_refs(obj, valid_refs):
    ret = []
    gc.collect()
    g_refs = gc.get_referrers(obj)
    valid_refs.add(id(locals()))
    valid_refs.add(id(sys._getframe()))
    for ref in g_refs:
        if id(ref) in valid_refs:
            pass
        ret.append(ref)
    if len(ret) == 1 and isinstance(ret[0], types.TracebackType):
        valid_refs.add(id(g_refs))
        valid_refs.add(id(ret))
        return _get_refs(ret[0], valid_refs)
    return ret

def _find_leaks(referent, potential_leak, valid_refs, recursion_depth, output_ref_chain, possible_leak_chains):
    valid_refs.add(id(sys._getframe()))
    ret = False
    if recursion_depth > 1:
        output = '  '*(recursion_depth - 1)
    else:
        output = ''
    type_name = type(potential_leak).__name__
    special_output = None
    if isinstance(potential_leak, types.FrameType):
        s = callable_repr(potential_leak)
        special_output = '{}: ID: {}, Frame: {}'.format(recursion_depth, id(potential_leak), s[:900])
    elif isinstance(potential_leak, types.FunctionType):
        s = callable_repr(potential_leak)
        special_output = '{}: ID: {}, Function: {}'.format(recursion_depth, id(potential_leak), s[:900])
    elif isinstance(potential_leak, dict):
        for (key_name, value) in potential_leak.items():
            while value is referent:
                special_output = '{}: ID: {}, dict[{}]'.format(recursion_depth, id(potential_leak), key_name)
                break
    if special_output:
        output += special_output
    else:
        output += '{}: ID: {}, {}: {}'.format(recursion_depth, id(potential_leak), type_name, str(potential_leak)[:900])
    output_ref_chain.append(output)
    if _full_print:
        logger.error(output)
    if output.find('pydev') >= 0:
        return False
    if recursion_depth == _recursion_depth or id(potential_leak) in _termination_points:
        output_string = '\n'.join(output_ref_chain)
        possible_leak_chains.append(output_string)
        return True
    if recursion_depth == -1:
        raise StopIteration
    valid_refs.add(id(locals()))
    fl_refs = _get_refs(potential_leak, valid_refs)
    valid_refs.add(id(fl_refs))
    for ref in fl_refs:
        valid_refs.add(id(ref))
    for ref in fl_refs:
        recursion_depth += 1
        ret |= _find_leaks(potential_leak, ref, valid_refs, recursion_depth, output_ref_chain, possible_leak_chains)
        if not _full_print and len(possible_leak_chains) > 9:
            if _termination_string not in possible_leak_chains:
                possible_leak_chains.append(_termination_string)
            return ret
        output_ref_chain.pop()
        recursion_depth -= 1
    return ret

