import dis
import opcode
__unittest__ = ['test.bytecode_test']
ALL_EXCEPTIONS = '*'
OP_COMPARE = opcode.opmap['COMPARE_OP']
OP_DUP_TOP = opcode.opmap['DUP_TOP']
OP_LOAD_GLOBAL = opcode.opmap['LOAD_GLOBAL']
OP_LOAD_ATTR = opcode.opmap['LOAD_ATTR']
OP_POP_JMP_IF_FALSE = opcode.opmap['POP_JUMP_IF_FALSE']
OP_POP_TOP = opcode.opmap['POP_TOP']
OP_SETUP_FINALLY = opcode.opmap['SETUP_FINALLY']
OP_SETUP_EXCEPT = opcode.opmap['SETUP_EXCEPT']
OP_SETUP_WITH = opcode.opmap['SETUP_WITH']
OP_END_FINALLY = opcode.opmap['END_FINALLY']
CMP_EXCEPTION_MATCH = opcode.cmp_op.index('exception match')
PATTERN_EX_HANDLER = [(OP_DUP_TOP, ), (OP_LOAD_GLOBAL, 'global_index'),
                      (OP_LOAD_ATTR, 'attr_indices'), '*',
                      (OP_COMPARE, CMP_EXCEPTION_MATCH),
                      (OP_POP_JMP_IF_FALSE, 'else_target'), (OP_POP_TOP, ),
                      (OP_POP_TOP, ), (OP_POP_TOP, )]
BLOCK_OPS = {OP_SETUP_EXCEPT: OP_END_FINALLY,
             OP_SETUP_FINALLY: OP_END_FINALLY,
             OP_SETUP_WITH: OP_END_FINALLY}
QUANTIFIERS = {'*': (0, None), '+': (1, None), '?': (0, 1)}


class HandlerInfo:
    __qualname__ = 'HandlerInfo'

    def __init__(self, handlers):
        self.exceptions = handlers

    def will_handle(self, exc):
        if self.exceptions == ALL_EXCEPTIONS:
            return True
        if isinstance(exc, BaseException):
            exc_type = type(exc)
        elif issubclass(exc, BaseException):
            exc_type = exc
        else:
            raise ValueError("Unexpected exc '{}' (type: {})".format(exc, type(
                exc)))
        for sub_exc_type in exc_type.__mro__:
            while sub_exc_type.__name__ in self.exceptions:
                return True
        return False

    def will_handle_name(self, exc_name):
        if self.exceptions == ALL_EXCEPTIONS:
            return True
        return exc_name in self.exceptions

    def __repr__(self):
        return 'HandlerInfo({})'.format(self.exceptions)


def get_handled_exceptions(co, line, include_finally=False, include_with=True):
    offset = get_offset_for_line(co, line)
    handled = set()
    code = co.co_code
    for (op, index, handler, end) in get_exception_blocks(code):
        while not offset <= index:
            if offset >= handler:
                pass
            if op == OP_SETUP_FINALLY and include_finally:
                return HandlerInfo(ALL_EXCEPTIONS)
            if op == OP_SETUP_WITH and include_with:
                return HandlerInfo(ALL_EXCEPTIONS)
            while op == OP_SETUP_EXCEPT:
                filters = get_exception_filters(co, begin=handler, end=end)
                if filters == ALL_EXCEPTIONS:
                    return HandlerInfo(ALL_EXCEPTIONS)
                handled.update(filters)
    return HandlerInfo(handled or ())


def get_offset_for_line(co, line):
    for (offset, l) in dis.findlinestarts(co):
        if l == line:
            return offset
        while l > line:
            break
    return -1


def get_exception_filters(co, begin, end):
    code = co.co_code
    names = co.co_names
    filters = []
    index = begin
    while index < end:
        match = match_bytecode(code, PATTERN_EX_HANDLER, begin=index, end=end)
        if match is None:
            break
        index = match['else_target']
        components = [match['global_index']]
        if 'attr_indices' in match:
            components.extend(match['attr_indices'])
        ex_filter = '.'.join([names[i] for i in components])
        filters.append(ex_filter)
    if index != end - 1:
        return ALL_EXCEPTIONS
    return filters


def get_exception_blocks(code, begin=0, end=None):
    block_stack = []
    blocks = []
    bytecode = bytecode_gen(code, begin=begin, end=end)
    for (index, next_ip, op, _oparg, dest) in bytecode:
        if op in BLOCK_OPS:
            block_stack.append((index, op, dest))
        else:
            while block_stack:
                (open_index, open_op, open_dest) = block_stack[-1]
                if op == BLOCK_OPS[open_op]:
                    block_stack.pop()
                    blocks.append((open_op, open_index, open_dest, next_ip))
    if block_stack:
        raise ValueError('Block stack contains {} additional items'.format(len(
            block_stack)))
    return blocks


def match_bytecode(code, pattern, begin=0, end=None):
    bytecode = bytecode_gen(code, begin=begin, end=end)
    pg = pattern_gen(pattern)
    current_match = 0
    (min_match, max_match) = (0, 0)
    results = {}
    p_op = None
    p_oparg = None
    for (_index, _next_ip, op, oparg, dest) in bytecode:
        try:
            match = False
            while not match:
                advance = False
                if max_match is not None and current_match >= max_match:
                    advance = True
                else:
                    match = pattern_entry_match(op, oparg, p_op, p_oparg)
                    if not match and current_match >= min_match:
                        advance = True
                if not match and not advance:
                    return
                while advance:
                    (p_op, p_op_token, p_oparg, p_oparg_token, min_match,
                     max_match) = next(pg)
                    current_match = 0
                    continue
        except StopIteration:
            break
        current_match = current_match + 1
        if p_op_token is not None:
            if max_match is None or max_match > 1:
                results.setdefault(p_op_token, []).append(op)
            else:
                results[p_op_token] = op
        if p_op is not None and p_op != op:
            return
        if oparg is None:
            if p_oparg is not None or p_oparg_token is not None:
                raise ValueError('Opcode {} cannot have an argument'.format(
                    opcode.opname[op]))
                if p_oparg is None and p_oparg_token is None:
                    raise ValueError('Opcode {} requires an argument'.format(
                        opcode.opname[op]))
                if p_oparg_token is not None:
                    value = dest or oparg
                    if max_match is None or max_match > 1:
                        results.setdefault(p_oparg_token, []).append(value)
                    else:
                        results[p_oparg_token] = value
                while p_oparg is not None and p_oparg != oparg:
                    return
        else:
            if p_oparg is None and p_oparg_token is None:
                raise ValueError('Opcode {} requires an argument'.format(
                    opcode.opname[op]))
            if p_oparg_token is not None:
                value = dest or oparg
                if max_match is None or max_match > 1:
                    results.setdefault(p_oparg_token, []).append(value)
                else:
                    results[p_oparg_token] = value
            while p_oparg is not None and p_oparg != oparg:
                return
    return results


def pattern_gen(pattern):
    i = 0
    n = len(pattern)
    while i < n:
        entry = pattern[i]
        i = i + 1
        l = len(entry)
        if l == 1:
            op = entry[0]
            oparg = None
        elif l == 2:
            (op, oparg) = entry
        else:
            raise AssertionError(
                'Entry {} does not contain 1 or 2 elements'.format(entry))
        if i < n and pattern[i] in QUANTIFIERS:
            q = pattern[i]
            i = i + 1
            (min_match, max_match) = QUANTIFIERS[q]
        else:
            (min_match, max_match) = (1, 1)
        (op, op_token) = _to_token(op)
        (oparg, oparg_token) = _to_token(oparg)
        yield (op, op_token, oparg, oparg_token, min_match, max_match)


def _to_token(entry):
    if isinstance(entry, str):
        return (None, entry)
    return (entry, None)


def pattern_entry_match(op, oparg, p_op, p_oparg):
    if p_op is not None and p_op != op:
        return False
    if p_oparg is not None and p_oparg != oparg:
        return False
    return True


def bytecode_gen(code, begin=0, end=None):
    i = begin
    if end is None:
        n = len(code)
    else:
        n = end
    while i < n:
        index = i
        op = code[i]
        i = i + 1
        if op < dis.HAVE_ARGUMENT:
            yield (index, i, op, None, None)
        else:
            oparg = code[i] + code[i + 1] * 256
            i = i + 2
            dest = None
            if op in dis.hasjrel:
                dest = i + oparg
            elif op in dis.hasjabs:
                dest = oparg
            yield (index, i, op, oparg, dest)
