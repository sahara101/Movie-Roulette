import importlib
import sys

def reload_service(module_name):
    """Reload a service module and reinitialize it"""
    if module_name in sys.modules:
        del sys.modules[module_name]
    module = importlib.import_module(module_name)
    if hasattr(module, 'initialize_seerr'):
        module.initialize_seerr()
    if hasattr(module, 'initialize_trakt'):
        module.initialize_trakt()
    return module
