```python
# This file implements responsive layout features for a local AI agent runtime.
# It adjusts the sidebar and kanban board based on tablet/desktop breakpoints.

def apply_responsive_layout(device_type):
    if device_type == "tablet":
        # Collapse sidebar to icon bar
        collapse_sidebar_to_icon_bar()
    elif device_type == "mobile":
        # Enable horizontal scrolling for kanban board
        enable_horizontal_scrolling_for_kanban()

def collapse_sidebar_to_icon_bar():
    # Code to collapse sidebar to icon bar on tablet
    print("Sidebar collapsed to icon bar.")

def enable_horizontal_scrolling_for_kanban():
    # Code to enable horizontal scrolling for kanban board on mobile
    print("Kanban board set to scroll horizontally.")
```