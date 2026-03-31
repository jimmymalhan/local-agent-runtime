```python
# This file implements real-time chat responses using Nexus streaming and Server-Sent Events (SSE) for faster perceived response.

from flask import Flask, Response, stream_with_context
import nexus

app = Flask(__name__)

@app.route('/api/chat', methods=['POST'])
def chat():
    def generate_response():
        # Assuming `nexus.chat` is a function that handles the chat logic and yields tokens
        for token in nexus.chat(stream=True):
            yield f"data: {token}\n\n"

    return Response(stream_with_context(generate_response()), content_type='text/event-stream')

if __name__ == '__main__':
    app.run(debug=True)
```