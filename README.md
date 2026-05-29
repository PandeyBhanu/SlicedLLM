# SlicedLLM

A production-grade PromptOps platform for AI prompt versioning, evaluation, and management. Built with FastAPI (backend) and Next.js 15 (frontend).

## Features

### Backend (FastAPI)
- **Prompt Registry**: Create, manage, and version prompts with semantic versioning
- **Version Management**: Immutable prompt versions with activation/deactivation
- **Diff Engine**: Side-by-side comparison of prompt versions with detailed analysis
- **Evaluation System**: Run evaluations against datasets with multiple LLM providers
- **Changelog & Audit**: Complete audit trail of all operations
- **Provider Abstraction**: Support for Ollama, Groq, and OpenAI providers
- **RESTful API**: Full API with OpenAPI documentation

### Frontend (Next.js 15)
- **Dashboard**: Overview of prompts, evaluations, and statistics
- **Prompt Registry**: UI for managing prompts and versions
- **Diff View**: Visual comparison of prompt versions
- **Evaluation Runner**: Configure and run evaluations
- **Results Page**: View evaluation results with charts and metrics
- **Changelog**: Timeline view of all changes

## Tech Stack

### Backend
- **FastAPI**: Modern, fast web framework
- **SQLAlchemy**: ORM with async support
- **PostgreSQL**: Production database
- **Alembic**: Database migrations
- **Pydantic**: Data validation
- **Structlog**: Structured logging

### Frontend
- **Next.js 15**: React framework with App Router
- **TypeScript**: Type-safe development
- **Tailwind CSS**: Utility-first styling
- **shadcn/ui**: Reusable UI components
- **TanStack Query**: Data fetching and caching
- **Recharts**: Data visualization
- **Lucide React**: Icons

## Prerequisites

- Docker and Docker Compose
- Node.js 18+ and npm
- Python 3.10+ (for local development without Docker)

## Quick Start

### 1. Clone the Repository

```bash
git clone https://github.com/PandeyBhanu/SlicedLLM.git
cd SlicedLLM
```

### 2. Setup Environment Variables

```bash
cp .env.example .env
```

Edit `.env` and add your API keys if using cloud providers:

```bash
# Optional: Add Groq API key for Groq provider
GROQ_API_KEY=your_groq_api_key_here

# Optional: Add OpenAI API key for OpenAI provider
OPENAI_API_KEY=your_openai_api_key_here
```

### 3. Start Backend with Docker Compose

```bash
docker-compose up -d
```

This will:
- Start PostgreSQL database on port 5432
- Start FastAPI backend on port 8000
- Run database migrations automatically

### 4. Setup Frontend

```bash
cd frontend
npm install
```

### 5. Configure Frontend Environment

Create `frontend/.env.local`:

```bash
NEXT_PUBLIC_API_URL=http://localhost:8000/api/v1
```

### 6. Start Frontend Development Server

```bash
npm run dev
```

The frontend will be available at http://localhost:3000

## Access Points

- **Frontend**: http://localhost:3000
- **Backend API**: http://localhost:8000
- **API Documentation**: http://localhost:8000/docs
- **Database**: localhost:5432

## Local Development (Without Docker)

### Start PostgreSQL

```bash
docker run -d -p 5432:5432 \
  -e POSTGRES_USER=postgres \
  -e POSTGRES_PASSWORD=postgres \
  -e POSTGRES_DB=slicedllm \
  postgres:16-alpine
```

### Setup Python Environment

```bash
cd SlicedLLM
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### Run Database Migrations

```bash
alembic upgrade head
```

### Start Backend Server

```bash
uvicorn app.main:app --reload --port 8000
```

Then follow steps 4-6 from the Quick Start for the frontend.

## Project Structure

```
SlicedLLM/
├── app/                      # Backend application
│   ├── api/                  # API endpoints
│   ├── core/                 # Core configuration
│   ├── db/                   # Database setup
│   ├── evaluation/           # Evaluation engine
│   ├── models/               # Database models
│   ├── promptops/            # Prompt operations
│   ├── providers/            # LLM providers
│   ├── repositories/         # Data access layer
│   ├── schemas/              # Pydantic schemas
│   └── services/             # Business logic
├── frontend/                 # Next.js frontend
│   ├── src/
│   │   ├── app/              # App router pages
│   │   ├── components/       # React components
│   │   ├── hooks/            # Custom hooks
│   │   ├── lib/              # Utilities
│   │   └── types/            # TypeScript types
│   ├── package.json
│   └── tsconfig.json
├── tests/                    # Test suite
├── alembic/                  # Database migrations
├── docker-compose.yml
├── Dockerfile
├── requirements.txt
└── .env.example
```

## LLM Providers

### Ollama (Local)
- Default local provider
- No API key required
- Requires Ollama running locally: http://localhost:11434
- Supported models: llama3, llama2, mistral

### Groq (Cloud)
- Fast cloud provider
- Requires `GROQ_API_KEY` in `.env`
- Get API key: https://console.groq.com/keys
- Supported models: llama3-8b-8192, mixtral-8x7b-32768, gemma-7b-it

### OpenAI (Cloud)
- Premium cloud provider
- Requires `OPENAI_API_KEY` in `.env`
- Supported models: gpt-4, gpt-3.5-turbo, gpt-4-turbo

## Running Tests

```bash
# Backend tests
cd SlicedLLM
pytest

# With coverage
pytest --cov=app --cov-report=html
```

## Stopping the Project

### With Docker Compose
```bash
docker-compose down
```

### Local Backend
Press `Ctrl+C` in the terminal running uvicorn

### Frontend
Press `Ctrl+C` in the terminal running `npm run dev`

## API Documentation

Once the backend is running, visit http://localhost:8000/docs for interactive API documentation (Swagger UI).

## Environment Variables

See `.env.example` for all available configuration options:

- **Database**: PostgreSQL connection settings
- **API**: API configuration and security
- **Providers**: Ollama, Groq, OpenAI settings
- **Evaluation**: Evaluation engine configuration

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Run tests
5. Submit a pull request

## License

MIT License - see LICENSE file for details
