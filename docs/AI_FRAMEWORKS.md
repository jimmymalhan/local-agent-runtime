# Advanced AI Agent Frameworks for End‑to‑End Automation

This document introduces a series of open‑source frameworks that can take your local
agent system from a single‑agent pipeline to a full multi‑agent business platform.
These frameworks are optional extensions; they require additional installation
and configuration but can unlock powerful orchestration, memory management and
parallel execution.  Each framework described here can be installed locally
without relying on SaaS APIs, making them compatible with the “no external API”
constraint of this repository.

## CrewAI

CrewAI is an open‑source framework designed specifically for multi‑agent
coordination.  It streamlines complex tasks through **role‑based architecture**,
where each agent has a distinct role (e.g. manager, worker, researcher)【534472104224777†L122-L141】.
Agents collaborate via structured messages and can dynamically reassign tasks,
allowing coordinated teamwork that mirrors real‑world organisations【534472104224777†L143-L164】.
CrewAI’s orchestration engine supports **sequential, parallel and conditional**
execution models【534472104224777†L151-L154】, and its built‑in tooling handles file
processing, data transformation and other common operations【534472104224777†L167-L172】.

**Installation:** CrewAI runs on Python 3.10+ and uses the `uv` package manager.
To install the CLI locally:

```bash
pip install crewai
```

Or, if you prefer the `uv` tool:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
uv tool install crewai
```

After installation, you can create a new CrewAI project (`crewai create crew
<project_name>`) and define your agents and tasks in YAML files.  This repository
includes a stub script (`scripts/crewai_orchestrate.sh`) that checks for the
CLI and runs a CrewAI project located in a specified directory.  Use this to
experiment with multi‑agent orchestration locally.

## LangChain

LangChain is a widely adopted framework for building AI agents.  It offers a
**modular approach** to chaining large language models with tools, memory and
external sources【237246115056748†L125-L137】.  LangChain excels at both research and
production workflows thanks to its large ecosystem and strong memory/context
handling【237246115056748†L125-L137】.  However, its flexibility comes with overhead:
it can be heavy for simple tasks and has a steeper learning curve【237246115056748†L138-L142】.

**Installation:** LangChain is available via pip:

```bash
pip install langchain
```

This repository provides a stub script (`scripts/langchain_pipeline.sh`) to
demonstrate how a LangChain pipeline might be invoked.  For production use,
you can build custom chains that call your local LLM (via Ollama or other
providers), integrate file tools, and maintain memory across interactions.

## LangGraph

LangGraph extends LangChain with a **graph‑based orchestration layer**.
It is designed to manage **long‑running, stateful workflows** with complex
branching and error recovery【237246115056748†L146-L156】.  By modelling agent tasks as
nodes in a graph, LangGraph makes debugging and error handling transparent,
and it is ideal for workflows that require conditional logic or retries.

**Installation:** Install LangGraph via pip:

```bash
pip install langgraph
```

The stub script `scripts/langgraph_flow.sh` illustrates how you might call a
LangGraph flow from this repository.  Use LangGraph when your business
processes involve many branching decisions or require robust error handling.

## AutoGen

AutoGen is a programming framework from Microsoft Research tailored for
**multi‑agent collaboration** and asynchronous task execution【237246115056748†L164-L176】.
It supports **human‑in‑the‑loop** oversight, enabling agents to coordinate while
still receiving guidance from developers or end‑users【237246115056748†L164-L176】.
AutoGen is well‑suited for research and enterprise scenarios but has a more
complex setup and higher resource requirements【237246115056748†L179-L182】.

**Installation:** Install AutoGen locally with:

```bash
pip install autogen
```

The script `scripts/autogen_run.sh` provides a starting point for running an
AutoGen conversation or plan from your local machine.  You may need to
configure agent definitions and tasks according to AutoGen’s documentation.

## SuperAGI

SuperAGI is an open‑source framework aimed at developers needing a
developer‑oriented environment with **parallel execution**, a **built‑in UI** and
rich integration options【237246115056748†L224-L236】.  It supports running multiple
agents in parallel and offers a graphical interface for monitoring and control,
making it suitable for complex multi‑agent systems.  SuperAGI is resource‑heavy
and still maturing【237246115056748†L239-L242】, so evaluate whether your hardware can
support it.

**Installation:** Install via pip:

```bash
pip install superagi
```

The stub script `scripts/superagi_run.sh` checks for the SuperAGI CLI and
launches a project.  Use it when you need parallel agents and a GUI
for orchestration.

## LlamaIndex

LlamaIndex specialises in **retrieval‑augmented generation (RAG)** workflows,
connecting agents to structured and unstructured data sources【237246115056748†L265-L276】.
It provides strong retrieval capabilities and easy document integration but
lacks orchestration features【237246115056748†L276-L281】.  Use LlamaIndex when your
agents need to query large knowledge bases or documents without a vector
database.

**Installation:** Install via pip:

```bash
pip install llama-index
```

The stub script `scripts/llamaindex_update.sh` shows how to build or update a
local index for your documents using LlamaIndex.  It can be combined with
LangChain or other frameworks for complete RAG pipelines.

## SGLang

SGLang is best used here as a **local ranking and high-throughput inference tier** rather than as a generic replacement for every agent. In a scaled deployment, use it to rerank candidate passages after retrieval, then feed only the best candidates into the final generation stage. This repo includes `scripts/sglang_ranker.sh`, which expects a local OpenAI-compatible SGLang endpoint, and `scripts/scale_rag_ranking.sh`, which chains retrieval plus reranking for larger RAG workloads.

## Why Use These Frameworks?

The frameworks above expand your local agent system in different ways:

* **CrewAI** adds role‑based multi‑agent orchestration, enabling agents to
  collaborate like a team【534472104224777†L122-L141】.
* **LangChain** provides modular building blocks and a large community for
  chaining tools and memory【237246115056748†L125-L137】.
* **LangGraph** introduces graph‑based workflows with error recovery【237246115056748†L146-L156】.
* **AutoGen** supports asynchronous collaboration and human oversight【237246115056748†L164-L176】.
* **SuperAGI** runs parallel agents with a built‑in UI【237246115056748†L224-L236】.
* **LlamaIndex** offers powerful document retrieval capabilities【237246115056748†L265-L276】.

By installing and experimenting with these tools, you can customise your
solopreneur system to handle everything from customer support and CRM to
marketing, research and data analysis.  Always ensure that any integration
respects your resource limits and stays within the “no external API” policy.

## Additional Emerging Frameworks

The AI agent ecosystem continues to evolve rapidly.  Below are several
additional open‑source frameworks gaining traction in 2026.  Each has
distinct strengths and may be worth exploring depending on your
technology stack and project requirements.  Many of these frameworks are
referenced in industry comparisons【86686542789695†L270-L291】【86686542789695†L294-L311】.

### Google Agent Development Kit (ADK)

The **Google ADK** is a modular toolkit for building and orchestrating
generative AI agents.  It integrates natively with Google’s Gemini
models and Vertex AI but also supports other providers.  ADK emphasises
declarative agent definitions, hierarchical compositions and built‑in
session management, making it easy to define agents with tools and
manage conversational state【384744227011679†L287-L304】.  Use ADK if you
operate within Google’s ecosystem and need built‑in multi‑agent
orchestration.

**Installation:** ADK is published on PyPI.  Install with:

```bash
pip install google-adk
```

After installation, create an ADK project and define your agents in
YAML or Python.  A stub script (`scripts/adk_run.sh`) is provided in
this repository as a starting point for running ADK flows locally.

### Dify

**Dify** is a low‑code platform and SDK that offers built‑in RAG,
function calling, ReAct strategies and integration with hundreds of
language models and vector search engines【384744227011679†L318-L329】.
Dify aims to make it simple to build complex agent workflows via a
graphical interface while still exposing an API for developers.  Use
Dify when you want a drag‑and‑drop environment with strong retrieval and
tool‑calling capabilities, but avoid if you need a completely offline
solution.

**Installation:** Dify is available via pip:

```bash
pip install dify
```

You can run the stub script (`scripts/dify_run.sh`) to launch a Dify
workflow from this repository once installed.  Note: Dify may require
additional services (like a vector database) to operate.

### Mastra

**Mastra** is a TypeScript‑first agent framework that provides
primitives for building AI applications with memory and tool‑calling
capabilities.  It supports deterministic LLM workflows, retrieval‑
augmented generation (RAG) and has native OpenTelemetry integration for
observability【86686542789695†L270-L291】.  Mastra fills a gap for
JavaScript/TypeScript teams who want to build agents with robust
observability and RAG support.

**Installation:** Install via npm:

```bash
npm install -g @mastra/cli
```

A placeholder script (`scripts/mastra_flow.sh`) demonstrates how you
might invoke a Mastra workflow within this repository.  Full
functionality will require the Mastra CLI and configuration.

### Semantic Kernel

Microsoft’s **Semantic Kernel (SK)** is a skill‑based framework designed
for enterprise integration.  It orchestrates external skills and
language models, provides native multi‑language support and is
positioned for large organisations that need robust skill management
【86686542789695†L322-L364】.  SK is ideal for .NET or enterprise
environments requiring compliance and scalability.

**Installation:** Install via pip:

```bash
pip install semantic-kernel
```

A stub script (`scripts/semantic_kernel_run.sh`) is included to outline
how you might call Semantic Kernel pipelines from this repository.

### Pydantic AI Agents

**Pydantic AI** provides a type‑safe Python agent framework with a
FastAPI‑style developer experience.  It emphasises strong type safety
and structured logic for building robust agents【86686542789695†L322-L364】.
Use Pydantic AI when you need validated inputs and outputs and prefer
strict typing.

**Installation:** Available via pip:

```bash
pip install pydantic-ai-agents
```

After installation, you can write agents using Pydantic models.  The
stub script (`scripts/pydantic_ai_run.sh`) provides a template for
invoking such agents in this repository.

### Strands Agents

**Strands Agents** is a model‑agnostic toolkit that runs anywhere
and supports multiple model providers via LiteLLM.  It emphasises
production‑grade observability through OpenTelemetry and offers
provider flexibility【86686542789695†L322-L364】.  Use Strands when you
need to integrate different LLM providers (e.g. Bedrock, Anthropic,
OpenAI, Ollama) with strong tracing support.

**Installation:** Install with pip:

```bash
pip install strands-agents
```

A placeholder script (`scripts/strands_agents_run.sh`) in this
repository can be customised once Strands Agents is installed.

### Smolagents

**Smolagents** (from Hugging Face) is a minimalist, code‑centric agent
framework.  It sets up a simple loop where the agent writes and
executes code to achieve a goal, making it ideal for quick
automations【86686542789695†L322-L364】.  Smolagents handles the ReAct
prompting under the hood, so you focus on high‑level tasks rather than
orchestration.

**Installation:** Available via pip:

```bash
pip install smolagents
```

The stub script (`scripts/smolagents_run.sh`) offers a starting point
for running smolagents from within this repository.

### Agno

**Agno** combines a fast agent SDK with an optional managed platform.
It offers multi‑provider support and emphasises speed and convenience
【86686542789695†L322-L364】.  Use Agno when you want a rapid SDK for
developing agents with optional hosted deployment.

**Installation:** Agno is available via pip:

```bash
pip install agno
```

Use the stub script (`scripts/agno_run.sh`) as a template for running
Agno agents locally.

### Microsoft Agent Framework

The **Microsoft Agent Framework (MAF)** is a flexible, general‑purpose
agent runtime that complements AutoGen and Semantic Kernel【86686542789695†L294-L311】.
It supports multiple LLM providers, offers built‑in observability via
OpenTelemetry and integrates with Azure services.  MAF is ideal for
developers in the Microsoft ecosystem who need a scalable, production‑
grade agent foundation.

**Installation:** Install via pip:

```bash
pip install ms-agent-framework
```

A stub script (`scripts/microsoft_agent_framework_run.sh`) is provided
to help you explore MAF in this repository once it is installed.

### OpenAI Agents SDK

Although not fully open source, the **OpenAI Agents SDK** provides a
structured toolset for building agents that utilise OpenAI’s models.  It
includes a specialised runtime for assigning roles, tools and triggers
and integrates with OpenAI’s function calling and web/file search
capabilities【86686542789695†L322-L364】.  You may consider exploring
this SDK if you operate in the OpenAI ecosystem and are willing to
allow network access.  No stub script is included due to the external
dependency.

When integrating any of these frameworks, always evaluate whether
network access or external APIs are required, and ensure you maintain
ethical guidelines.  These frameworks provide a rich set of options for
building aggressive, world‑class multi‑agent systems.
