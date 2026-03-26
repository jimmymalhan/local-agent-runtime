# {{name}}

Django REST Framework API with PostgreSQL and Celery.

## Quick start

```bash
pip install -r requirements.txt
python manage.py migrate
python manage.py runserver
```

## Celery worker

```bash
celery -A {{name}}.celery.app worker --loglevel=info
```

## Tests

```bash
pytest -v
```

## Docker

```bash
docker compose up -d
```

## Project structure

```
{{name}}/
  settings/base.py   # Django settings
  api/               # DRF models, serializers, views, urls
  celery/app.py      # Celery application
  urls.py            # Root URL conf
tests/               # pytest-django test suite
```
