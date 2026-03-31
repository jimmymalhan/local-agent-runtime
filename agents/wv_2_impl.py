```python
# This script sets up a WebSocket server that listens for state updates from agent nodes.
# It then broadcasts these updates to connected clients, allowing them to visualize the workflow graph in real-time.

import asyncio
from websockets import serve

async def handle_state_update(websocket, path):
    async for message in websocket:
        # Process incoming state update (e.g., active, idle, error)
        state = message
        print(f"Received state update: {state}")
        
        # Broadcast the state update to all connected clients
        await asyncio.wait([client.send(state) for client in connected_clients])

connected_clients = set()

async def main():
    async with serve(handle_state_update, "localhost", 8765):
        global connected_clients
        while True:
            new_client = await websocket.accept()
            connected_clients.add(new_client)
            print("Client connected")

# Run the WebSocket server
asyncio.run(main())
```