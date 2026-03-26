"""
Plugin architecture for a text editor.

Components:
- Plugin (abstract interface)
- HookRegistry (event system for intercept points)
- PluginHost (manages plugin lifecycle and dispatches hooks)
- PluginLoader (discovers and loads plugins by class or module path)
- Buffer (simple text buffer that plugins can modify)
- CommandRegistry (plugins register named commands)
- FileTypeRegistry (plugins register handlers for file extensions)
"""

from __future__ import annotations

import abc
import importlib
import enum
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Set, Tuple


# ---------------------------------------------------------------------------
# Hook system
# ---------------------------------------------------------------------------

class Hook(enum.Enum):
    """Built-in hook points that plugins can subscribe to."""
    KEYSTROKE = "keystroke"
    BEFORE_BUFFER_CHANGE = "before_buffer_change"
    AFTER_BUFFER_CHANGE = "after_buffer_change"
    BUFFER_SAVE = "buffer_save"
    BUFFER_LOAD = "buffer_load"
    COMMAND_EXECUTE = "command_execute"
    PLUGIN_LOADED = "plugin_loaded"
    PLUGIN_UNLOADED = "plugin_unloaded"


@dataclass
class HookEvent:
    """Payload passed to hook callbacks."""
    hook: Hook
    data: Dict[str, Any] = field(default_factory=dict)
    cancelled: bool = False

    def cancel(self) -> None:
        self.cancelled = True


# Callback signature: (HookEvent) -> Optional[HookEvent]
HookCallback = Callable[[HookEvent], Optional[HookEvent]]


class HookRegistry:
    """Central registry that maps hooks to ordered callback lists."""

    def __init__(self) -> None:
        self._callbacks: Dict[Hook, List[Tuple[int, str, HookCallback]]] = {
            h: [] for h in Hook
        }

    def subscribe(
        self,
        hook: Hook,
        callback: HookCallback,
        plugin_name: str = "",
        priority: int = 100,
    ) -> None:
        self._callbacks[hook].append((priority, plugin_name, callback))
        self._callbacks[hook].sort(key=lambda t: t[0])

    def unsubscribe_all(self, plugin_name: str) -> None:
        for hook in Hook:
            self._callbacks[hook] = [
                (p, n, cb) for p, n, cb in self._callbacks[hook] if n != plugin_name
            ]

    def dispatch(self, event: HookEvent) -> HookEvent:
        for _priority, _name, callback in self._callbacks[event.hook]:
            if event.cancelled:
                break
            result = callback(event)
            if result is not None:
                event = result
        return event

    def subscriber_count(self, hook: Hook) -> int:
        return len(self._callbacks[hook])


# ---------------------------------------------------------------------------
# Buffer
# ---------------------------------------------------------------------------

class Buffer:
    """Simple gap-buffer-style text buffer (list of lines)."""

    def __init__(self, text: str = "", filename: str = "untitled") -> None:
        self.filename = filename
        self._lines: List[str] = text.split("\n") if text else [""]
        self._hook_registry: Optional[HookRegistry] = None

    def attach_hooks(self, registry: HookRegistry) -> None:
        self._hook_registry = registry

    def _fire(self, hook: Hook, **data: Any) -> HookEvent:
        if self._hook_registry is None:
            return HookEvent(hook=hook, data=data)
        return self._hook_registry.dispatch(HookEvent(hook=hook, data=data))

    @property
    def text(self) -> str:
        return "\n".join(self._lines)

    @property
    def line_count(self) -> int:
        return len(self._lines)

    def get_line(self, index: int) -> str:
        return self._lines[index]

    def set_line(self, index: int, content: str) -> None:
        event = self._fire(
            Hook.BEFORE_BUFFER_CHANGE,
            action="set_line",
            line=index,
            old=self._lines[index],
            new=content,
        )
        if event.cancelled:
            return
        content = event.data.get("new", content)
        self._lines[index] = content
        self._fire(Hook.AFTER_BUFFER_CHANGE, action="set_line", line=index)

    def insert_line(self, index: int, content: str) -> None:
        event = self._fire(
            Hook.BEFORE_BUFFER_CHANGE,
            action="insert_line",
            line=index,
            new=content,
        )
        if event.cancelled:
            return
        content = event.data.get("new", content)
        self._lines.insert(index, content)
        self._fire(Hook.AFTER_BUFFER_CHANGE, action="insert_line", line=index)

    def delete_line(self, index: int) -> str:
        event = self._fire(
            Hook.BEFORE_BUFFER_CHANGE,
            action="delete_line",
            line=index,
            old=self._lines[index],
        )
        if event.cancelled:
            return self._lines[index]
        removed = self._lines.pop(index)
        if not self._lines:
            self._lines = [""]
        self._fire(Hook.AFTER_BUFFER_CHANGE, action="delete_line", line=index)
        return removed

    def insert_text(self, line: int, col: int, text: str) -> None:
        old = self._lines[line]
        new = old[:col] + text + old[col:]
        self.set_line(line, new)

    def save(self) -> str:
        event = self._fire(Hook.BUFFER_SAVE, filename=self.filename, text=self.text)
        if event.cancelled:
            return ""
        return event.data.get("text", self.text)

    def load(self, text: str, filename: str = "") -> None:
        if filename:
            self.filename = filename
        event = self._fire(Hook.BUFFER_LOAD, filename=self.filename, text=text)
        if event.cancelled:
            return
        text = event.data.get("text", text)
        self._lines = text.split("\n") if text else [""]


# ---------------------------------------------------------------------------
# Command & FileType registries
# ---------------------------------------------------------------------------

CommandHandler = Callable[["PluginHost", List[str]], Any]


class CommandRegistry:
    """Named commands that plugins can register and invoke."""

    def __init__(self) -> None:
        self._commands: Dict[str, Tuple[str, CommandHandler]] = {}

    def register(self, name: str, handler: CommandHandler, plugin_name: str = "") -> None:
        self._commands[name] = (plugin_name, handler)

    def unregister_all(self, plugin_name: str) -> None:
        self._commands = {
            k: v for k, v in self._commands.items() if v[0] != plugin_name
        }

    def execute(self, name: str, host: "PluginHost", args: List[str] | None = None) -> Any:
        if name not in self._commands:
            raise KeyError(f"Unknown command: {name}")
        _, handler = self._commands[name]
        return handler(host, args or [])

    def list_commands(self) -> List[str]:
        return sorted(self._commands.keys())

    def has(self, name: str) -> bool:
        return name in self._commands


FileTypeHandler = Callable[[Buffer], None]


class FileTypeRegistry:
    """Maps file extensions to handler callbacks."""

    def __init__(self) -> None:
        self._handlers: Dict[str, List[Tuple[str, FileTypeHandler]]] = {}

    def register(self, extension: str, handler: FileTypeHandler, plugin_name: str = "") -> None:
        ext = extension if extension.startswith(".") else f".{extension}"
        self._handlers.setdefault(ext, []).append((plugin_name, handler))

    def unregister_all(self, plugin_name: str) -> None:
        for ext in self._handlers:
            self._handlers[ext] = [
                (n, h) for n, h in self._handlers[ext] if n != plugin_name
            ]

    def handle(self, extension: str, buf: Buffer) -> None:
        ext = extension if extension.startswith(".") else f".{extension}"
        for _name, handler in self._handlers.get(ext, []):
            handler(buf)

    def supported_extensions(self) -> Set[str]:
        return {ext for ext, handlers in self._handlers.items() if handlers}


# ---------------------------------------------------------------------------
# Plugin interface
# ---------------------------------------------------------------------------

class Plugin(abc.ABC):
    """Abstract base class every plugin must implement."""

    @property
    @abc.abstractmethod
    def name(self) -> str:
        """Unique plugin identifier."""

    @property
    def version(self) -> str:
        return "0.0.0"

    @property
    def description(self) -> str:
        return ""

    @abc.abstractmethod
    def activate(self, host: "PluginHost") -> None:
        """Called when the plugin is loaded. Register hooks/commands here."""

    def deactivate(self, host: "PluginHost") -> None:
        """Called when the plugin is unloaded. Cleanup if needed."""

    def on_keystroke(self, key: str, buffer: Buffer) -> Optional[str]:
        """Override to intercept keystrokes. Return modified key or None to consume it."""
        return key


# ---------------------------------------------------------------------------
# PluginHost
# ---------------------------------------------------------------------------

class PluginHost:
    """
    Central coordinator that owns registries, manages plugins,
    and dispatches events.
    """

    def __init__(self) -> None:
        self.hooks = HookRegistry()
        self.commands = CommandRegistry()
        self.file_types = FileTypeRegistry()
        self._plugins: Dict[str, Plugin] = {}
        self._active_buffer: Optional[Buffer] = None

    # -- buffer management --

    def create_buffer(self, text: str = "", filename: str = "untitled") -> Buffer:
        buf = Buffer(text, filename)
        buf.attach_hooks(self.hooks)
        self._active_buffer = buf
        ext = self._extension_of(filename)
        if ext:
            self.file_types.handle(ext, buf)
        return buf

    @property
    def active_buffer(self) -> Optional[Buffer]:
        return self._active_buffer

    @staticmethod
    def _extension_of(filename: str) -> str:
        dot = filename.rfind(".")
        if dot == -1:
            return ""
        return filename[dot:]

    # -- plugin lifecycle --

    def load_plugin(self, plugin: Plugin) -> None:
        if plugin.name in self._plugins:
            raise ValueError(f"Plugin already loaded: {plugin.name}")
        self._plugins[plugin.name] = plugin
        plugin.activate(self)
        self.hooks.dispatch(
            HookEvent(hook=Hook.PLUGIN_LOADED, data={"plugin": plugin.name})
        )

    def unload_plugin(self, name: str) -> None:
        plugin = self._plugins.pop(name, None)
        if plugin is None:
            raise KeyError(f"Plugin not loaded: {name}")
        plugin.deactivate(self)
        self.hooks.unsubscribe_all(name)
        self.commands.unregister_all(name)
        self.file_types.unregister_all(name)
        self.hooks.dispatch(
            HookEvent(hook=Hook.PLUGIN_UNLOADED, data={"plugin": name})
        )

    def get_plugin(self, name: str) -> Optional[Plugin]:
        return self._plugins.get(name)

    @property
    def loaded_plugins(self) -> List[str]:
        return sorted(self._plugins.keys())

    # -- keystroke dispatch --

    def send_keystroke(self, key: str) -> Optional[str]:
        event = self.hooks.dispatch(
            HookEvent(hook=Hook.KEYSTROKE, data={"key": key})
        )
        if event.cancelled:
            return None
        key = event.data.get("key", key)
        for plugin in self._plugins.values():
            result = plugin.on_keystroke(key, self._active_buffer or Buffer())
            if result is None:
                return None
            key = result
        return key

    # -- command shortcut --

    def run_command(self, name: str, args: List[str] | None = None) -> Any:
        return self.commands.execute(name, self, args)


# ---------------------------------------------------------------------------
# PluginLoader — discover / load plugins by class or dotted module path
# ---------------------------------------------------------------------------

class PluginLoader:
    """Utility for discovering and instantiating Plugin subclasses."""

    @staticmethod
    def from_class(cls: type, host: PluginHost) -> Plugin:
        if not issubclass(cls, Plugin):
            raise TypeError(f"{cls} is not a Plugin subclass")
        instance = cls()
        host.load_plugin(instance)
        return instance

    @staticmethod
    def from_module_path(dotted_path: str, class_name: str, host: PluginHost) -> Plugin:
        module = importlib.import_module(dotted_path)
        cls = getattr(module, class_name)
        return PluginLoader.from_class(cls, host)

    @staticmethod
    def from_classes(classes: List[type], host: PluginHost) -> List[Plugin]:
        return [PluginLoader.from_class(c, host) for c in classes]


# ===================================================================
# Example plugins (used by __main__ assertions)
# ===================================================================

class AutoSavePlugin(Plugin):
    """Tracks buffer changes and exposes a 'save' command."""

    @property
    def name(self) -> str:
        return "autosave"

    @property
    def version(self) -> str:
        return "1.0.0"

    @property
    def description(self) -> str:
        return "Tracks changes and provides a save command."

    def __init__(self) -> None:
        self.change_count = 0
        self.last_saved: str = ""

    def activate(self, host: PluginHost) -> None:
        host.hooks.subscribe(
            Hook.AFTER_BUFFER_CHANGE,
            self._on_change,
            plugin_name=self.name,
            priority=50,
        )
        host.commands.register("save", self._cmd_save, plugin_name=self.name)

    def _on_change(self, event: HookEvent) -> Optional[HookEvent]:
        self.change_count += 1
        return event

    def _cmd_save(self, host: PluginHost, args: List[str]) -> str:
        buf = host.active_buffer
        if buf is None:
            return "no buffer"
        self.last_saved = buf.save()
        self.change_count = 0
        return self.last_saved


class LineNumberPlugin(Plugin):
    """Intercepts save to prepend line numbers."""

    @property
    def name(self) -> str:
        return "line_numbers"

    def activate(self, host: PluginHost) -> None:
        host.hooks.subscribe(
            Hook.BUFFER_SAVE,
            self._on_save,
            plugin_name=self.name,
            priority=10,
        )

    def _on_save(self, event: HookEvent) -> Optional[HookEvent]:
        text: str = event.data.get("text", "")
        lines = text.split("\n")
        numbered = "\n".join(f"{i + 1}: {l}" for i, l in enumerate(lines))
        event.data["text"] = numbered
        return event


class UppercaseKeystrokePlugin(Plugin):
    """Converts every keystroke to uppercase via on_keystroke."""

    @property
    def name(self) -> str:
        return "uppercase_keys"

    def activate(self, host: PluginHost) -> None:
        pass  # uses on_keystroke override instead of hooks

    def on_keystroke(self, key: str, buffer: Buffer) -> Optional[str]:
        return key.upper()


class KeystrokeLoggerPlugin(Plugin):
    """Logs keystrokes via the hook system (not on_keystroke)."""

    @property
    def name(self) -> str:
        return "keystroke_logger"

    def __init__(self) -> None:
        self.log: List[str] = []

    def activate(self, host: PluginHost) -> None:
        host.hooks.subscribe(
            Hook.KEYSTROKE,
            self._on_key,
            plugin_name=self.name,
        )

    def _on_key(self, event: HookEvent) -> Optional[HookEvent]:
        self.log.append(event.data.get("key", ""))
        return event


class MarkdownPlugin(Plugin):
    """Registers a file-type handler for .md files."""

    @property
    def name(self) -> str:
        return "markdown"

    def __init__(self) -> None:
        self.handled_buffers: List[str] = []

    def activate(self, host: PluginHost) -> None:
        host.file_types.register(".md", self._handle_md, plugin_name=self.name)
        host.commands.register("md-info", self._cmd_info, plugin_name=self.name)

    def _handle_md(self, buf: Buffer) -> None:
        self.handled_buffers.append(buf.filename)

    def _cmd_info(self, host: PluginHost, args: List[str]) -> str:
        return f"Handled: {', '.join(self.handled_buffers)}"


class ReadOnlyPlugin(Plugin):
    """Cancels all buffer modifications — demonstrates event cancellation."""

    @property
    def name(self) -> str:
        return "readonly"

    def activate(self, host: PluginHost) -> None:
        host.hooks.subscribe(
            Hook.BEFORE_BUFFER_CHANGE,
            self._block,
            plugin_name=self.name,
            priority=0,
        )

    @staticmethod
    def _block(event: HookEvent) -> Optional[HookEvent]:
        event.cancel()
        return event


class WordCountCommand(Plugin):
    """Adds a :wc command that returns word count of active buffer."""

    @property
    def name(self) -> str:
        return "wordcount"

    def activate(self, host: PluginHost) -> None:
        host.commands.register("wc", self._cmd_wc, plugin_name=self.name)

    @staticmethod
    def _cmd_wc(host: PluginHost, args: List[str]) -> int:
        buf = host.active_buffer
        if buf is None:
            return 0
        return len(buf.text.split())


# ===================================================================
# Verification
# ===================================================================

if __name__ == "__main__":
    # ---- 1. Basic host + buffer creation ----
    host = PluginHost()
    buf = host.create_buffer("hello\nworld", filename="test.txt")
    assert buf.text == "hello\nworld"
    assert buf.line_count == 2
    assert buf.get_line(0) == "hello"

    # ---- 2. Load plugins via PluginLoader ----
    autosave = PluginLoader.from_class(AutoSavePlugin, host)
    assert "autosave" in host.loaded_plugins
    assert host.get_plugin("autosave") is autosave

    PluginLoader.from_classes(
        [LineNumberPlugin, UppercaseKeystrokePlugin, KeystrokeLoggerPlugin],
        host,
    )
    assert len(host.loaded_plugins) == 4

    # ---- 3. Buffer modification fires hooks ----
    autosave_inst: AutoSavePlugin = host.get_plugin("autosave")  # type: ignore
    assert autosave_inst.change_count == 0
    buf.set_line(0, "HELLO")
    assert buf.get_line(0) == "HELLO"
    assert autosave_inst.change_count == 1

    buf.insert_line(1, "middle")
    assert buf.line_count == 3
    assert autosave_inst.change_count == 2

    removed = buf.delete_line(1)
    assert removed == "middle"
    assert buf.line_count == 2
    assert autosave_inst.change_count == 3

    buf.insert_text(0, 5, "!")
    assert buf.get_line(0) == "HELLO!"
    assert autosave_inst.change_count == 4

    # ---- 4. Save command + line numbers hook ----
    saved = host.run_command("save")
    assert "1: HELLO!" in saved
    assert "2: world" in saved
    assert autosave_inst.change_count == 0  # reset after save

    # ---- 5. Keystroke interception ----
    logger: KeystrokeLoggerPlugin = host.get_plugin("keystroke_logger")  # type: ignore
    result = host.send_keystroke("a")
    assert result == "A"  # UppercaseKeystrokePlugin converts
    assert logger.log == ["a"]  # logger sees original key in hook

    result = host.send_keystroke("b")
    assert result == "B"
    assert logger.log == ["a", "b"]

    # ---- 6. File-type handler ----
    md_plugin = PluginLoader.from_class(MarkdownPlugin, host)
    md_buf = host.create_buffer("# Title\nSome text", filename="readme.md")
    md_inst: MarkdownPlugin = host.get_plugin("markdown")  # type: ignore
    assert "readme.md" in md_inst.handled_buffers

    info = host.run_command("md-info")
    assert "readme.md" in info

    # Non-.md file should not trigger handler
    txt_buf = host.create_buffer("plain", filename="notes.txt")
    assert len(md_inst.handled_buffers) == 1

    # ---- 7. ReadOnly plugin cancels buffer changes ----
    host2 = PluginHost()
    ro_buf = host2.create_buffer("immutable line", filename="locked.txt")
    PluginLoader.from_class(ReadOnlyPlugin, host2)
    ro_buf.set_line(0, "changed")
    assert ro_buf.get_line(0) == "immutable line"  # change was cancelled

    ro_buf.insert_line(0, "new line")
    assert ro_buf.line_count == 1  # insert was cancelled

    deleted = ro_buf.delete_line(0)
    assert ro_buf.line_count == 1  # delete was cancelled

    # ---- 8. Word count command ----
    PluginLoader.from_class(WordCountCommand, host)
    host.create_buffer("one two three four five", filename="count.txt")
    assert host.run_command("wc") == 5

    # ---- 9. Command listing ----
    cmds = host.commands.list_commands()
    assert "save" in cmds
    assert "wc" in cmds
    assert "md-info" in cmds

    # ---- 10. Unload plugin removes hooks/commands ----
    assert host.commands.has("save")
    host.unload_plugin("autosave")
    assert "autosave" not in host.loaded_plugins
    assert not host.commands.has("save")

    # ---- 11. Duplicate plugin load raises ----
    try:
        PluginLoader.from_class(LineNumberPlugin, host)
        assert False, "Should have raised ValueError"
    except ValueError:
        pass

    # ---- 12. Unload unknown plugin raises ----
    try:
        host.unload_plugin("nonexistent")
        assert False, "Should have raised KeyError"
    except KeyError:
        pass

    # ---- 13. Unknown command raises ----
    try:
        host.run_command("nonexistent")
        assert False, "Should have raised KeyError"
    except KeyError:
        pass

    # ---- 14. Hook priority ordering ----
    host3 = PluginHost()
    order: List[str] = []

    class PriorityPluginA(Plugin):
        @property
        def name(self) -> str:
            return "priority_a"

        def activate(self, h: PluginHost) -> None:
            h.hooks.subscribe(Hook.KEYSTROKE, lambda e: (order.append("A"), e)[1],
                              plugin_name=self.name, priority=200)

    class PriorityPluginB(Plugin):
        @property
        def name(self) -> str:
            return "priority_b"

        def activate(self, h: PluginHost) -> None:
            h.hooks.subscribe(Hook.KEYSTROKE, lambda e: (order.append("B"), e)[1],
                              plugin_name=self.name, priority=50)

    PluginLoader.from_classes([PriorityPluginA, PriorityPluginB], host3)
    host3.send_keystroke("x")
    assert order == ["B", "A"]  # lower priority number runs first

    # ---- 15. Buffer load with hook ----
    host4 = PluginHost()
    load_log: List[str] = []
    host4.hooks.subscribe(
        Hook.BUFFER_LOAD,
        lambda e: (load_log.append(e.data["filename"]), e)[1],
        plugin_name="test",
    )
    b = host4.create_buffer(filename="empty.txt")
    b.load("new content", filename="loaded.txt")
    assert b.text == "new content"
    assert b.filename == "loaded.txt"
    assert "loaded.txt" in load_log

    # ---- 16. File type registry supported extensions ----
    assert ".md" in host.file_types.supported_extensions()

    # ---- 17. Keystroke cancellation via hook ----
    host5 = PluginHost()
    host5.hooks.subscribe(
        Hook.KEYSTROKE,
        lambda e: (e.cancel(), e)[1],
        plugin_name="blocker",
    )
    assert host5.send_keystroke("z") is None  # cancelled

    # ---- 18. HookRegistry subscriber count ----
    assert host.hooks.subscriber_count(Hook.KEYSTROKE) >= 1

    # ---- 19. Plugin version and description ----
    md_p = host.get_plugin("markdown")
    assert md_p is not None
    assert md_p.version == "0.0.0"  # default

    as_cls = AutoSavePlugin()
    assert as_cls.version == "1.0.0"
    assert as_cls.description == "Tracks changes and provides a save command."

    # ---- 20. PluginLoader rejects non-Plugin classes ----
    try:
        PluginLoader.from_class(str, PluginHost())
        assert False, "Should have raised TypeError"
    except TypeError:
        pass

    print("All 20 assertions passed.")
