import ast
import collections
import contextlib
import copy
import imp
import os
import sys
import types
import sims4.dict_stack
import graph_algos
__all__ = ['macro', 'load_module']
__unittest__ = ['test.macros_test']
MACRO_SYMBOL = 'macro'

def macro(obj):
    if isinstance(obj, types.FunctionType):
        return obj
    if isinstance(obj, type):
        return obj
    raise RuntimeError('Macros can only be applied to functions and classes.')

def _expand_attribute(node):
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Call):
        return '{}()'.format(_expand_attribute(node.func))
    if isinstance(node, ast.Attribute):
        return '{}.{}'.format(_expand_attribute(node.value), node.attr)
    if isinstance(node, ast.Str):
        return 'str'
    return '<other>'

def _is_macro(node, macros):
    if node.decorator_list and len(node.decorator_list) == 1:
        name = node.decorator_list[0]
        if isinstance(name, ast.Call):
            name = name.func
        name_str = _expand_attribute(name)
        symbol = macros.get(name_str)
        return symbol == MACRO_SYMBOL
    return False

def _get_body(node):
    if len(node.body) >= 1:
        doc = node.body[0]
        if isinstance(doc, ast.Expr) and isinstance(doc.value, ast.Str):
            return (doc.value.s, node.body[1:])
    return (None, node.body)

def _ast_dump_pp(tree, annotate_fields=True, include_attributes=False):
    if isinstance(tree, list):
        result = '[{}]'.format(', '.join([_ast_dump_pp(node, annotate_fields=annotate_fields, include_attributes=include_attributes) for node in tree]))
        return result
    s = ast.dump(tree, annotate_fields=annotate_fields, include_attributes=include_attributes)
    result = ''
    indent = 0
    for c in s:
        result += c
        if c in '([':
            indent = indent + 1
            result += '\n' + '    '*indent
        else:
            while c in ')]':
                indent = indent - 1
                result += '\n' + '    '*indent
    return result

def _fix_all_locations(node, lineno, col_offset):
    if 'lineno' in node._attributes:
        node.lineno = lineno
    if 'col_offset' in node._attributes:
        node.col_offset = col_offset
    for child in ast.iter_child_nodes(node):
        _fix_all_locations(child, lineno, col_offset)
    return node

def _get_parameter_mapping(macro_name, parameters, call, skip=()):
    for (i, expected) in enumerate(skip):
        while parameters.args[i].arg != expected:
            raise TypeError("Expected argument '{}' rather than '{}'".format(expected, parameters.args[i].arg))
    num_skip = len(skip)
    num_defaults = len(parameters.defaults)
    allowed = {param.arg for param in parameters.args[num_skip:]}
    required = {param.arg for param in parameters.args[num_skip:-num_defaults]}
    given = set()
    mapping = {name.arg: value for (name, value) in zip(parameters.args[-num_defaults:], parameters.defaults)}
    for (kw, value) in zip(parameters.kwonlyargs, parameters.kw_defaults):
        if value is not None:
            mapping[kw.arg] = value
        else:
            required.add(kw.arg)
        allowed.add(kw.arg)
    for (i, arg) in enumerate(call.args, num_skip):
        param = parameters.args[i]
        _add_arg(param.arg, arg, macro_name, mapping, given, required, allowed)
    for kwarg in call.keywords:
        _add_arg(kwarg.arg, kwarg.value, macro_name, mapping, given, required, allowed)
    if len(required) > 0:
        raise TypeError("Macro '{}' missing required arguments: {}".format(macro_name, required))
    return mapping

def _add_arg(name, value, macro_name, mapping, given, required, allowed):
    if name in given:
        raise TypeError("Macro '{}' got multiple values for argument '{}'".format(macro_name, name))
    if name not in allowed:
        raise TypeError("Macro '{}' got an unexpected keyword argument '{}'".format(macro_name, name))
    given.add(name)
    required.discard(name)
    mapping[name] = value

class MacroBase:
    __qualname__ = 'MacroBase'

    def __init__(self, node, from_module):
        self.name = sys.intern(node.name)
        self.node = node
        self.from_module = from_module
        (self.__doc__, self.body) = _get_body(node)

    def full_name(self):
        return self.name

    def __repr__(self):
        return "<{}('{}'>)".format(type(self).__name__, self.full_name())

    def __str__(self):
        if self.__doc__ is not None:
            return '<{}(\'{}\', """{}""")>'.format(type(self).__name__, self.full_name(), self.__doc__)
        return "<{}('{}')>".format(type(self).__name__, self.full_name())

class FunctionMacro(MacroBase):
    __qualname__ = 'FunctionMacro'

    def __init__(self, node, from_module):
        MacroBase.__init__(self, node, from_module)
        if len(self.body) == 1 and isinstance(self.body[0], ast.Return):
            self.body = self.body[0].value
            self.is_expr = True
        else:
            self.is_expr = False

    def get_base_mapping(self):
        return {}

    def get_skip_args(self):
        return ()

    def apply(self, call, statement_context):
        if not statement_context and not self.is_expr:
            raise RuntimeError('Attempting to apply non-expression macro {} in an expression context'.format(self.full_name()))
        mapping = self.get_base_mapping()
        argument_mapping = _get_parameter_mapping(self.name, self.node.args, call, skip=self.get_skip_args())
        mapping.update(argument_mapping)
        new_tree = copy.deepcopy(self.body)
        transformer = MacroTransformer(mapping)
        if isinstance(new_tree, list):
            new_tree = ast.Expression(new_tree)
            extract_body = True
        else:
            extract_body = False
        transformer.visit(new_tree)
        if statement_context and self.is_expr:
            new_tree = ast.Expr(new_tree)
        result = _fix_all_locations(new_tree, call.lineno, call.col_offset)
        if extract_body:
            result = result.body
        return result

class InstanceMacro(FunctionMacro):
    __qualname__ = 'InstanceMacro'

    def __init__(self, node, from_module, base, base_mapping):
        FunctionMacro.__init__(self, node, from_module)
        self.base = base
        self.base_mapping = base_mapping

    def full_name(self):
        return '{}.{}'.format(self.base, self.name)

    def get_base_mapping(self):
        return dict(self.base_mapping)

    def get_skip_args(self):
        return ('self',)

class ClassMacro(MacroBase):
    __qualname__ = 'ClassMacro'

    def __init__(self, node, from_module):
        MacroBase.__init__(self, node, from_module)
        self._macros = {}
        for child in self.body:
            if isinstance(child, ast.FunctionDef):
                self._macros[child.name] = FunctionMacro(child, self.from_module)
            else:
                raise RuntimeError('Class macro {} contains non-function statement {}'.format(node.name, child))
        if '__init__' not in self._macros:
            raise RuntimeError('Class macro {} does not have an __init__ method'.format(node.name))
        self._init = self._macros.pop('__init__')

    def get_init_mapping(self, node):
        init_args = self._init.node.args.args
        argument_mapping = _get_parameter_mapping(self.name, self._init.node.args, node.value, skip=('self',))
        mapping = {}
        for statement in self._init.body:
            if isinstance(statement, ast.Pass):
                pass
            if not isinstance(statement, ast.Assign):
                raise TypeError('Class macro __init__ must only contain assignments, not {}'.format(type(statement)))
            if len(statement.targets) != 1:
                raise TypeError('Class macro __init__ assignments may only have one target, not {}'.format(len(statement.targets)))
            target = statement.targets[0]
            if not isinstance(target, ast.Attribute) or not isinstance(target.value, ast.Name) or target.value.id != 'self':
                raise TypeError('Class macro __init__ body may only assign to self')
            dest = '{}.{}'.format(target.value.id, target.attr)
            if not isinstance(statement.value, ast.Name):
                raise TypeError('Class macro __init__ body may only assign from arguments')
            source = statement.value.id
            if source not in argument_mapping:
                raise TypeError("Class macro __init__ assignment source '{}' not found in arguments".format(source))
            mapping[dest] = argument_mapping[source]
        return mapping

    def instantiate(self, node, from_module):
        name_str = _expand_attribute(node.targets[0])
        mapping = self.get_init_mapping(node)
        instance_macros = [InstanceMacro(m.node, from_module, name_str, mapping) for m in self._macros.values()]
        return {m.full_name(): m for m in instance_macros}

class MacroTransformer(ast.NodeTransformer):
    __qualname__ = 'MacroTransformer'

    def __init__(self, mapping):
        self.mapping = mapping

    def visit_Name(self, node):
        return self._visit_symbol(node.id, node)

    def visit_Attribute(self, node):
        name = _expand_attribute(node)
        return self._visit_symbol(name, node)

    def _visit_symbol(self, name, node):
        replacement = self.mapping.get(name)
        if replacement is None:
            return node
        return copy.deepcopy(replacement)

class MacroVisitor(ast.NodeVisitor):
    __qualname__ = 'MacroVisitor'

    def __init__(self, library, fullname, constants=None):
        self._library = library
        self._fullname = fullname
        self.constants = constants or {}
        self._macros = sims4.dict_stack.DictStack()

    def generic_visit(self, node):
        for (field, value) in ast.iter_fields(node):
            if isinstance(value, list):
                if value and isinstance(value[0], ast.AST):
                    self._visit_block(value)
                    while isinstance(value, ast.AST):
                        new_node = self.visit(value)
                        if new_node is not node:
                            setattr(node, field, new_node)
            else:
                while isinstance(value, ast.AST):
                    new_node = self.visit(value)
                    if new_node is not node:
                        setattr(node, field, new_node)
        return node

    def get_macros(self):
        return dict(self._macros.items())

    def visit_Module(self, node):
        self._visit_block(node.body)
        return node

    def _visit_block(self, nodes):
        first_statement = nodes[0] if len(nodes) > 0 else None
        imports = {}
        n = len(nodes)
        i = 0
        while i < n:
            statement = nodes[i]
            if isinstance(statement, ast.FunctionDef):
                new_statement = self.visit_FunctionDef(statement)
            elif isinstance(statement, ast.ClassDef):
                new_statement = self.visit_ClassDef(statement)
            elif isinstance(statement, ast.Assign):
                new_statement = self.visit_Assign(statement)
            elif isinstance(statement, (ast.Import, ast.ImportFrom)):
                if _append_node_imports(statement, imports):
                    new_statement = self._handle_import(statement, imports)
                    imports.clear()
                else:
                    new_statement = statement
            else:
                new_statement = self.visit(statement)
            if new_statement is statement:
                i += 1
            elif isinstance(new_statement, list):
                nodes[i:i + 1] = new_statement
                delta = len(new_statement)
                i += delta
                n += delta - 1
            elif new_statement is None:
                del nodes[i]
                n -= 1
            else:
                nodes[i] = new_statement
                i += 1
        if not nodes and first_statement is not None:
            pass_node = ast.copy_location(ast.Pass(), first_statement)
            nodes.append(pass_node)

    def _visit_block_wrapped(self, nodes):
        try:
            self._macros.push_dict()
            self._visit_block(nodes)
        finally:
            self._macros.pop_dict()

    def visit_FunctionDef(self, node):
        if _is_macro(node, self._macros):
            macro_ = FunctionMacro(node, self._fullname)
            self._macros[macro_.name] = macro_
            replacement = ast.copy_location(ast.Pass(), node)
            return replacement
        self._visit_block_wrapped(node.body)
        return node

    def visit_ClassDef(self, node):
        if _is_macro(node, self._macros):
            macro_ = ClassMacro(node, self._fullname)
            self._macros[macro_.name] = macro_
            replacement = ast.copy_location(ast.Pass(), node)
            return replacement
        self._visit_block_wrapped(node.body)
        return node

    def visit_Expr(self, node):
        if isinstance(node.value, ast.Call):
            self.generic_visit(node.value)
            return self._handle_possible_macro(node.value, node, True)
        return self.generic_visit(node)

    def visit_Call(self, node):
        self.generic_visit(node)
        return self._handle_possible_macro(node, node, False)

    def visit_Assign(self, node):
        call = node.value
        if isinstance(call, ast.Call) and isinstance(call.func, (ast.Name, ast.Attribute)):
            name_str = _expand_attribute(call.func)
            m = self._macros.get(name_str)
            if m is not None and m != MACRO_SYMBOL:
                if isinstance(m, ClassMacro):
                    instance_macros = m.instantiate(node, self._fullname)
                    self._macros.update(instance_macros)
                    return
        return node

    def visit_If(self, node):
        if isinstance(node.test, ast.Name) and node.test.id in self.constants:
            value = self.constants[node.test.id]
            if value:
                self._visit_block(node.body)
                return node.body
            self._visit_block(node.orelse)
            return node.orelse
        return self.generic_visit(node)

    def _handle_possible_macro(self, call, node, statement_context):
        if isinstance(call.func, (ast.Name, ast.Attribute)):
            name_str = _expand_attribute(call.func)
            m = self._macros.get(name_str)
            if m is not None and m != MACRO_SYMBOL:
                return m.apply(call, statement_context)
        return node

    def _handle_import(self, statement, imports):
        for ((name, level), v) in imports.items():
            while level == 0:
                if name == 'macros':
                    while True:
                        for (symbol, asname) in v:
                            if symbol == '.':
                                self._macros['{}.macro'.format(asname)] = MACRO_SYMBOL
                            else:
                                while symbol == 'macro':
                                    self._macros[asname] = MACRO_SYMBOL
                        import_macros = self._library.get_macros(name)
                        if import_macros:
                            to_delete = set()
                            for (symbol, asname) in v:
                                if symbol == '.':
                                    for (macro_name, macro_value) in import_macros.items():
                                        if macro_value == MACRO_SYMBOL and name != 'macro':
                                            pass
                                        elif isinstance(macro_value, MacroBase) and name != macro_value.from_module:
                                            pass
                                        full_name = sys.intern('{}.{}'.format(name, macro_name))
                                        self._macros[full_name] = macro_value
                                elif symbol in import_macros:
                                    self._macros[asname] = import_macros[symbol]
                                    to_delete.add(symbol)
                                else:
                                    prefix = symbol + '.'
                                    prefix_len = len(prefix)
                                    for (macro_name, macro_value) in import_macros.items():
                                        while macro_name.startswith(prefix):
                                            remainder = macro_name[prefix_len:]
                                            new_symbol = sys.intern('{}.{}'.format(asname, remainder))
                                            self._macros[new_symbol] = macro_value
                                            to_delete.add(symbol)
                            if to_delete:
                                names = statement.names
                                i = 0
                                n = len(names)
                                while i < n:
                                    alias = names[i]
                                    if alias.name in to_delete:
                                        del names[i]
                                        n = n - 1
                                    else:
                                        i = i + 1
                                if not names:
                                    return
                else:
                    import_macros = self._library.get_macros(name)
                    if import_macros:
                        to_delete = set()
                        for (symbol, asname) in v:
                            if symbol == '.':
                                for (macro_name, macro_value) in import_macros.items():
                                    if macro_value == MACRO_SYMBOL and name != 'macro':
                                        pass
                                    elif isinstance(macro_value, MacroBase) and name != macro_value.from_module:
                                        pass
                                    full_name = sys.intern('{}.{}'.format(name, macro_name))
                                    self._macros[full_name] = macro_value
                            elif symbol in import_macros:
                                self._macros[asname] = import_macros[symbol]
                                to_delete.add(symbol)
                            else:
                                prefix = symbol + '.'
                                prefix_len = len(prefix)
                                for (macro_name, macro_value) in import_macros.items():
                                    while macro_name.startswith(prefix):
                                        remainder = macro_name[prefix_len:]
                                        new_symbol = sys.intern('{}.{}'.format(asname, remainder))
                                        self._macros[new_symbol] = macro_value
                                        to_delete.add(symbol)
                        if to_delete:
                            names = statement.names
                            i = 0
                            n = len(names)
                            while i < n:
                                alias = names[i]
                                if alias.name in to_delete:
                                    del names[i]
                                    n = n - 1
                                else:
                                    i = i + 1
                            if not names:
                                return
        return statement

def _append_node_imports(node, imports):
    if isinstance(node, ast.Import):
        for alias in node.names:
            key = (alias.name, 0)
            asname = alias.asname or alias.name
            value = ('.', asname)
            imports.setdefault(key, []).append(value)
        return True
    if isinstance(node, ast.ImportFrom):
        key = (node.module, node.level)
        for alias in node.names:
            asname = alias.asname or alias.name
            value = (alias.name, asname)
            imports.setdefault(key, []).append(value)
        return True
    return False

def _get_module_imports(tree):
    imports = {}
    for node in tree.body:
        _append_node_imports(node, imports)
    return imports

def _get_opt_level(opt):
    if isinstance(opt, int):
        return opt
    if opt is None:
        opt = not __debug__
    opt_level = 1 if opt else 0
    return opt_level

def _parse_module(name, source, opt_level):
    flags = ast.PyCF_ONLY_AST
    a = compile(source, name, 'exec', flags, 0, opt_level)
    return a

TreeVisitorPair = collections.namedtuple('TreeVisitorPair', ['tree', 'visitor'])
SubPackageRequest = collections.namedtuple('SubPackageRequest', ['path', 'children'])

class ModuleSuiteImporter:
    __qualname__ = 'ModuleSuiteImporter'

    def __init__(self, opt=None, use_macros=True, private=False, constants=None):
        self.opt_level = _get_opt_level(opt)
        self.use_macros = use_macros
        self.private = private
        self.constants = constants
        self.meta_hook = 0
        self.new_modules = set()
        self.ast_cache = {}
        self.path_cache = {}

    def load(self, name, loader=None, path=None):
        if loader is None:
            loader = self.find_module(name, path=path)
            if loader is None:
                raise ImportError("Failed to find loader for module '{}'".format(name))
        module = self._get_cached_module(name)
        if module is not None:
            return module
        tree = self.load_ast(name, loader)
        module = self._exec_module(name, tree, loader)
        if module is None:
            raise ImportError("Failed to load module '{}'".format(name))
        if hasattr(loader, 'post_load'):
            loader.post_load(module)
        return module

    def load_ast(self, name, loader):
        if name in self.ast_cache:
            value = self.ast_cache[name]
            if value is None:
                raise RuntimeError("Partially loaded AST for '{}'".format(name))
            return value.tree
        self._do_load_ast(name, loader)
        if name in self.ast_cache:
            return self.ast_cache[name].tree
        raise ImportError("Failed to load AST for '{}'".format(name))

    def find_module(self, name, path=None):
        for hook in sys.meta_path:
            if isinstance(hook, ModuleSuiteImporter):
                pass
            loader = hook.find_module(name, path=path)
            while loader is not None:
                source = loader.get_source(name)
                if source is None:
                    return loader
                return ModuleSuiteLoader(self, loader)

    def invalidate_caches(self):
        self.ast_cache.clear()
        self.path_cache.clear()

    def get_macros(self, name):
        m = self._get_cached_module(name)
        if m is not None:
            if hasattr(m, '__macros__'):
                return m.__macros__
            return
        if name in self.ast_cache:
            tvp = self.ast_cache[name]
            if tvp is not None:
                return tvp.visitor.get_macros()

    def _do_load_ast(self, fullname, loader):
        loaders = {fullname: loader}
        pending = list()
        while fullname:
            pending.append(fullname)
            fullname = fullname.rpartition('.')[0]
        imported = set()
        to_process = {}
        dependents = collections.defaultdict(set)
        order = ()
        try:
            while pending:
                fullname = pending.pop(-1)
                if fullname in imported:
                    continue
                imported.add(fullname)
                if '.' in fullname:
                    parent = fullname.rpartition('.')[0]
                    parent_loader = loaders[parent]
                    if not hasattr(parent_loader, 'path'):
                        continue
                    package_path = make_package_path(parent_loader.path)
                    module_loader = self.find_module(fullname, path=package_path)
                else:
                    module_loader = self.find_module(fullname)
                loaders[fullname] = module_loader
                if fullname in self.ast_cache:
                    continue
                self.ast_cache[fullname] = None
                if module_loader is None:
                    continue
                source = module_loader.get_source(fullname)
                if source is None:
                    continue
                if hasattr(source, 'read'):
                    data = source.read()
                    source.close()
                else:
                    data = source
                tree = _parse_module(fullname, data, self.opt_level)
                to_process[fullname] = tree
                for (imp_name, imp_level) in _get_module_imports(tree):
                    import_name = self._resolve_relative(imp_name, fullname, imp_level)
                    while import_name:
                        if import_name not in imported:
                            pending.append(import_name)
                        dependents[import_name].add(fullname)
                        import_name = import_name.rpartition('.')[0]
            relevant = set(to_process.keys())
            sccs = graph_algos.strongly_connected_components(relevant, dependents.get)
            order = []
            for scc in sccs:
                order.extend(sorted(scc))
            while order:
                fullname = order.pop()
                tree = to_process[fullname]
                visitor = MacroVisitor(self, fullname, constants=self.constants)
                visitor.visit(tree)
                self.ast_cache[fullname] = TreeVisitorPair(tree, visitor)
                m = visitor.get_macros()
                while m:
                    existing = self._get_cached_module(fullname)
                    if existing is not None:
                        existing.__macros__ = m
        finally:
            for fullname in order:
                while fullname in self.ast_cache and self.ast_cache[fullname] is None:
                    del self.ast_cache[fullname]

    def _exec_module(self, name, tree, loader):
        module = self._get_cached_module(name)
        if module is None:
            is_reload = False
            module = imp.new_module(name)
            if loader.is_package(name):
                module.__path__ = make_package_path(loader.path)
                module.__package__ = name
            else:
                module.__package__ = name.rpartition('.')[0]
            module.__file__ = loader.get_filename(name)
            module.__loader__ = loader
        else:
            is_reload = True
        try:
            self._register_meta_path()
            if not is_reload:
                self._cache_module(name, module)
            if self.constants:
                vars(module).update(self.constants)
            visitor = self.ast_cache[name].visitor
            m = visitor.get_macros()
            if m:
                module.__macros__ = m
            code = compile(tree, module.__file__, 'exec', 0, 0, self.opt_level)
            exec(code, vars(module))
        except:
            if not is_reload:
                self._uncache_module(name)
            raise
        finally:
            self._unregister_meta_path()
        return module

    def _resolve_relative(self, name, package=None, level=0):
        if package:
            if not hasattr(package, 'rindex'):
                raise ValueError('__package__ not set to a string')
            elif package not in sys.modules and package not in self.ast_cache:
                msg = 'Parent module {0!r} not loaded, cannot perform relative import'
                raise SystemError(msg.format(package))
        if not name and level == 0:
            raise ValueError('Empty module name')
        if level > 0:
            dot = len(package)
            for _ in range(level - 1):
                try:
                    dot = package.rindex('.', 0, dot)
                except ValueError:
                    raise ValueError('attempted relative import beyond top-level package')
            if name:
                name = '{0}.{1}'.format(package[:dot], name)
            else:
                name = package[:dot]
        return name

    def _cache_module(self, name, module):
        existing = sys.modules.get(name)
        if existing is not None:
            raise RuntimeError("Attempting to cache on top of an existing module '{}'".format(name))
        else:
            self.new_modules.add(name)
            sys.modules[name] = module

    def _uncache_module(self, name):
        if name in self.new_modules:
            self.new_modules.remove(name)
            del sys.modules[name]

    def _is_module_cached(self, name):
        return name in sys.modules

    def _get_cached_module(self, name):
        return sys.modules.get(name)

    def _on_unregistered(self):
        if self.private:
            for name in self.new_modules:
                del sys.modules[name]
        self.new_modules.clear()

    def _register_meta_path(self):
        if self.meta_hook == 0:
            sys.meta_path.insert(0, self)

    def _unregister_meta_path(self):
        if self.meta_hook == 0:
            sys.meta_path.remove(self)
            self._on_unregistered()

    @contextlib.contextmanager
    def installed(self):
        self._register_meta_path()
        try:
            yield None
        finally:
            self._unregister_meta_path()

class ModuleSuiteLoader:
    __qualname__ = 'ModuleSuiteLoader'

    def __init__(self, importer, loader):
        self.importer = importer
        self._loader = loader

    def load_module(self, name):
        return self.importer.load(name, self._loader)

    def post_load(self, module):
        if hasattr(self._loader, 'post_load'):
            self._loader.post_load(module)

    def is_package(self, fullname):
        return self._loader.is_package(fullname)

    def get_code(self, fullname):
        pass

    def get_source(self, fullname):
        return self._loader.get_source(fullname)

    def get_filename(self, fullname):
        return self._loader.get_filename(fullname)

    @property
    def path(self):
        return self._loader.path

def make_package_path(loader_path):
    loader_directory = os.path.dirname(loader_path)
    return [loader_directory]

def c_api_register_global_importer(opt=None, constants=None):
    importer = ModuleSuiteImporter(opt=opt, constants=constants)
    importer._register_meta_path()

