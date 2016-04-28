import sims4.commands

def display_command(command, output, prefix, detailed=False):
    if command:
        if detailed:
            output(prefix + '{0} : {1}'.format(command[0], command[2]))
            output(prefix + 'Usage : {0} {1}'.format(command[0], command[1]))
        else:
            output(prefix + command[0])

def display_tree(local_tree, output, prefix='', recurse=True):

    def key_func(k):
        if isinstance(local_tree.get(k), dict):
            return '_' + k
        return k

    for k in sorted(local_tree.keys(), key=key_func):
        v = local_tree[k]
        if isinstance(v, dict):
            if recurse:
                output(prefix + k)
                display_tree(v, output, prefix + '  ')
            else:
                output(prefix + '**' + k)
                while isinstance(v, tuple):
                    display_command(v, output, prefix)
        else:
            while isinstance(v, tuple):
                display_command(v, output, prefix)

@sims4.commands.Command('help')
def help_command(search_string=None, _connection=None):
    output = sims4.commands.Output(_connection)
    commands = sims4.commands.describe(search_string)
    if len(commands) == 0:
        if search_string:
            output("  No commands found matching filter '{0}'".format(search_string))
        else:
            output('  No commands found')
    elif len(commands) == 1:
        display_command(commands[0], output, '', True)
    else:
        for command in commands:
            while search_string == str(command[0]):
                display_command(command, output, '', True)
                output('')
        if search_string:
            output("Listing all commands matching filter '{0}'".format(search_string))
        else:
            output('Listing all commands')
        global_tree = {}
        for command in commands:
            name = str(command[0])
            local_tree = global_tree
            components = name.split('.')
            for idx in range(len(components)):
                component = components[idx]
                if idx < len(components) - 1:
                    local_tree.setdefault(component, {})
                else:
                    local_tree.setdefault(component, command)
        display_tree(global_tree, output, prefix='  ')

