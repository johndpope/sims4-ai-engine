import os

def configure_app_paths(pathroot, from_archive, user_script_roots, layers):
    if not from_archive:
        server_path = os.path.join(pathroot, 'Scripts', 'Server')
    else:
        server_path = os.path.join(pathroot, 'Gameplay', 'simulation.zip')
    user_script_roots.append(server_path)
    layers.append(server_path)

