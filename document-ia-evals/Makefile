.PHONY: help setup-db start-db stop-db reset-db run clean migrate

help: ## Show this help message
	@echo "Available commands:"
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-15s\033[0m %s\n", $$1, $$2}'

setup-db: ## Initial database setup (start DB + run migrations)
	@echo "🔧 Setting up database..."
	@chmod +x scripts/setup_db.sh
	@./scripts/setup_db.sh

start-db: ## Start the PostgreSQL container
	@echo "▶ Starting PostgreSQL..."
	@docker compose up -d postgres

stop-db: ## Stop the PostgreSQL container
	@echo "⏸ Stopping PostgreSQL..."
	@docker compose down

reset-db: ## Reset database (WARNING: deletes all data!)
	@echo "⚠️  Resetting database (this will delete all data)..."
	@docker compose down -v
	@docker compose up -d postgres
	@sleep 3
	@alembic upgrade head
	@echo "✓ Database reset complete"

migrate: ## Run database migrations
	@echo "▶ Running migrations..."
	@alembic upgrade head

run: ## Start the Streamlit application
	@echo "🚀 Starting Streamlit app..."
	@streamlit run src/document_ia_evals/app.py --server.runOnSave true 

clean: ## Stop containers and clean up
	@echo "🧹 Cleaning up..."
	@docker compose down
	@echo "✓ Cleanup complete"

dev: setup-db run ## Setup database and run app (for development)