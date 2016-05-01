RELOADER_ENABLED = False
__enable_gc_callback = True
import gc
try:
    import _profile
except:
    __enable_gc_callback = False


def system_init(gameplay):
    import sims4.importer
    sims4.importer.enable()
    try:
        import debugger
        debugger.initialize()
    except ImportError:
        pass
    print('Server Startup')
    if __enable_gc_callback:
        gc.callbacks.append(_profile.notify_gc_function)


def system_shutdown():
    global RELOADER_ENABLED
    import sims4.importer
    sims4.importer.disable()
    RELOADER_ENABLED = False
