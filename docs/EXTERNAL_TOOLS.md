# External Tools from Fireship Video

This document summarises seven open‑source AI tools highlighted in the
*Fireship* video “7 new open source AI tools you need right now” and
describes how they could be integrated into your local agent framework.
Each tool is optional — your system already functions without them — but
they offer powerful ways to extend your agents.  Where possible, we
provide high‑level instructions for local integration and link back to
the original source for further details.

## 1. Agency

**Purpose:** A repository of agent templates that mirror the roles in a
startup — frontend developer, backend developer, growth marketer,
security engineer and more.  Each template contains a detailed
Markdown document defining the agent’s identity, responsibilities,
deliverables and success metrics, providing a turnkey way to spin up
specialised agents【103549211664539†L69-L75】.  The original project ships with 61
agents across nine divisions.

**Integration:**

1. Clone the Agency repository from its official source (for example
   `git clone https://github.com/<org>/agency-agents`).
2. Copy the agent files into your local agent directory:

   ```bash
   cp -r agency-agents/* ~/.claude/agents/
   ```

3. Activate the desired agent in your Claude session by name (e.g.
   “activate Frontend Developer mode and help me build a React
   component”)【103549211664539†L69-L75】.  You can also convert these agents to the
   skill format used in this repository by mapping their sections
   (Identity, Process, Deliverables) into the **Trigger**, **Commands** and
   **Output** sections of a skill file.

## 2. Prompt FU

**Purpose:** A prompt unit‑testing framework (acquired by OpenAI) that
automatically red‑teams your prompts to uncover injection or
censorship vulnerabilities【755566301775411†L156-L165】.  It acts like a unit test
suite for prompts, ensuring they handle malicious inputs and edge
cases.

**Integration:** A helper script `scripts/promptfu_test.sh` is provided
in this repository.  Install Prompt FU locally (e.g.
`pip install promptfu`), then run:

```bash
./scripts/promptfu_test.sh path/to/prompt.md
```

The script executes Prompt FU against the given prompt file and
writes a report to `logs/promptfu.log`.  Use this during skill
development to harden your prompts against injection attacks.

## 3. Mirrorish (MicroFish)

**Purpose:** A multi‑agent AI prediction engine that learns from
real‑time news, financial data and social signals to simulate digital
worlds and forecast trends【755566301775411†L156-L165】.  It can be used to
compare different implementation strategies or resource allocations
before committing to a plan.

**Integration:** Mirrorish is designed to run as its own service.  To
experiment locally, create a stub script `scripts/mirrorish_predict.sh`
that reads a scenario description and outputs a placeholder prediction.
Once you install Mirrorish (see its documentation), modify the script
to call the tool’s CLI and feed the results back into your agent
pipeline.  Mirrorish is not required for basic operation of this
framework.

## 4. Impeccable

**Purpose:** A suite of 17 commands (e.g. `distill`, `colorize`,
`animate`) that refine AI‑generated user interfaces【755566301775411†L156-L165】.
Impeccable analyses HTML or design output from an agent and applies
optimisations to improve readability, aesthetics and accessibility.

**Integration:** If your agents generate UI code, you can incorporate
Impeccable by creating a wrapper script `scripts/impeccable_ui.sh` that
accepts an HTML file, runs the appropriate Impeccable command and
writes the refined HTML back to `context/` or `memory/`.  Install
Impeccable according to its documentation and adjust the wrapper to
call `impeccable <command> <input> --output <output>`.

## 5. Open Viking

**Purpose:** A file‑system‑based context database for AI agents.  It
organises memories, resources and skills in hierarchical directories
instead of a vector database, enabling token savings and long‑term
memory refinement【755566301775411†L156-L165】.  By storing information
directly in files, agents can selectively load only the portions they
need at each step.

**Integration:** The architecture of this repository already follows
Open Viking’s philosophy.  Memories are stored under `memory/`, context
summaries under `context/` and skills under `skills/`, and agents
selectively read only the files required for the current task.  If you
wish to adopt Open Viking itself, install it locally and configure the
agent pipeline to use its hierarchical loading mechanisms.  This
framework can serve as a starting point for such an integration.

## 6. Heretic

**Purpose:** An open‑source tool that removes or bypasses model
censorship using a technique called *obliteration*【755566301775411†L156-L165】.  It
allows you to test how your agents behave under fewer safety
restrictions and can be used to stress‑test prompt robustness.

**Integration:** **Use with caution.** If you choose to explore
Heretic, install it locally and create a wrapper script
`scripts/heretic_filter.sh` that feeds your prompt or conversation
through `heretic` before passing it to the Claude CLI.  Ensure that
you abide by all applicable laws and ethical guidelines when using this
tool.  Heretic is not required for normal operation and should only be
used in controlled experiments.

## 7. Nano Chat

**Purpose:** A pipeline for training a small language model from
scratch for around $100 in GPU costs【755566301775411†L156-L165】.  It
provides scripts and configurations to download a dataset, train a
compact model and deploy it locally.

**Integration:** Training a custom model is a heavyweight process.
However, if you wish to experiment, download the Nano Chat pipeline
from its official repository and run it on a machine with suitable
hardware.  Afterwards, modify your agent scripts to use the resulting
model (for example, via Ollama or another local inference engine).  The
core framework in this repository can interact with any model
exposed via a Claude‑compatible CLI.

---

These tools represent the cutting edge of open‑source AI agent
infrastructure.  While not all are necessary to run this repository,
they can greatly enhance the capabilities of your agents.  Refer to
each project’s documentation for installation and usage details.  Keep
in mind that your system must remain local and free of external API
dependencies, so ensure that any integrations respect those
constraints.