"""Tests for the Item API."""
import pytest
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from {{name}}.api.models import Item


@pytest.fixture
def api_client():
    return APIClient()


@pytest.fixture
def item(db):
    return Item.objects.create(title="Test Item", description="A test item")


@pytest.mark.django_db
def test_health_check(api_client):
    url = reverse("health")
    response = api_client.get(url)
    assert response.status_code == status.HTTP_200_OK
    assert response.data["status"] == "ok"


@pytest.mark.django_db
def test_list_items_empty(api_client):
    url = reverse("item-list")
    response = api_client.get(url)
    assert response.status_code == status.HTTP_200_OK


@pytest.mark.django_db
def test_create_item(api_client):
    url = reverse("item-list")
    response = api_client.post(url, {"title": "New Item"}, format="json")
    assert response.status_code == status.HTTP_201_CREATED
    assert response.data["title"] == "New Item"


@pytest.mark.django_db
def test_get_item(api_client, item):
    url = reverse("item-detail", kwargs={"pk": item.pk})
    response = api_client.get(url)
    assert response.status_code == status.HTTP_200_OK
    assert response.data["id"] == item.pk


@pytest.mark.django_db
def test_update_item(api_client, item):
    url = reverse("item-detail", kwargs={"pk": item.pk})
    response = api_client.patch(url, {"title": "Updated"}, format="json")
    assert response.status_code == status.HTTP_200_OK
    assert response.data["title"] == "Updated"


@pytest.mark.django_db
def test_delete_item(api_client, item):
    url = reverse("item-detail", kwargs={"pk": item.pk})
    response = api_client.delete(url)
    assert response.status_code == status.HTTP_204_NO_CONTENT
    assert not Item.objects.filter(pk=item.pk).exists()
