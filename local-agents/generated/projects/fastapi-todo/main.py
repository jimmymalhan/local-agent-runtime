from typing import List

from fastapi import FastAPI, Depends, HTTPException, status
from sqlalchemy.orm import Session

from database import Base, engine, get_db
from models import Todo
from schemas import TodoCreate, TodoUpdate, TodoResponse

Base.metadata.create_all(bind=engine)

app = FastAPI(title="TODO API")


@app.post("/todos", response_model=TodoResponse, status_code=status.HTTP_201_CREATED)
def create_todo(todo: TodoCreate, db: Session = Depends(get_db)):
    db_todo = Todo(**todo.model_dump())
    db.add(db_todo)
    db.commit()
    db.refresh(db_todo)
    return db_todo


@app.get("/todos", response_model=List[TodoResponse])
def list_todos(skip: int = 0, limit: int = 100, db: Session = Depends(get_db)):
    return db.query(Todo).offset(skip).limit(limit).all()


@app.get("/todos/{todo_id}", response_model=TodoResponse)
def get_todo(todo_id: int, db: Session = Depends(get_db)):
    todo = db.query(Todo).filter(Todo.id == todo_id).first()
    if todo is None:
        raise HTTPException(status_code=404, detail="Todo not found")
    return todo


@app.patch("/todos/{todo_id}", response_model=TodoResponse)
def update_todo(todo_id: int, todo_update: TodoUpdate, db: Session = Depends(get_db)):
    todo = db.query(Todo).filter(Todo.id == todo_id).first()
    if todo is None:
        raise HTTPException(status_code=404, detail="Todo not found")
    for field, value in todo_update.model_dump(exclude_unset=True).items():
        setattr(todo, field, value)
    db.commit()
    db.refresh(todo)
    return todo


@app.delete("/todos/{todo_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_todo(todo_id: int, db: Session = Depends(get_db)):
    todo = db.query(Todo).filter(Todo.id == todo_id).first()
    if todo is None:
        raise HTTPException(status_code=404, detail="Todo not found")
    db.delete(todo)
    db.commit()
    return None


if __name__ == "__main__":
    from fastapi.testclient import TestClient

    client = TestClient(app)

    # POST /todos - create
    resp = client.post("/todos", json={"title": "Buy milk", "description": "2% milk"})
    assert resp.status_code == 201, f"Expected 201, got {resp.status_code}"
    todo = resp.json()
    assert todo["title"] == "Buy milk"
    assert todo["description"] == "2% milk"
    assert todo["completed"] is False
    assert "id" in todo
    todo_id = todo["id"]

    # POST /todos - create second
    resp2 = client.post("/todos", json={"title": "Walk dog"})
    assert resp2.status_code == 201

    # GET /todos - list all
    resp = client.get("/todos")
    assert resp.status_code == 200
    todos = resp.json()
    assert len(todos) >= 2

    # GET /todos/{id} - get one
    resp = client.get(f"/todos/{todo_id}")
    assert resp.status_code == 200
    assert resp.json()["title"] == "Buy milk"

    # GET /todos/{id} - not found
    resp = client.get("/todos/9999")
    assert resp.status_code == 404

    # PATCH /todos/{id} - update
    resp = client.patch(f"/todos/{todo_id}", json={"completed": True, "title": "Buy oat milk"})
    assert resp.status_code == 200
    updated = resp.json()
    assert updated["completed"] is True
    assert updated["title"] == "Buy oat milk"
    assert updated["description"] == "2% milk"  # unchanged

    # PATCH /todos/{id} - not found
    resp = client.patch("/todos/9999", json={"title": "nope"})
    assert resp.status_code == 404

    # DELETE /todos/{id}
    resp = client.delete(f"/todos/{todo_id}")
    assert resp.status_code == 204

    # DELETE /todos/{id} - already deleted
    resp = client.delete(f"/todos/{todo_id}")
    assert resp.status_code == 404

    # Verify deleted
    resp = client.get(f"/todos/{todo_id}")
    assert resp.status_code == 404

    # Verify remaining
    resp = client.get("/todos")
    assert resp.status_code == 200
    assert len(resp.json()) == 1

    print("All assertions passed.")
