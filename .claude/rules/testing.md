# Testing Standards

## Test Categories (All Required)
- **Unit tests** - individual functions and helpers
- **Integration tests** - module interactions and orchestration
- **E2E tests** - full user workflows (UI to database)
- **Retry tests** - failure injection and recovery
- **Permission tests** - access control verification
- **Audit tests** - logging and immutability
- **Contract tests** - API response validation

## Test Execution
```bash
npm test           # All tests with coverage (Jest)
npm run test:ci    # CI mode for GitHub Actions
npm run test:watch # Development watch mode
npm run test:e2e   # End-to-end tests (requires API)
```

## Coverage Minimums
- **Global**: 60% (branches, functions, lines, statements)
- **Critical modules**: 85%
- **State machine**: 90%
- **Orchestration**: 90%
- **Security modules**: 90%

## Test File Naming
- Unit: `tests/unit/<module>.test.js` or `tests/<module>.test.js`
- Integration: `tests/integration/<module>.test.js`
- E2E: `tests/e2e/<scenario>.test.js`
- Component: `tests/components/<component>.test.js`
- Fixtures: `tests/fixtures/<name>.js`

## Test Structure
```javascript
describe('Module Name', () => {
  describe('happy path', () => {
    it('should complete successfully', () => { ... });
    it('should return expected output', () => { ... });
  });

  describe('error handling', () => {
    it('should retry on transient error', () => { ... });
    it('should fail after max retries', () => { ... });
  });

  describe('edge cases', () => {
    it('should handle empty input', () => { ... });
    it('should handle malformed data', () => { ... });
  });

  describe('permissions', () => {
    it('should deny access to unauthorized user', () => { ... });
  });
});
```

## Critical Workflows to Test
1. **Request Intake** - form submission → validation → API call
2. **Pipeline Execution** - orchestration → 4 agents → output
3. **Error Recovery** - network error → retry → success/failure
4. **Permission Enforcement** - unauthorized access denied
5. **Audit Logging** - action → log entry → retrieval
6. **State Transitions** - valid transitions only
7. **Timeout Handling** - request timeout → retry → success/fail

## Before Releasing to Production
- [ ] `npm test` passes with 100% of tests passing
- [ ] `npm run test:ci` passes in GitHub Actions
- [ ] All critical workflows tested locally or with E2E
- [ ] Coverage >= minimum thresholds
- [ ] Retry logic tested with simulated failures
- [ ] Permission checks tested with denied access
- [ ] Audit trail verified with log retrieval
- [ ] UI states tested on localhost:3000
- [ ] Rollback path verified as safe

## Flaky Tests
If a test fails intermittently:
1. Run it 10 times: `npm run test:watch -- --testNamePattern="test name"`
2. Identify the race condition or timing issue
3. Fix the test or code, never disable tests
4. Document the issue in CHANGELOG.md
5. Add deterministic test to prevent regression

## Test Output
After running tests, verify:
- All test names clearly describe what they test
- Failure messages explain what went wrong
- Coverage report shows which lines are untested
- No warnings or deprecation messages

## GitHub Actions Integration
Tests run automatically on:
- Pull requests to main
- Pushes to main
- Manual workflow dispatch

Coverage reports uploaded to artifacts for review.

## E2E Test Requirements
```bash
export ANTHROPIC_API_KEY=sk-ant-...
npm run test:e2e
```

E2E tests require valid API credentials and count against billing.
Run E2E only:
- Before major releases
- When critical flows change
- When external API behavior changes
