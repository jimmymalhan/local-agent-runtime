# CLI Standards

**Scope:** Command-line interfaces in `src/local-pipeline.js` and `src/run.js`

## Commands

### npm run diagnose [incident]
- **Purpose**: Diagnose an incident using the full 4-agent pipeline
- **Input**: Incident description (required, 10-2000 chars)
- **Output**: Formatted diagnosis with router, retriever, skeptic, verifier results
- **Example**: `npm run diagnose "Database query takes 45 seconds"`

### npm start
- **Purpose**: Start the web server with UI and API
- **Output**: Server running on http://localhost:3000
- **Timeout**: 60 seconds per diagnosis request

### npm test
- **Purpose**: Run all tests with coverage report
- **Pass criteria**: All tests pass, coverage ≥ 60% global
- **Output**: Test summary with passing/failing counts

### npm run test:e2e
- **Purpose**: End-to-end tests with real API calls
- **Requirements**: ANTHROPIC_API_KEY set in .env
- **Cost**: Uses API credits
- **Output**: Test results with diagnosis examples

## Output Format

### Console Output (User-Friendly)
```
🔍 Diagnosing incident...
┌─ Router: [classification]
├─ Retriever: [evidence summary]
├─ Skeptic: [competing theory]
└─ Verifier: [root cause + confidence]

✅ Diagnosis Complete (took 24.5 seconds)
Confidence: 94/100
```

### Error Output
```
❌ Error: validation_error
Message: Incident must be 10-2000 characters
Suggestion: Provide more detail about the failure
Retry: npm run diagnose "Your full incident description here"
```

## Exit Codes
- `0` - Success (diagnosis complete)
- `1` - Validation error (invalid input)
- `2` - API error (timeout, network failure)
- `3` - Internal error (unhandled exception)

## Performance Targets
- Diagnose command: < 30 seconds (p95)
- Response time: immediate (< 1s) to show status
- No hanging processes

## Logging
- Info: Normal operation messages
- Warn: Retries, timeouts approaching
- Error: Validation errors, API failures
- Debug: (disabled in production)

## Testing
Before releasing CLI changes:
```bash
# Test happy path
npm run diagnose "Database query takes 45 seconds"

# Test error path (invalid input)
npm run diagnose "short"

# Test timeout scenario
npm run diagnose "Long incident description" --timeout=1

# Check exit code
npm run diagnose "test"; echo "Exit: $?"
```
