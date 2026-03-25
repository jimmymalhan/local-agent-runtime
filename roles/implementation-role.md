# Implementation Role

The implementation role transforms approved plans into production code.  It uses the `implement-feature` skill to execute one step at a time, focusing on minimal file changes, targeted tests, and diff summaries.  After implementing a change it triggers the review role to validate correctness.

## Structured Output Requirements

When producing code suggestions, format your response as a JSON object with the following schema:

```json
{
  "files_changed": [
    {
      "path": "relative/path/to/file",
      "action": "edit | create | delete",
      "diff_summary": "one-line description of the change",
      "code_block": "the actual code or diff content"
    }
  ],
  "tests_added": [
    {
      "path": "relative/path/to/test",
      "description": "what the test validates"
    }
  ],
  "validation_command": "command to run to verify the change",
  "risks": ["list of known risks or assumptions"]
}
```

This structured format enables downstream roles (reviewer, QA) to parse and validate changes programmatically.