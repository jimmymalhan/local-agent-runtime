# Grounded Answer Corpus

Template for saving good local answers with review feedback. These entries serve as few-shot examples for planner, QA, and summarizer roles.

## Entry Template

### Answer ID: [YYYY-MM-DD-NNN]
- **Task**: [Original user request]
- **Model**: [Model used, e.g. qwen2.5-coder:7b]
- **Profile**: [Runtime profile, e.g. balanced]

#### Answer
```
[The full answer text that was graded as good]
```

#### Review Feedback
- **Plan Accuracy**: [score]/100 - [brief justification]
- **Code Correctness**: [score]/100 - [brief justification]
- **Hallucination Rate**: [score]/100 - [brief justification]
- **Actionability**: [score]/100 - [brief justification]
- **Composite Score**: [score]/100

#### What Made This Answer Good
- [Specific quality 1]
- [Specific quality 2]
- [Specific quality 3]

#### Reviewer Notes
[Free-form notes from the reviewer about what to replicate]

---

## Saved Answers

(Add entries below as good answers are identified during local runs.)

---

## Usage

1. During planner stage: include 1-2 relevant grounded answers as few-shot context.
2. During QA stage: compare current output against the closest grounded answer.
3. During summarizer stage: use grounded answer style as a quality reference.
4. Periodically prune entries older than 30 days or below composite score 80.
