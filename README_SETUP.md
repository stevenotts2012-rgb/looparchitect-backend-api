# Loop Architect Backend API

A FastAPI-based music production backend for managing audio loops, generating arrangements, and providing audio processing capabilities. Features AWS S3 storage integration and async background processing.

## Quick Start

### Prerequisites
- Python 3.10+
- PostgreSQL (or SQLite for local development)
- FFmpeg (for audio processing)

### Installation

1. **Clone the repository:**
```bash
git clone <repo-url>
cd looparchitect-backend-api
```

2. **Create a virtual environment:**
```bash
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
```

3. **Install dependencies:**
```bash
pip install -r requirements.txt
```

4. **Set up environment variables:**
```bash
cp .env.example .env
# Edit .env with your configuration
```

5. **Initialize the database:**
```bash
# Create migrations
alembic upgrade head

# Or on first setup, run migrate.py
python migrate.py
```

6. **Run the server:**
```bash
python main.py
# Server runs on http://localhost:8000
```

7. **Access API documentation:**
- Swagger UI: http://localhost:8000/docs
- ReDoc: http://localhost:8000/redoc

---

## Environment Variables

### Required
```bash
# Database
DATABASE_URL=sqlite:///./test.db  # Or PostgreSQL connection string

# FastAPI
APP_ENV=development  # or 'production', 'staging'
```

### AWS S3 Configuration (Required for Render/Production)
```bash
AWS_S3_BUCKET=your-bucket-name
AWS_ACCESS_KEY_ID=your-access-key
AWS_SECRET_ACCESS_KEY=your-secret-key
AWS_REGION=us-east-1
```

**Note:** If AWS env vars are not set, the system falls back to local file storage (`./uploads/` directory).

### Optional
```bash
LOG_LEVEL=INFO
CORS_ORIGINS=http://localhost:3000,http://localhost:8080
```

---

## Core Features

### 1. Loop Library CRUD
Manage audio loops with metadata:

**Create Loop:**
```bash
curl -X POST http://localhost:8000/api/v1/loops \
  -H "Content-Type: application/json" \
  -d '{"name": "Trap Beat", "bpm": 140, "bars": 16, "genre": "Trap"}'
```

**Upload Loop with File:**
```bash
curl -X POST http://localhost:8000/api/v1/loops/with-file \
  -F "file=@my-loop.wav" \
  -F 'loop_in={"name":"My Loop","bpm":140,"bars":16}'
```

**List Loops:**
```bash
curl http://localhost:8000/api/v1/loops?genre=Trap&limit=10
```

**Update Loop:**
```bash
curl -X PATCH http://localhost:8000/api/v1/loops/1 \
  -H "Content-Type: application/json" \
  -d '{"bpm": 160}'
```

### 2. Async Arrangement Generation
Generate full arrangements from loops asynchronously:

**Create Arrangement Job:**
```bash
curl -X POST http://localhost:8000/api/v1/arrangements \
  -H "Content-Type: application/json" \
  -d '{"loop_id": 1, "target_duration_seconds": 180}'
```

**Check Job Status:**
```bash
curl http://localhost:8000/api/v1/arrangements/1
```

**Download Arrangement (when ready):**
```bash
curl http://localhost:8000/api/v1/arrangements/1/download -o arrangement.wav
```

### 3. File Storage (S3 or Local)
Automatic failover to local storage if S3 is unavailable:

- **Production (S3):** Files stored in AWS S3 with presigned URLs (1-hour expiration)
- **Development (Local):** Files stored in `./uploads/` directory

### 4. Audio Processing
- Loop analysis (BPM, key, duration detection)
- Audio arrangement generation (section-based assembly)
- File upload/download management

---

## Architecture

### Database Models

**Loop Model**
- `id` - Primary key
- `name` - Loop name (required)
- `file_key` - S3 storage key
- `bpm` - Tempo in beats per minute
- `bars` - Number of bars
- `genre` - Musical genre
- `duration_seconds` - Loop duration
- `status` - Processing status (pending, processing, complete, failed)
- `created_at` - Timestamp

**Arrangement Model**
- `id` - Primary key
- `loop_id` - Foreign key to Loop
- `status` - Job status (queued, processing, done, failed)
- `target_seconds` - Target arrangement duration
- `output_s3_key` - S3 key of generated arrangement
- `output_url` - Presigned download URL
- `arrangement_json` - Timeline metadata
- `error_message` - Error details if failed

### API Routes

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/v1/loops` | Create loop metadata |
| POST | `/api/v1/loops/with-file` | Create loop with file upload |
| GET | `/api/v1/loops` | List loops (filterable) |
| GET | `/api/v1/loops/{id}` | Get loop details |
| PUT | `/api/v1/loops/{id}` | Update loop |
| PATCH | `/api/v1/loops/{id}` | Partially update loop |
| DELETE | `/api/v1/loops/{id}` | Delete loop |
| POST | `/api/v1/arrangements` | Create arrangement job |
| GET | `/api/v1/arrangements` | List arrangements |
| GET | `/api/v1/arrangements/{id}` | Get arrangement status |
| GET | `/api/v1/arrangements/{id}/download` | Download arrangement |

---

## Testing

### Run Tests
```bash
# All tests
pytest

# With coverage
pytest --cov=app

# Specific test file
pytest tests/routes/test_loops_crud.py -v

# Specific test class
pytest tests/routes/test_loops_crud.py::TestLoopCreate -v
```

### Test Coverage
- Loop CRUD operations (`tests/routes/test_loops_crud.py`)
- S3 integration (`tests/routes/test_loops_s3_integration.py`)
- Arrangement pipeline (`tests/routes/test_arrangements.py`)
- Background jobs (`tests/services/test_arrangement_jobs.py`)
- Arrangement engine (`tests/services/test_arrangement_engine.py`)

### Mock Testing
Tests use `unittest.mock` and `moto` for S3 operations without requiring real AWS credentials.

---

## Development Workflow

### Database Migrations
Create a new migration:
```bash
alembic revision --autogenerate -m "Description of change"
```

Apply migrations:
```bash
alembic upgrade head
```

Rollback:
```bash
alembic downgrade -1
```

### Code Structure
```
app/
  ├── main.py                 # FastAPI app initialization
  ├── config.py               # Configuration management
  ├── db.py                   # Database session
  ├── models/
  │   ├── loop.py            # Loop ORM model
  │   ├── arrangement.py      # Arrangement ORM model
  │   └── schemas.py         # Pydantic schemas
  ├── routes/
  │   ├── loops.py           # Loop CRUD endpoints
  │   └── arrangements.py    # Arrangement endpoints
  ├── services/
  │   ├── storage.py         # S3/local file storage
  │   ├── loop_service.py    # Business logic
  │   ├── arrangement_engine.py  # Audio arrangement logic
  │   └── arrangement_jobs.py    # Background job handler
  └── schemas/
      ├── loop.py            # Loop request/response schemas
      └── arrangement.py     # Arrangement schemas

migrations/
  └── versions/
      └── 00x_*.py          # Alembic migrations

tests/
  ├── routes/
  │   ├── test_loops_crud.py
  │   ├── test_loops_s3_integration.py
  │   └── test_arrangements.py
  └── services/
      ├── test_arrangement_jobs.py
      └── test_arrangement_engine.py
```

---

## Deployment

### Docker
```dockerfile
FROM python:3.10-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

### Environment Setup for Production

1. **Set AWS S3 credentials:**
```bash
export AWS_S3_BUCKET=prod-bucket
export AWS_ACCESS_KEY_ID=<your-key>
export AWS_SECRET_ACCESS_KEY=<your-secret>
export AWS_REGION=us-east-1
```

2. **Use PostgreSQL:**
```bash
export DATABASE_URL=postgresql://user:pass@host:5432/dbname
```

3. **Run migrations:**
```bash
alembic upgrade head
```

4. **Start server:**
```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 4
```

### Health Check
```bash
curl http://localhost:8000/health
```

---

## Troubleshooting

### S3 Connection Issues
- Verify AWS credentials are set correctly
- Check S3 bucket name and region
- Ensure bucket permissions allow upload/download
- System falls back to local storage if S3 unavailable

### Database Issues
- Check `DATABASE_URL` format
- Ensure PostgreSQL is running
- Run migrations: `alembic upgrade head`

### Audio Processing Issues
- Verify FFmpeg is installed: `ffmpeg -version`
- Check file format is WAV or MP3
- Look for error details in loop status

---

## API Documentation

For detailed endpoint documentation, see [API_REFERENCE.md](./API_REFERENCE.md)

Interactive API docs available at:
- Swagger UI: http://localhost:8000/docs
- ReDoc: http://localhost:8000/redoc

---

## Contributing

1. Create feature branch: `git checkout -b feature/your-feature`
2. Make changes and write tests
3. Run tests: `pytest`
4. Commit: `git commit -am "Add feature"`
5. Push: `git push origin feature/your-feature`
6. Create Pull Request

---

## License

[Add your license here]

---

## Support

For issues and questions:
- Check [API_REFERENCE.md](./API_REFERENCE.md) for endpoint details
- Review test files in `tests/` for usage examples
- Check application logs for error details
