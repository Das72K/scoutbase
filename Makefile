# SCOUTBASE developer commands. Requires Docker, uv and a .env (cp .env.example .env).

-include .env
export

ALEMBIC := uv run alembic -c db/alembic.ini

.PHONY: up down migrate downgrade psql test reset

up:  ## Start Postgres and wait until it is healthy
	docker compose up -d --wait db

down:  ## Stop containers (data volume is kept)
	docker compose down

migrate:  ## Apply all migrations
	$(ALEMBIC) upgrade head

downgrade:  ## Roll back one migration (make downgrade REV=base for all)
	$(ALEMBIC) downgrade $(or $(REV),-1)

psql:  ## Open psql inside the db container as the owner
	docker compose exec db psql -U $(POSTGRES_USER) -d $(POSTGRES_DB)

test:  ## Run the test suite against the running database
	uv run pytest -v

reset:  ## Destroy the data volume and rebuild from scratch
	docker compose down -v
	$(MAKE) up
	$(MAKE) migrate
