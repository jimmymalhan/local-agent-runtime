```python
# This Python script generates CSS variables for dark and light themes with glassmorphism design tokens.
def generate_theme_css(base_color, accent_color):
    # Dark theme colors
    dark_bg = f"rgb({base_color[0] * 0.8}, {base_color[1] * 0.8}, {base_color[2] * 0.8})"
    dark_text = "white"
    
    # Light theme colors
    light_bg = f"rgb({base_color[0] * 1.2}, {base_color[1] * 1.2}, {base_color[2] * 1.2})"
    light_text = "black"
    
    # Glassmorphism properties
    glass_opacity = "0.8"
    glass_filter = f"blur(5px) brightness({glass_opacity})"
    
    # CSS variables for dark theme
    dark_theme_css = f"""
    :root {{
        --bg-color: {dark_bg};
        --text-color: {dark_text};
        --accent-color: {accent_color};
        --glass-opacity: {glass_opacity};
        --glass-filter: {glass_filter};
    }}
    """
    
    # CSS variables for light theme
    light_theme_css = f"""
    :root {{
        --bg-color: {light_bg};
        --text-color: {light_text};
        --accent-color: {accent_color};
        --glass-opacity: {glass_opacity};
        --glass-filter: {glass_filter};
    }}
    """
    
    return dark_theme_css, light_theme_css

# Example usage
base_color = (50, 50, 50)
accent_color = (255, 165, 0)
dark_theme, light_theme = generate_theme_css(base_color, accent_color)

print("Dark Theme CSS:")
print(dark_theme)
print("\nLight Theme CSS:")
print(light_theme)
```