---
name: generate_marketing_plan
description: Generate a growth and marketing plan based on current market insights.
trigger: >
  When the user asks for a marketing or growth plan, or when a new feature
  is ready for launch.
inputs:
  - project_summary: Summary of the project or product from context.
  - market_data: Local market research documents or summaries.
commands: |
  1. Review the project summary and market data to identify target audiences,
     competitors and differentiators.
  2. Outline a marketing plan including objectives, key messages, channels,
     timelines and success metrics.
  3. Propose at least two experiments to test growth hypotheses.
  4. Write the plan to `memory/marketing-plan.md` and summarise the key points.
output: >
  A marketing plan document stored under `memory/`, plus a concise summary
  of the plan to include in the assistant’s response.
stop_condition: >
  The plan has been written to memory and the summary has been generated.
---

Use this skill to produce detailed growth strategies without external APIs.  Keep
recommendations actionable and aligned with the available offline channels.
