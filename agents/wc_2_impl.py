```python
# This script removes all dead code from .py files by removing unused imports,
# deleting duplicate modules, and removing orphan scripts in the 'scripts/' directory.

import os
import importlib.util
from collections import defaultdict

def find_unused_imports(file_path):
    with open(file_path, 'r') as file:
        lines = file.readlines()
    
    used_imports = set()
    for line in lines:
        if line.startswith('import ') or line.startswith('from '):
            parts = line.split()
            module_name = parts[1].split('.')[0]
            try:
                importlib.import_module(module_name)
                used_imports.add(module_name)
            except ImportError:
                pass
    
    with open(file_path, 'w') as file:
        for line in lines:
            if not (line.startswith('import ') or line.startswith('from ')) or any(part in line for part in used_imports):
                file.write(line)

def find_duplicate_modules(directory):
    module_counts = defaultdict(int)
    for root, _, files in os.walk(directory):
        for file in files:
            if file.endswith('.py'):
                with open(os.path.join(root, file), 'r') as f:
                    first_line = f.readline().strip()
                    if first_line.startswith('# Module:'):
                        module_name = first_line.split(': ')[1]
                        module_counts[module_name] += 1
    
    duplicates = {module: count for module, count in module_counts.items() if count > 1}
    return duplicates

def remove_orphan_scripts(directory):
    for root, _, files in os.walk(directory):
        for file in files:
            if file.endswith('.py'):
                with open(os.path.join(root, file), 'r') as f:
                    first_line = f.readline().strip()
                    if not first_line.startswith('# Module:'):
                        os.remove(os.path.join(root, file))

def main():
    project_root = 'path/to/your/project'
    
    # Remove unused imports
    for root, _, files in os.walk(project_root):
        for file in files:
            if file.endswith('.py'):
                find_unused_imports(os.path.join(root, file))
    
    # Find and remove duplicate modules
    duplicates = find_duplicate_modules(project_root)
    for module, _ in duplicates.items():
        for root, _, files in os.walk(project_root):
            for file in files:
                if file.endswith('.py'):
                    with open(os.path.join(root, file), 'r') as f:
                        first_line = f.readline().strip()
                        if first_line.startswith('# Module:') and first_line.split(': ')[1] == module:
                            os.remove(os.path.join(root, file))
    
    # Remove orphan scripts
    remove_orphan_scripts('scripts/')

if __name__ == '__main__':
    main()
```