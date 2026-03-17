# Confidence Scoring System

## Scoring Rubric
### 95-100: Critical Flows Verified + Unknowns Documented
- All critical workflows tested locally
- All critical workflows passed in GitHub Actions
- Tests show 90%+ coverage
- Error cases covered and tested
- Rollback path verified and tested
- .claude/CONFIDENCE_SCORE.md updated with full evidence
- No major unknowns; residual risks listed

### 80-94: Strong Proof with Minor Open Items
- Code changes match approved plan exactly
- Tests pass locally and in GitHub Actions
- Critical workflows verified manually or with E2E tests
- 80%+ code coverage
- Error handling verified for main failure modes
- Rollback documented and appears safe
- Minor unknowns documented (edge cases, rare scenarios)
- CHANGELOG updated

### 60-79: Implemented but Incomplete Proof
- Code changes implemented
- Tests pass but some critical flows untested
- Coverage 60-80%
- Assumptions present in implementation
- Error handling partial
- Rollback path identified but not tested
- Significant unknowns remain
- Manual testing required before production use

### 40-59: Partial Evidence
- Implementation in progress or incomplete
- Tests pass but only for happy path
- Coverage <60%
- Major critical flows untested
- Error cases not handled
- Assumptions not verified
- This stage requires more work before production

### 0-39: Unverified — No Evidence
- No tests run
- Changes made without verification
- Unknowns outnumber known factors
- Do not release to production

## Score Updates Required When
- Code changes are made to critical paths
- Tests are added or modified
- New failure modes are discovered
- Assumptions are verified or disproven
- Rollback path changes
- GitHub Actions workflow status changes

## Evidence Structure for .claude/CONFIDENCE_SCORE.md
```markdown
## [Task Name]
- **Files changed**: src/x.js, tests/x.test.js
- **Tests run**: `npm test` - 319 passing
- **GitHub Actions**: workflow #123 passed on commit abc123def
- **Critical flows verified**:
  - [Flow 1]: [verification step]
  - [Flow 2]: [verification step]
- **Edge cases checked**: [what was tested]
- **Error handling**: [covered scenarios]
- **Unknowns**: [list any assumptions]
- **Residual risks**: [what could still fail]
- **Rollback**: [how to revert safely]
- **Confidence**: 87/100 (reason with evidence)
```

## Special Rules
### Cannot Exceed 79 If:
- Critical workflow is untested
- New code has 0% test coverage
- Assumptions outnumber verified facts
- Rollback path unknown or unsafe
- Error recovery untested

### Must Include [UNKNOWN] If:
- External API behavior uncertain
- User behavior not verified
- Infrastructure detail assumed
- Third-party library behavior assumed
- Edge case not tested

### Cannot Claim 100 Unless:
- All critical flows pass tests
- All tests pass in GitHub Actions
- Manual verification completed
- Rollback tested and safe
- No unknowns or all unknowns documented with mitigation

### Merge Gate (HARD):
**Do NOT merge any branch until confidence is 100%** with evidence: local npm test 100% pass, all CI jobs 100% pass, all QA types 100%, additional tests 100%, docs/CONFIDENCE_SCORE.md updated. Block merge if any check fails.

## Examples

### Example 1: High Confidence (92)
```markdown
## Fix retry logic in API client
- Files: src/api-client.js, tests/api-client.test.js
- Tests: 319 passing (npm test output verified)
- GitHub: workflow #451 passed
- Critical flows:
  - Network failure → auto-retry → success: TESTED (mock network failure)
  - Max retries exceeded → error thrown: TESTED (retry limit scenario)
  - Exponential backoff: TESTED (timeout assertions)
- Edge cases:
  - Partial response: TESTED
  - Request timeout: TESTED
  - Invalid response JSON: TESTED
- Unknowns: Response timeout behavior in production (rare)
- Residual risk: Long-running request could still timeout if network is very slow
- Rollback: Revert src/api-client.js to previous commit
- Confidence: 92/100 (minor unknown about production network conditions)
```

### Example 2: Low Confidence (45)
```markdown
## Add new validation rule
- Files: src/validator.js
- Tests: 3 new tests added, 2 passing, 1 failing
- GitHub: workflow pending
- Critical flows:
  - Valid input: NOT TESTED
  - Invalid input: PARTIALLY TESTED (1 case only)
- Error handling: NOT IMPLEMENTED
- Unknowns: Does this break existing validation? What are edge cases?
- Residual risk: Other validators might conflict
- Rollback: Straightforward revert
- Confidence: 45/100 (incomplete tests, untested critical flows, unknowns outweigh evidence)
```
