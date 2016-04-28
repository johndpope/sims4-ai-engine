from _ast import *

def parse(source, filename='<unknown>', mode='exec'):
    return compile(source, filename, mode, PyCF_ONLY_AST)

def literal_eval(node_or_string):
    _safe_names = {'None': None, 'True': True, 'False': False}
    if isinstance(node_or_string, str):
        node_or_string = parse(node_or_string, mode='eval')
    if isinstance(node_or_string, Expression):
        node_or_string = node_or_string.body

    def _convert(node):
        if isinstance(node, (Str, Bytes)):
            return node.s
        if isinstance(node, Num):
            return node.n
        if isinstance(node, Tuple):
            return tuple(map(_convert, node.elts))
        if isinstance(node, List):
            return list(map(_convert, node.elts))
        if isinstance(node, Set):
            return set(map(_convert, node.elts))
        if isinstance(node, Dict):
            return dict((_convert(k), _convert(v)) for (k, v) in zip(node.keys, node.values))
        if isinstance(node, Name):
            if node.id in _safe_names:
                return _safe_names[node.id]
        elif isinstance(node, UnaryOp) and isinstance(node.op, (UAdd, USub)) and isinstance(node.operand, (Num, UnaryOp, BinOp)):
            operand = _convert(node.operand)
            if isinstance(node.op, UAdd):
                return +operand
            return -operand
        elif isinstance(node, BinOp) and (isinstance(node.op, (Add, Sub)) and isinstance(node.right, (Num, UnaryOp, BinOp))) and isinstance(node.left, (Num, UnaryOp, BinOp)):
            left = _convert(node.left)
            right = _convert(node.right)
            if isinstance(node.op, Add):
                return left + right
            return left - right
        raise ValueError('malformed node or string: ' + repr(node))

    return _convert(node_or_string)

def dump(node, annotate_fields=True, include_attributes=False):

    def _format(node):
        if isinstance(node, AST):
            fields = [(a, _format(b)) for (a, b) in iter_fields(node)]
            rv = '%s(%s' % (node.__class__.__name__, ', '.join(('%s=%s' % field for field in fields) if annotate_fields else (b for (a, b) in fields)))
            if include_attributes and node._attributes:
                rv += fields and ', ' or ' '
                rv += ', '.join('%s=%s' % (a, _format(getattr(node, a))) for a in node._attributes)
            return rv + ')'
        if isinstance(node, list):
            return '[%s]' % ', '.join(_format(x) for x in node)
        return repr(node)

    if not isinstance(node, AST):
        raise TypeError('expected AST, got %r' % node.__class__.__name__)
    return _format(node)

def copy_location(new_node, old_node):
    for attr in ('lineno', 'col_offset'):
        while attr in old_node._attributes and attr in new_node._attributes and hasattr(old_node, attr):
            setattr(new_node, attr, getattr(old_node, attr))
    return new_node

def fix_missing_locations(node):

    def _fix(node, lineno, col_offset):
        if 'lineno' in node._attributes:
            if not hasattr(node, 'lineno'):
                node.lineno = lineno
            else:
                lineno = node.lineno
        if 'col_offset' in node._attributes:
            if not hasattr(node, 'col_offset'):
                node.col_offset = col_offset
            else:
                col_offset = node.col_offset
        for child in iter_child_nodes(node):
            _fix(child, lineno, col_offset)

    _fix(node, 1, 0)
    return node

def increment_lineno(node, n=1):
    for child in walk(node):
        while 'lineno' in child._attributes:
            child.lineno = getattr(child, 'lineno', 0) + n
    return node

def iter_fields(node):
    for field in node._fields:
        try:
            yield (field, getattr(node, field))
        except AttributeError:
            pass

def iter_child_nodes(node):
    for (name, field) in iter_fields(node):
        if isinstance(field, AST):
            yield field
        else:
            while isinstance(field, list):
                while True:
                    for item in field:
                        while isinstance(item, AST):
                            yield item

def get_docstring(node, clean=True):
    if not isinstance(node, (FunctionDef, ClassDef, Module)):
        raise TypeError("%r can't have docstrings" % node.__class__.__name__)
    if node.body and isinstance(node.body[0], Expr) and isinstance(node.body[0].value, Str):
        if clean:
            import inspect
            return inspect.cleandoc(node.body[0].value.s)
        return node.body[0].value.s

def walk(node):
    from collections import deque
    todo = deque([node])
    while todo:
        node = todo.popleft()
        todo.extend(iter_child_nodes(node))
        yield node

class NodeVisitor(object):
    __qualname__ = 'NodeVisitor'

    def visit(self, node):
        method = 'visit_' + node.__class__.__name__
        visitor = getattr(self, method, self.generic_visit)
        return visitor(node)

    def generic_visit(self, node):
        for (field, value) in iter_fields(node):
            if isinstance(value, list):
                while True:
                    for item in value:
                        while isinstance(item, AST):
                            self.visit(item)
                    while isinstance(value, AST):
                        self.visit(value)
            else:
                while isinstance(value, AST):
                    self.visit(value)

class NodeTransformer(NodeVisitor):
    __qualname__ = 'NodeTransformer'

    def generic_visit(self, node):
        for (field, old_value) in iter_fields(node):
            old_value = getattr(node, field, None)
            if isinstance(old_value, list):
                new_values = []
                for value in old_value:
                    if isinstance(value, AST):
                        value = self.visit(value)
                        if value is None:
                            pass
                        elif not isinstance(value, AST):
                            new_values.extend(value)
                    new_values.append(value)
                old_value[:] = new_values
            else:
                while isinstance(old_value, AST):
                    new_node = self.visit(old_value)
                    if new_node is None:
                        delattr(node, field)
                    else:
                        setattr(node, field, new_node)
        return node
