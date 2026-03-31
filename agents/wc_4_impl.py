```python
import time
import logging

# This script implements an exponential backoff strategy for agent restarts,
# with a health probe before each restart attempt. It logs the reason for each restart
# and alerts after 5 unsuccessful attempts.

def is_agent_healthy():
    # Placeholder function to simulate agent health check
    return False  # Change this to actual health check logic

def log_restart_reason(reason):
    logging.info(f"Restarting agent due to: {reason}")

def exponential_backoff_restarts(max_attempts=5, initial_delay=60):
    attempts = 0
    delay = initial_delay
    
    while attempts < max_attempts:
        if is_agent_healthy():
            logging.info("Agent is healthy. No restart needed.")
            return
        
        log_restart_reason(f"Attempt {attempts + 1} failed")
        
        time.sleep(delay)
        attempts += 1
        delay *= 2  # Double the delay for next attempt
    
    logging.error("Max restart attempts reached. Alerting...")
    # Placeholder for alerting mechanism

if __name__ == "__main__":
    exponential_backoff_restarts()
```