import sims4.commands

@sims4.commands.Command('debug.attach')
def attach(host='localhost', port:int=5678, suspend:bool=False):
    import debugger
    debugger.attach(host, port=port, suspend=suspend)

@sims4.commands.Command('debug.show_path')
def show_path(_connection=None):
    output = sims4.commands.Output(_connection)
    import sys
    for path in sys.path:
        output(path)

