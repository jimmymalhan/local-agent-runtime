# API Endpoint Standards

**Scope:** All REST API endpoints in `src/` and `/api/*` routes

## Error Handling Contract

Every endpoint must return proper HTTP status and error format:

```javascript
// 400 Bad Request (client error)
{ "error": "validation_error", "message": "Incident required", "field": "incident" }

// 403 Forbidden (permission denied)
{ "error": "permission_denied", "message": "Insufficient permissions" }

// 404 Not Found
{ "error": "not_found", "message": "Resource not found" }

// 429 Rate Limited
{ "error": "rate_limit", "message": "Too many requests", "retryAfter": 60 }

// 500 Server Error (include trace ID)
{ "error": "internal_error", "message": "An error occurred", "traceId": "trace-123" }

// 503 Service Unavailable
{ "error": "service_unavailable", "message": "API temporarily unavailable", "retryAfter": 30 }
```

## Critical Path Endpoints

### POST /api/diagnose
- **Input validation**: incident (required, 10-2000 chars)
- **Output**: { id, incident, result { router, retriever, skeptic, verifier }, timestamp }
- **Errors**: validation_error, timeout, api_error, internal_error
- **Timeout**: 60 seconds (triggers auto-retry)
- **Retry**: Automatic on network/5xx errors (max 2 retries)

### GET /api/diagnose/:id
- **Input validation**: id format (UUID)
- **Output**: Full diagnosis result with timestamp
- **Errors**: not_found, permission_denied

### POST /api/batch-diagnose
- **Input validation**: incidents array (1-100 items)
- **Output**: Array of { id, result, status }
- **Errors**: validation_error, batch_limit_exceeded

## Testing Requirements

Before merging any API changes:
```bash
# 1. Test happy path (valid input → 200 with correct structure)
npm test -- --testNamePattern="POST /api/diagnose"

# 2. Test error cases (invalid input → proper error response)
npm test -- --testNamePattern="error cases"

# 3. Test retry logic (simulated failures)
npm test -- --testNamePattern="retry"

# 4. Integration test (full flow with real API)
npm run test:e2e
```

## Performance Budgets
- Single diagnosis: < 30 seconds (p95)
- Batch diagnosis: < 2 seconds per incident (p95)
- API response: < 500ms from request to response frame

## Security
- Input validation on all fields (client + server)
- Rate limiting: 100 requests/hour per IP
- No PII in error messages
- Sensitive data encrypted in logs
- CORS headers set properly

## Documentation
Every endpoint must be documented in:
- `public/api-reference.html` (user-facing docs)
- Inline code comments (for developers)
- CHANGELOG.md (when adding/changing endpoints)
