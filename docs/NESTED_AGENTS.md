# Nested Sub‑Agents and Phased Execution

To minimise hallucination and ensure reliable outcomes, complex tasks
should be decomposed into smaller phases handled by **nested sub‑agents**.
Each sub‑agent focuses on a specific step — such as context
retrieval, plan generation, implementation or evaluation — enabling
clear division of responsibilities and systematic reasoning.  This
approach mirrors the “agentic RAG” workflow, where agents not only
retrieve data but also evaluate and decide which information to trust or
discard【462684992376271†L160-L174】.

## Why Use Sub‑Agents?

Large language models are prone to hallucinations when they tackle
multiple goals simultaneously or when context becomes unwieldy.  By
splitting work into distinct agents and sub‑agents, you constrain the
problem space for each component and provide targeted context.  Sub‑agents
can run concurrently or sequentially depending on the nature of the
task, and they can feed results back up to the parent agent for
integration.

Benefits include:

* **Reduced hallucination:** Each sub‑agent sees only the context
  relevant to its phase, improving accuracy and factuality.
* **Parallelism:** Independent sub‑agents can run concurrently,
  accelerating throughput for large workflows.
* **Reusability:** Sub‑agents (e.g. a retrieval module or a code
  linter) can be reused in multiple workflows, reducing duplication.
* **Robustness:** If one sub‑agent fails, the parent agent can retry
  or adjust the plan without derailing the entire process.

## Designing Sub‑Agent Trees

When designing nested sub‑agents, consider the following patterns:

1. **Linear phases:** A parent agent delegates sequential steps to
   child agents.  For example, an **implementation** agent might first
   call a **retrieval** sub‑agent for context, then a **planning**
   sub‑agent to outline tasks, then one or more **execution** sub‑agents
   to apply code changes, followed by a **review** sub‑agent.
2. **Branching tasks:** A parent agent invokes several child agents
   in parallel to explore different approaches or handle independent
   components.  The parent then consolidates the results and selects
   the best option.
3. **Recursive refinement:** A sub‑agent can spawn its own sub‑agents
   when it encounters a complex subproblem.  For example, a test
   generation agent might call smaller agents to generate unit tests
   for each module.

## Implementing Nested Agents in This Repository

The shell scripts in `agents/` are intentionally simple, logging
commands instead of executing them directly.  To implement nested
sub‑agents:

1. **Write sub‑agent scripts** in `agents/` for each phase.  For
   example, create `retrieval-agent.sh`, `plan-agent.sh`,
   `execute-step-agent.sh` and `evaluate-agent.sh`.  Each script
   receives the user prompt and any intermediate results.
2. **Update parent agents** to call these sub‑agents in the desired
   order.  For instance, modify `implementation-agent.sh` to call
   `retrieval-agent.sh` and then `plan-agent.sh` before generating
   code.
3. **Use environment variables** or workflow definitions to control
   which sub‑agents run.  This allows you to switch between simple and
   complex pipelines without editing code.
4. **Log intermediate results** to the `memory/` or `logs/` directory.
   Parent agents can read these files to decide next steps.  This
   ensures that sub‑agent outputs persist and can be reviewed later.

## Example: Multi‑Step RAG Workflow

Suppose you want to build a knowledge agent that answers questions
about your company’s policies.  You can set up a nested agent
hierarchy like this:

1. **Top‑level agent:** Receives the user question.
2. **Retrieval sub‑agent:** Queries the local vector store and returns
   relevant policy documents.
3. **Evaluation sub‑agent:** Reads the retrieved documents and filters
   out irrelevant or outdated information.
4. **Synthesis sub‑agent:** Summarises the filtered documents and
   prepares a structured answer.
5. **Generation sub‑agent:** Combines the summary with the original
   question to craft a natural‑language response.

By delegating each phase to a dedicated agent, you make the system
modular, testable and easier to improve over time.  You can further
extend this pattern by adding a **feedback sub‑agent** that captures
user feedback and triggers skill evolution.