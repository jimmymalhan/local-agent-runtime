"""Plugin system with dynamic loading, interface validation, and hook registration."""

import importlib
import importlib.util
import os
import sys
from pathlib import Path
from typing import Any, Callable, Protocol, runtime_checkable


@runtime_checkable
class PluginProtocol(Protocol):
    name: str
    version: str
    hooks: dict[str, Callable]


class PluginManager:
    """Discovers plugins in a directory, loads them dynamically, validates interface, registers hooks."""

    def __init__(self, plugin_dir: str = "plugins"):
        self.plugin_dir = Path(plugin_dir)
        self._plugins: dict[str, PluginProtocol] = {}
        self._hooks: dict[str, list[Callable]] = {}

    @property
    def plugins(self) -> dict[str, Any]:
        return dict(self._plugins)

    @property
    def hooks(self) -> dict[str, list[Callable]]:
        return dict(self._hooks)

    def discover(self) -> list[str]:
        """Find all .py plugin files in the plugin directory."""
        if not self.plugin_dir.is_dir():
            return []
        return [
            f.stem
            for f in sorted(self.plugin_dir.iterdir())
            if f.suffix == ".py" and f.name != "__init__.py"
        ]

    def _load_module(self, module_name: str):
        """Dynamically load a Python module from the plugin directory."""
        file_path = self.plugin_dir / f"{module_name}.py"
        if not file_path.exists():
            raise FileNotFoundError(f"Plugin file not found: {file_path}")
        spec = importlib.util.spec_from_file_location(
            f"plugins.{module_name}", str(file_path)
        )
        if spec is None or spec.loader is None:
            raise ImportError(f"Cannot create module spec for {file_path}")
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        return module

    def _validate_plugin(self, plugin: Any) -> bool:
        """Validate that a plugin object has required attributes: name, version, hooks."""
        if not hasattr(plugin, "name") or not isinstance(plugin.name, str):
            return False
        if not hasattr(plugin, "version") or not isinstance(plugin.version, str):
            return False
        if not hasattr(plugin, "hooks") or not isinstance(plugin.hooks, dict):
            return False
        for key, val in plugin.hooks.items():
            if not isinstance(key, str) or not callable(val):
                return False
        return True

    def _register_hooks(self, plugin: PluginProtocol):
        """Register all hooks from a validated plugin."""
        for hook_name, callback in plugin.hooks.items():
            self._hooks.setdefault(hook_name, []).append(callback)

    def load_plugin(self, module_name: str) -> Any:
        """Load a single plugin by module name, validate it, and register its hooks."""
        module = self._load_module(module_name)
        # Look for a `plugin` attribute or a `Plugin` class to instantiate
        plugin_obj = None
        if hasattr(module, "plugin"):
            plugin_obj = module.plugin
        elif hasattr(module, "Plugin"):
            plugin_obj = module.Plugin()
        else:
            raise AttributeError(
                f"Module '{module_name}' has no 'plugin' instance or 'Plugin' class"
            )

        if not self._validate_plugin(plugin_obj):
            raise TypeError(
                f"Plugin '{module_name}' does not satisfy the plugin protocol "
                f"(requires: name: str, version: str, hooks: dict[str, callable])"
            )

        self._plugins[plugin_obj.name] = plugin_obj
        self._register_hooks(plugin_obj)
        return plugin_obj

    def load_all(self) -> list[str]:
        """Discover and load all plugins. Returns list of loaded plugin names."""
        loaded = []
        for module_name in self.discover():
            try:
                p = self.load_plugin(module_name)
                loaded.append(p.name)
            except (AttributeError, TypeError, ImportError, FileNotFoundError) as e:
                print(f"Skipping plugin '{module_name}': {e}")
        return loaded

    def call_hook(self, hook_name: str, *args, **kwargs) -> list[Any]:
        """Invoke all registered callbacks for a given hook name."""
        results = []
        for callback in self._hooks.get(hook_name, []):
            results.append(callback(*args, **kwargs))
        return results

    def unload_plugin(self, plugin_name: str) -> bool:
        """Unload a plugin and remove its hooks."""
        plugin = self._plugins.pop(plugin_name, None)
        if plugin is None:
            return False
        for hook_name, callback in plugin.hooks.items():
            if hook_name in self._hooks:
                self._hooks[hook_name] = [
                    cb for cb in self._hooks[hook_name] if cb is not callback
                ]
                if not self._hooks[hook_name]:
                    del self._hooks[hook_name]
        return True


if __name__ == "__main__":
    import tempfile
    import shutil

    # --- Setup: create a temp plugins directory with sample plugins ---
    tmp_dir = tempfile.mkdtemp()
    plugins_dir = os.path.join(tmp_dir, "plugins")
    os.makedirs(plugins_dir)

    # Plugin A: uses a module-level `plugin` instance
    plugin_a_code = '''\
class _PluginA:
    name = "alpha"
    version = "1.0.0"

    def __init__(self):
        self.hooks = {
            "on_start": self.on_start,
            "on_data": self.on_data,
        }

    def on_start(self):
        return "alpha started"

    def on_data(self, data):
        return f"alpha got {data}"

plugin = _PluginA()
'''

    # Plugin B: uses a `Plugin` class (instantiated by manager)
    plugin_b_code = '''\
class Plugin:
    name = "beta"
    version = "2.3.1"

    def __init__(self):
        self.hooks = {
            "on_start": self.on_start,
            "on_stop": self.on_stop,
        }

    def on_start(self):
        return "beta started"

    def on_stop(self):
        return "beta stopped"
'''

    # Plugin C: invalid (missing version)
    plugin_c_code = '''\
class Plugin:
    name = "gamma"
    hooks = {}
'''

    with open(os.path.join(plugins_dir, "alpha_plugin.py"), "w") as f:
        f.write(plugin_a_code)
    with open(os.path.join(plugins_dir, "beta_plugin.py"), "w") as f:
        f.write(plugin_b_code)
    with open(os.path.join(plugins_dir, "bad_plugin.py"), "w") as f:
        f.write(plugin_c_code)

    # --- Test 1: discover finds all .py files ---
    pm = PluginManager(plugins_dir)
    discovered = pm.discover()
    assert set(discovered) == {"alpha_plugin", "beta_plugin", "bad_plugin"}, (
        f"Discovery failed: {discovered}"
    )

    # --- Test 2: load_all loads valid plugins, skips invalid ---
    loaded = pm.load_all()
    assert "alpha" in loaded, f"alpha not loaded: {loaded}"
    assert "beta" in loaded, f"beta not loaded: {loaded}"
    assert "gamma" not in loaded, f"gamma should have been skipped: {loaded}"
    assert len(loaded) == 2, f"Expected 2 loaded, got {len(loaded)}"

    # --- Test 3: plugins dict is correct ---
    assert "alpha" in pm.plugins
    assert "beta" in pm.plugins
    assert pm.plugins["alpha"].version == "1.0.0"
    assert pm.plugins["beta"].version == "2.3.1"

    # --- Test 4: hooks are registered correctly ---
    assert "on_start" in pm.hooks
    assert len(pm.hooks["on_start"]) == 2  # alpha + beta
    assert "on_data" in pm.hooks
    assert len(pm.hooks["on_data"]) == 1  # alpha only
    assert "on_stop" in pm.hooks
    assert len(pm.hooks["on_stop"]) == 1  # beta only

    # --- Test 5: call_hook invokes all registered callbacks ---
    start_results = pm.call_hook("on_start")
    assert "alpha started" in start_results
    assert "beta started" in start_results

    data_results = pm.call_hook("on_data", "hello")
    assert data_results == ["alpha got hello"]

    stop_results = pm.call_hook("on_stop")
    assert stop_results == ["beta stopped"]

    # --- Test 6: calling a non-existent hook returns empty ---
    assert pm.call_hook("on_nonexistent") == []

    # --- Test 7: unload_plugin removes plugin and its hooks ---
    assert pm.unload_plugin("alpha") is True
    assert "alpha" not in pm.plugins
    assert len(pm.hooks.get("on_start", [])) == 1  # only beta remains
    assert "on_data" not in pm.hooks  # alpha was the only provider

    # --- Test 8: unloading unknown plugin returns False ---
    assert pm.unload_plugin("nonexistent") is False

    # --- Test 9: load a single plugin by module name ---
    pm2 = PluginManager(plugins_dir)
    p = pm2.load_plugin("alpha_plugin")
    assert p.name == "alpha"
    assert pm2.call_hook("on_start") == ["alpha started"]

    # --- Test 10: validation rejects invalid plugins ---
    try:
        pm2.load_plugin("bad_plugin")
        assert False, "Should have raised TypeError for invalid plugin"
    except TypeError as e:
        assert "bad_plugin" in str(e)

    # --- Cleanup ---
    shutil.rmtree(tmp_dir)

    print("All assertions passed.")
