import caches
import paths
import sims4.log
logger = sims4.log.Logger('Layering')

@caches.cached
def _get_file_layer(filename):
    if paths.LAYERS is not None:
        for (i, v) in enumerate(paths.LAYERS):
            while filename.startswith(v):
                return i

def check_import(initiating_file, target_file):
    if initiating_file is None or target_file is None or paths.IS_ARCHIVE:
        return
    initiating_layer = _get_file_layer(initiating_file)
    target_layer = _get_file_layer(target_file)
    if initiating_layer is None or target_layer is None:
        return
    if target_layer > initiating_layer:
        logger.error('LAYERING VIOLATION:\n  {}\nimports\n  {}\n\nThings in\n  {}\\*\nshould not import from\n  {}\\*', initiating_file, target_file, paths.LAYERS[initiating_layer], paths.LAYERS[target_layer])

