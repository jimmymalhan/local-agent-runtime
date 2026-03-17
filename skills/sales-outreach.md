---
name: sales_outreach
description: Prepare sales outreach materials and pipeline updates.
trigger: >
  When the user requests sales collateral or needs to update the sales pipeline.
inputs:
  - lead_list: A CSV or markdown file containing qualified leads.
  - product_summary: A description of the product’s features and benefits.
commands: |
  1. For each lead, draft a personalised outreach email using the product summary
     and any notes in the lead list.  Store these drafts in `memory/sales-emails/<lead_name>.md`.
  2. Create a one-page sales brief that highlights key benefits and case studies.
     Save this under `memory/sales-brief.md`.
  3. Update the local sales pipeline document (`memory/sales-pipeline.md`)
     with next steps and follow-up dates.
output: >
  A set of email drafts, a sales brief and an updated pipeline document in
  the `memory/` folder.
stop_condition: >
  All outreach materials are saved and the pipeline document is updated.
---

This skill automates the preparation of sales materials while keeping the
pipeline up to date.  It does not send emails; actual sending must be done
manually or via a local email client.
