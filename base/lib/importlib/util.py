from _bootstrap import module_for_loader
from _bootstrap import set_loader
from _bootstrap import set_package
from _bootstrap import _resolve_name

def resolve_name(name, package):
    if not name.startswith('.'):
        return name
    if not package:
        raise ValueError('{!r} is not a relative name (no leading dot)'.format(name))
    level = 0
    for character in name:
        if character != '.':
            break
        level += 1
    return _resolve_name(name[level:], package, level)

