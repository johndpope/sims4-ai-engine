import _symtable
from _symtable import USE, DEF_GLOBAL, DEF_LOCAL, DEF_PARAM, DEF_IMPORT, DEF_BOUND, OPT_IMPORT_STAR, SCOPE_OFF, SCOPE_MASK, FREE, LOCAL, GLOBAL_IMPLICIT, GLOBAL_EXPLICIT, CELL
import weakref
__all__ = ['symtable', 'SymbolTable', 'Class', 'Function', 'Symbol']

def symtable(code, filename, compile_type):
    top = _symtable.symtable(code, filename, compile_type)
    return _newSymbolTable(top, filename)

class SymbolTableFactory:
    __qualname__ = 'SymbolTableFactory'

    def __init__(self):
        self._SymbolTableFactory__memo = weakref.WeakValueDictionary()

    def new(self, table, filename):
        if table.type == _symtable.TYPE_FUNCTION:
            return Function(table, filename)
        if table.type == _symtable.TYPE_CLASS:
            return Class(table, filename)
        return SymbolTable(table, filename)

    def __call__(self, table, filename):
        key = (table, filename)
        obj = self._SymbolTableFactory__memo.get(key, None)
        if obj is None:
            obj = self._SymbolTableFactory__memo[key] = self.new(table, filename)
        return obj

_newSymbolTable = SymbolTableFactory()

class SymbolTable(object):
    __qualname__ = 'SymbolTable'

    def __init__(self, raw_table, filename):
        self._table = raw_table
        self._filename = filename
        self._symbols = {}

    def __repr__(self):
        if self.__class__ == SymbolTable:
            kind = ''
        else:
            kind = '%s ' % self.__class__.__name__
        if self._table.name == 'global':
            return '<{0}SymbolTable for module {1}>'.format(kind, self._filename)
        return '<{0}SymbolTable for {1} in {2}>'.format(kind, self._table.name, self._filename)

    def get_type(self):
        if self._table.type == _symtable.TYPE_MODULE:
            return 'module'
        if self._table.type == _symtable.TYPE_FUNCTION:
            return 'function'
        if self._table.type == _symtable.TYPE_CLASS:
            return 'class'

    def get_id(self):
        return self._table.id

    def get_name(self):
        return self._table.name

    def get_lineno(self):
        return self._table.lineno

    def is_optimized(self):
        return bool(self._table.type == _symtable.TYPE_FUNCTION and not self._table.optimized)

    def is_nested(self):
        return bool(self._table.nested)

    def has_children(self):
        return bool(self._table.children)

    def has_exec(self):
        return False

    def has_import_star(self):
        return bool(self._table.optimized & OPT_IMPORT_STAR)

    def get_identifiers(self):
        return self._table.symbols.keys()

    def lookup(self, name):
        sym = self._symbols.get(name)
        if sym is None:
            flags = self._table.symbols[name]
            namespaces = self._SymbolTable__check_children(name)
            sym = self._symbols[name] = Symbol(name, flags, namespaces)
        return sym

    def get_symbols(self):
        return [self.lookup(ident) for ident in self.get_identifiers()]

    def __check_children(self, name):
        return [_newSymbolTable(st, self._filename) for st in self._table.children if st.name == name]

    def get_children(self):
        return [_newSymbolTable(st, self._filename) for st in self._table.children]

class Function(SymbolTable):
    __qualname__ = 'Function'
    _Function__params = None
    _Function__locals = None
    _Function__frees = None
    _Function__globals = None

    def __idents_matching(self, test_func):
        return tuple([ident for ident in self.get_identifiers() if test_func(self._table.symbols[ident])])

    def get_parameters(self):
        if self._Function__params is None:
            self._Function__params = self._Function__idents_matching(lambda x: x & DEF_PARAM)
        return self._Function__params

    def get_locals(self):
        if self._Function__locals is None:
            locs = (LOCAL, CELL)
            test = lambda x: x >> SCOPE_OFF & SCOPE_MASK in locs
            self._Function__locals = self._Function__idents_matching(test)
        return self._Function__locals

    def get_globals(self):
        if self._Function__globals is None:
            glob = (GLOBAL_IMPLICIT, GLOBAL_EXPLICIT)
            test = lambda x: x >> SCOPE_OFF & SCOPE_MASK in glob
            self._Function__globals = self._Function__idents_matching(test)
        return self._Function__globals

    def get_frees(self):
        if self._Function__frees is None:
            is_free = lambda x: x >> SCOPE_OFF & SCOPE_MASK == FREE
            self._Function__frees = self._Function__idents_matching(is_free)
        return self._Function__frees

class Class(SymbolTable):
    __qualname__ = 'Class'
    _Class__methods = None

    def get_methods(self):
        if self._Class__methods is None:
            d = {}
            for st in self._table.children:
                d[st.name] = 1
            self._Class__methods = tuple(d)
        return self._Class__methods

class Symbol(object):
    __qualname__ = 'Symbol'

    def __init__(self, name, flags, namespaces=None):
        self._Symbol__name = name
        self._Symbol__flags = flags
        self._Symbol__scope = flags >> SCOPE_OFF & SCOPE_MASK
        self._Symbol__namespaces = namespaces or ()

    def __repr__(self):
        return '<symbol {0!r}>'.format(self._Symbol__name)

    def get_name(self):
        return self._Symbol__name

    def is_referenced(self):
        return bool(self._Symbol__flags & _symtable.USE)

    def is_parameter(self):
        return bool(self._Symbol__flags & DEF_PARAM)

    def is_global(self):
        return bool(self._Symbol__scope in (GLOBAL_IMPLICIT, GLOBAL_EXPLICIT))

    def is_declared_global(self):
        return bool(self._Symbol__scope == GLOBAL_EXPLICIT)

    def is_local(self):
        return bool(self._Symbol__flags & DEF_BOUND)

    def is_free(self):
        return bool(self._Symbol__scope == FREE)

    def is_imported(self):
        return bool(self._Symbol__flags & DEF_IMPORT)

    def is_assigned(self):
        return bool(self._Symbol__flags & DEF_LOCAL)

    def is_namespace(self):
        return bool(self._Symbol__namespaces)

    def get_namespaces(self):
        return self._Symbol__namespaces

    def get_namespace(self):
        if len(self._Symbol__namespaces) != 1:
            raise ValueError('name is bound to multiple namespaces')
        return self._Symbol__namespaces[0]

if __name__ == '__main__':
    import os
    import sys
    src = open(sys.argv[0]).read()
    mod = symtable(src, os.path.split(sys.argv[0])[1], 'exec')
    for ident in mod.get_identifiers():
        info = mod.lookup(ident)
        print(info, info.is_local(), info.is_namespace())
