# Backend Standards

## Production-Grade Reliability
Every critical path must include:
- **Validation** - input, contract, state, permissions
- **Retries** - exponential backoff for transient failures
- **Timeout** - prevent hanging requests
- **Idempotency** - safe to retry same request
- **Logging** - structured logs with trace IDs
- **Error handling** - type, severity, recovery path
- **Fallback** - graceful degradation on failure
- **Rollback** - safe revert for bad state

## API Endpoints
Each endpoint must handle:
- Missing required fields (400 + message)
- Invalid field types (400 + message)
- Permission denied (403 + message)
- Resource not found (404 + message)
- Rate limit exceeded (429 + retry-after)
- Server error (500 + trace ID + retry guidance)
- Timeout (503 + trace ID + manual retry path)

## Error Response Format
```javascript
{
  "error": "error_code_name",
  "message": "User-friendly description",
  "traceId": "trace-12345678",
  "status": 400,
  "suggestion": "What user should do next",
  "retryable": true,
  "retryAfter": 2
}
```

## State Machine Transitions
- Only allow valid transitions
- Validate state before each action
- Use atomic updates (no partial state)
- Log all state changes
- Reject invalid operations clearly

## Retry Logic
```javascript
// Exponential backoff: 1s, 2s, 4s, 8s (max)
const backoffMs = Math.min(1000 * Math.pow(2, retryCount), 8000);
```

Retry on:
- Network errors (connection reset, timeout)
- Server errors (5xx)
- Transient failures (rate limit 429)

Do NOT retry on:
- Client errors (400, 403, 404)
- Invalid input
- Permission denied
- Already processed (idempotency check)

## Validation Rules
- Validate at API boundary (req.body, req.params)
- Validate before state changes
- Validate permissions before operations
- Return clear error messages
- Never let invalid data enter system

## Logging Requirements
Every critical operation must log:
```javascript
logger.info('Operation completed', {
  traceId,
  operation: 'action_name',
  userId: user.id,
  input: sanitizedInput,
  output: sanitizedOutput,
  duration: endTime - startTime,
  status: 'success'
});
```

Sensitive fields (passwords, tokens, PII) must be sanitized.

## Observable Metrics
- Request count by endpoint
- Error count by type
- Latency by percentile (p50, p95, p99)
- Retry count and success rate
- State machine transition frequency
- Permission denial count

## Database/Persistence
- Use transactions for multi-step operations
- Verify state before update
- Log all writes with user context
- Implement soft deletes (archive instead of destroy)
- Audit trail for compliance

## Dependencies
- All external calls have timeouts
- Graceful fallback if dependency fails
- Circuit breaker for failing dependencies
- Clear error messages for dependency issues

## Testing Requirements
- Unit test validation logic
- Unit test retry behavior
- Integration test full workflow
- E2E test with real API calls
- Failure injection test (mock failures)
- Permission test (denied access)
- Timeout test (slow responses)

## Deployment Safety
- Backward compatibility with prior version
- Feature flags for gradual rollout
- Monitoring for error rate spikes
- Canary deployment for risky changes
- Rollback procedure documented and tested
