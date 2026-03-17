# System Legend

This document provides an at‑a‑glance overview of the tools, frameworks,
roles and workflows included in this repository.  It acts as a
“legend” for the solopreneur system, helping you track which
components are available and their purpose.  The legend is updated
periodically by maintenance scripts (`scripts/update_external_tools.sh`
and `scripts/update_project.sh`).  Use it to understand the
capabilities of your local AI stack and to plan further extensions.

## Core Components

- **Local Ollama Runtime** – All primary reasoning runs through the
  local Ollama-backed model team instead of a hosted API.
- **Agents** – Shell scripts in `agents/` that orchestrate each
  compatibility pipeline stage. The preferred execution path lives in
  `scripts/local_team_run.py`, which coordinates a weighted multi-role
  local team.
- **Skills** – Reusable reasoning templates stored in `skills/`.  The
  system generates, upgrades and discards skills as it learns from
  feedback logs.
- **Workflows** – YAML/markdown files in `workflows/` that define
  sequences of agents for each type of task.  New workflows are
  created automatically based on user prompts and evolving
  requirements.
- **Roles** – Human‑readable descriptions of each agent role (e.g.
  architect, implementation, growth, sales) in `roles/`.
- **Feedback Logs** – Logs under `feedback/` that record every
  prompt and the evolution of workflows; used to generate new skills
  and refine existing ones.
- **Resource Monitor** – `monitor_resources.sh` monitors CPU and
  memory, ensuring the system does not exceed 70 % utilisation.  A
  slowdown flag pauses agents when resources are constrained.
- **Progress Tracker** – `progress_tracker.sh` records the
  percentage completion of batch processes and writes updates to
  `state/progress.json` and `logs/progress.log`.
- **Checkpoint Manager** – `create_checkpoint.sh` and
  `restore_checkpoint.sh` create recoverable snapshots under
  `state/checkpoints/` before major
  changes or restore operations.
- **To‑Do Manager** – `state/todo.md` and `update_todo.sh` maintain
  a list of pending tasks and the agents responsible for them.

## External Tools from Fireship Video

The following tools are integrated or stubbed based on the Fireship
video “7 new open source AI tools you need right now”【755566301775411†L156-L165】:

| Tool        | Purpose                                            | Status | Notes |
|-------------|----------------------------------------------------|--------|-------|
| **Agency**  | Library of agent templates for common roles【103549211664539†L69-L75】 | Optional | Clone and copy into `.claude/agents/` or convert to skills. |
| **Prompt FU** | Unit‑test framework for prompts【755566301775411†L156-L165】 | Supported | Use `scripts/promptfu_test.sh` to test prompts. |
| **Mirrorish** | Multi‑agent prediction engine【755566301775411†L156-L165】 | Stubbed | Placeholder script `mirrorish_predict.sh` awaits installation. |
| **Impeccable** | UI refinement commands【755566301775411†L156-L165】 | Supported | Use `impeccable_ui.sh` for HTML improvements. |
| **Open Viking** | File‑system‑based context database【755566301775411†L156-L165】 | Native | The repo’s directory structure mirrors this philosophy. |
| **Heretic** | Censorship removal tool【755566301775411†L156-L165】 | Supported | Use with caution via `heretic_filter.sh`. |
| **Nano Chat** | Lightweight LLM training pipeline【755566301775411†L156-L165】 | Stubbed | `nanochat_train.sh` is a placeholder until installed. |

## Advanced Frameworks

This system can interface with several open‑source frameworks to
enhance orchestration, parallelism and retrieval.  Installation and
integration are optional:

| Framework    | Strengths                                         | Installation | Notes |
|--------------|----------------------------------------------------|-------------|-------|
| **CrewAI**   | Role‑based multi‑agent orchestration【534472104224777†L122-L141】 | `pip install crewai` | See `scripts/crewai_orchestrate.sh` for a stub. |
| **LangChain** | Modular chains and memory management【237246115056748†L125-L137】 | `pip install langchain` | Stub script `langchain_pipeline.sh` provided. |
| **LangGraph** | Graph‑based workflows with error recovery【237246115056748†L146-L156】 | `pip install langgraph` | See `langgraph_flow.sh`. |
| **AutoGen**  | Asynchronous multi‑agent collaboration【237246115056748†L164-L176】 | `pip install autogen` | Run via `autogen_run.sh`. |
| **SuperAGI** | Parallel agents with built‑in UI【237246115056748†L224-L236】 | `pip install superagi` | Start with `superagi_run.sh`; resource heavy. |
| **LlamaIndex** | Retrieval‑augmented generation (RAG)【237246115056748†L265-L276】 | `pip install llama-index` | Used internally for RAG via `llamaindex_update.sh`. |
| **Pinecone** | Managed vector database for RAG【462684992376271†L120-L133】 | `pip install pinecone-client` | Optional; set `RAG_METHOD=pinecone`. |
| **OpenClaw** | Self‑hosted agent gateway and summarisation【7309971885225†L132-L162】 | `curl -fsSL https://openclaw.ai/install.sh | bash` | Used via `openclaw_summarize.sh`. |
| **Google ADK** | Modular multi‑agent orchestration toolkit【384744227011679†L287-L304】 | `pip install google-adk` | Stub script `adk_run.sh`. |
| **Dify** | Low‑code platform with built‑in RAG and ReAct【384744227011679†L318-L329】 | `pip install dify` | Stub script `dify_run.sh`; may require additional services. |
| **Mastra** | TypeScript‑first framework with memory, RAG, OpenTelemetry【86686542789695†L270-L291】 | `npm install -g @mastra/cli` | Use `mastra_flow.sh` stub. |
| **Semantic Kernel** | Enterprise skill orchestration with multi‑language support【86686542789695†L322-L364】 | `pip install semantic-kernel` | Stub script `semantic_kernel_run.sh`. |
| **Pydantic AI** | Type‑safe Python agents with FastAPI‑style DX【86686542789695†L322-L364】 | `pip install pydantic-ai-agents` | See `pydantic_ai_run.sh`. |
| **Strands Agents** | Model‑agnostic toolkit with strong observability【86686542789695†L322-L364】 | `pip install strands-agents` | Stub script `strands_agents_run.sh`. |
| **Smolagents** | Minimalist code‑centric agents for quick automations【86686542789695†L322-L364】 | `pip install smolagents` | Stub script `smolagents_run.sh`. |
| **Agno** | Fast agent SDK with optional hosted platform【86686542789695†L322-L364】 | `pip install agno` | Stub script `agno_run.sh`. |
| **Microsoft Agent Framework** | Flexible runtime with multi‑provider support and observability【86686542789695†L294-L311】 | `pip install ms-agent-framework` | Use `microsoft_agent_framework_run.sh`. |

## Roles and Skills

The system defines the following roles (with associated skills):

| Role          | Description                                           | Example Skill Files |
|---------------|-------------------------------------------------------|--------------------|
| **Architect** | Analyses requirements and designs architectures | `generate-architecture.md` |
| **Implementation** | Generates production code and modules | `implement-feature.md` |
| **Review**    | Validates code quality and detects errors | `validate-logic.md` |
| **Test**      | Creates and runs integration/unit tests | (generated dynamically) |
| **Optimizer** | Improves performance and reduces complexity | `optimize-system.md` |
| **Growth**    | Develops marketing strategies and leads generation | `generate-marketing-plan.md` |
| **Sales**     | Drafts outreach emails and manages sales pipeline | `sales-outreach.md` |

The list of skills is dynamic; new skills are created by
`scripts/skill_generator.sh` based on patterns found in the
feedback logs.  Skills are versioned (e.g. `implement-feature-v1.md`,
`implement-feature-v2.md`) to track improvements over time.

## Maintenance Scripts

- `update_external_tools.sh` – Looks for new tools from a source (set
  `EXTERNAL_TOOL_SOURCE`) and appends them to the docs.
- `self_update.sh` – Pulls the latest repository and upgrades Python
  dependencies (if network access is allowed).
- `update_project.sh` – Combines the above, upgrading external tools,
  performing a git pull, upgrading optional Python packages, and
  generating new skills.
- `skill_generator.sh` – Parses feedback logs to create new skill
  templates for recurring tasks.
- `progress_tracker.sh` – Logs pipeline progress in percentage terms.
- `monitor_resources.sh` – Monitors CPU and memory and writes a
  slowdown flag when utilisation exceeds the threshold.
- `rag_retrieval.sh` – Implements retrieval‑augmented generation, with
  optional Pinecone support.
- `openclaw_summarize.sh` – Summarises files/directories using
  OpenClaw’s CLI.

This legend helps you understand the scope of your local automation
stack at a glance. Use it as a reference when adding new tools or
frameworks, and keep it updated through maintenance scripts or manual
edits.
