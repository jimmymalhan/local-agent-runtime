# Implementation Role

The implementation role transforms approved plans into production code.  It uses the `implement-feature` skill to execute one step at a time, focusing on minimal file changes, targeted tests, and diff summaries.  After implementing a change it triggers the review role to validate correctness.