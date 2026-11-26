PY ?= python
VENV ?= .venv

.PHONY: help install dev-api dev-worker test lint format migrate seed up down logs frontend

help:
	@echo "OPERATION ZERO — common targets"
	@echo "  make install     install backend + frontend dependencies"
	@echo "  make dev-api     run the API with reload on :8000"
	@echo "  make dev-worker  run health-check + alert workers"
	@echo "  make test        run backend test suite"
	@echo "  make migrate     apply database migrations"
	@echo "  make seed        load the synthetic demo workspace"
	@echo "  make up          docker compose up --build"
	@echo "  make down        docker compose down"

install:
	$(PY) -m venv $(VENV)
	$(VENV)/bin/pip install -r backend/requirements.txt -r backend/requirements-dev.txt
	cd frontend && npm install

dev-api:
	cd backend && uvicorn app.main:app --reload --port 8000

dev-worker:
	cd backend && python -m app.workers.runner

test:
	cd backend && $(PY) -m pytest -q

lint:
	cd backend && ruff check app tests && ruff format --check app tests

format:
	cd backend && ruff format app tests

migrate:
	cd backend && alembic upgrade head

seed:
	cd backend && python -m app.scripts.seed_demo

up:
	docker compose up --build

down:
	docker compose down -v

frontend:
	cd frontend && npm run dev
