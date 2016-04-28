#ERROR: jaddr is None
import re
import sims4.log
import paths
logger = sims4.log.Logger('Importer')

def _partial_path_to_module_fqn(partial_path):
    if partial_path.endswith('__init__'):
        partial_path = partial_path[:-len('__init__')]
    fqn = partial_path.translate(str.maketrans('\\/', '..'))
    fqn = fqn.strip('.')
    return fqn

def import_modules():
    error_count = 0
    for script_root in paths.USER_SCRIPT_ROOTS:
        error_count += import_modules_by_path(script_root)
    return error_count

def module_names_gen(_path):
    import sys
    import os
    import zipfile
    py_re = re.compile('.+\\.py$')
    zip_index = _path.find('.zip')
    if zip_index != -1:
        compiled = True
        py_re = re.compile('.+\\.py[co]$')
        zip_name = _path[0:zip_index + 4]
        local_path = _path[zip_index + 5:]
        archive = zipfile.ZipFile(zip_name)
        if local_path:
            files = [f for f in archive.namelist() if py_re.match(f)]
        else:
            files = [f for f in archive.namelist() if py_re.match(f)]
        for filename in files:
            if compiled:
                filename = filename[:-4]
            else:
                filename = filename[:-3]
            module_fqn = _partial_path_to_module_fqn(filename)
            yield (filename, module_fqn)
    else:
        compiled = False
        py_re = re.compile('.+\\.py$')
        prefix_list = sorted([os.path.commonprefix([os.path.abspath(m), _path]) for m in sys.path if _path.startswith(os.path.abspath(m))], key=len, reverse=True)
        if not prefix_list:
            logger.error('Path {0} must be under sys.path: {1}', _path, sys.path)
            return
        prefix = prefix_list[0]
        local_path = os.path.relpath(_path, prefix)
        files = []
        for (dirpath, _, filenames) in os.walk(_path):
            relative = os.path.join(local_path, os.path.relpath(dirpath, _path))
            relative = os.path.normpath(relative)
            for filename in filenames:
                while py_re.match(filename):
                    files.append((dirpath, relative, filename))
        for (dirpath, relative, filename) in files:
            if compiled:
                filename = filename[:-4]
            else:
                filename = filename[:-3]
            module_filename = os.path.join(dirpath, filename)
            module_name = os.path.join(relative, filename)
            module_fqn = _partial_path_to_module_fqn(module_name)
            yield (module_filename, module_fqn)

def import_modules_by_path(_path):
    import builtins
    ignored_modules = set()
    error_count = 0
    for (module_name, module_fqn) in module_names_gen(_path):
        try:
            builtins.__import__(module_fqn)
            ignored_modules.add(module_fqn)
        except Exception:
            logger.exception("  Failure: '{0}' ({1})", module_name, module_fqn)
            error_count += 1
    return error_count

