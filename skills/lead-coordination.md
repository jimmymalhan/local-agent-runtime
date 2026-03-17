# Skill: Lead + Subagent Coordination

**Trigger:** When running multi-role tasks that need faster parallel execution, shared planning, and skill-based sub-agent pickup.

**Principle:** Start with a common plan. The lead (planner/architect) defines work items. Subagents (based on skills) pick tasks and run simultaneously. All agents keep upgrading their skill set.

**Flow:**
1. **Common plan:** Planner produces a task breakdown. Architect assigns roles and handoffs.
2. **Skill-based pick:** Each role reads the plan and selects the subset that matches its skill (researcher=map repo, retriever=pull context, implementer=code, reviewer=critique, optimizer=speed/cost, benchmarker=gap analysis).
3. **Resource-aware grouping:** Keep heavy models paired with lighter roles so the total machine load stays under the 70 percent CPU and memory ceilings.
4. **Simultaneous work:** Roles in the same group run in parallel (`group_order` in `config/runtime.json`). No blocking inside a group.
5. **Lead handoff:** Summarizer receives all outputs and produces the final answer. Benchmarker compares against the target bar. Review always runs before the final answer is accepted.

**Coordination rules:**
- Researcher and Retriever run first in parallel; they prepare context.
- Planner and Architect run next in parallel; they produce the plan.
- Implementer, Tester, Reviewer run in parallel where dependencies allow.
- Subagents never wait for each other within a group—use shared_outputs from prior groups only.
- The lead must route upgrade, RAG, SGLang, Pinecone, and MCP tasks to the matching skills before execution.

**Skill upgrades:** Each role's output should cite what it learned. The next run inherits improved context. Skills in `skills/` define triggers—agents pick based on task keywords.
