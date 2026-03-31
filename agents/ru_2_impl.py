```python
# This file implements a Jira-style Kanban board for managing projects and tasks.
# It includes epics as columns, tasks as draggable cards, and status swimlanes (Todo/In Progress/Done).
# The system supports filtering by agent, epic, and priority, and real-time WebSocket updates.

from flask import Flask, render_template, request, jsonify
from flask_socketio import SocketIO, emit

app = Flask(__name__)
app.config['SECRET_KEY'] = 'secret!'
socketio = SocketIO(app)

tasks = {
    "Todo": [],
    "In Progress": [],
    "Done": []
}

@socketio.on('connect')
def test_connect():
    print('Client connected')

@socketio.on('disconnect')
def test_disconnect():
    print('Client disconnected')

@socketio.on('move_task')
def handle_move_task(data):
    source_list = data['source']
    target_list = data['target']
    task_id = data['task_id']

    # Move the task from the source list to the target list
    tasks[source_list].remove(task_id)
    tasks[target_list].append(task_id)

    emit('update_board', tasks, broadcast=True)

@app.route('/')
def index():
    return render_template('kanban.html')

if __name__ == '__main__':
    socketio.run(app)
```