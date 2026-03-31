```python
# This script sets up a WebSocket server that listens for state updates from agent nodes.
# It then broadcasts these updates to connected clients to highlight live nodes in a workflow graph.

import asyncio
from websockets import serve

async def handle_state(websocket, path):
    async for message in websocket:
        # Process the incoming state update (e.g., active, idle, error)
        state = message
        
        # Broadcast the state update to all connected clients
        await broadcast(state)

# Function to broadcast messages to all connected clients
async def broadcast(message):
    for client in clients:
        await client.send(message)

# Set up a set to keep track of connected clients
clients = set()

start_server = serve(handle_state, "localhost", 8765)

asyncio.get_event_loop().run_until_complete(start_server)
asyncio.get_event_loop().run_forever()
```