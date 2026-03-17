#!/bin/bash
set -euo pipefail

DOC_DIR=${1:-./documents}
INDEX_DIR=${2:-./memory/index}

if ! command -v python3 >/dev/null 2>&1; then
  echo "Python 3 is required to run LlamaIndex builders." >&2
  exit 1
fi

python3 - "$DOC_DIR" "$INDEX_DIR" <<'PYEOF'
import pathlib
import sys

try:
    from llama_index.core import SimpleDirectoryReader, VectorStoreIndex
except ImportError:
    print("Please install llama-index via 'pip install llama-index'")
    raise SystemExit(1)

doc_dir = pathlib.Path(sys.argv[1])
index_dir = pathlib.Path(sys.argv[2])

if not doc_dir.is_dir():
    print(f"Document directory '{doc_dir}' does not exist.")
    raise SystemExit(1)

documents = SimpleDirectoryReader(str(doc_dir)).load_data()
index = VectorStoreIndex.from_documents(documents)
index.storage_context.persist(persist_dir=str(index_dir))
print(f"Saved index to {index_dir}")
PYEOF
