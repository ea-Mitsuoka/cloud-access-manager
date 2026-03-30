# Stage 1: Builder
# Install dependencies using Poetry
FROM python:3.12-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV POETRY_VERSION=1.8.2
ENV POETRY_VIRTUALENVS_IN_PROJECT=1

# Install poetry
RUN pip install "poetry==${POETRY_VERSION}"

# Set the working directory
WORKDIR /app

# Copy only the files needed for dependency installation
COPY pyproject.toml poetry.lock ./

# Install dependencies, without dev dependencies
RUN poetry install --no-interaction --no-ansi --no-dev


# Stage 2: Final
# Create the final, lean image
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Point to the virtual environment created by Poetry
ENV VIRTUAL_ENV=/app/.venv

# Add the virtual environment's bin directory to the PATH
ENV PATH="/app/.venv/bin:$PATH"
ENV PORT=8080

WORKDIR /app

# Copy the virtual environment from the builder stage
COPY --from=builder ${VIRTUAL_ENV} ${VIRTUAL_ENV}

# Copy the application code
COPY app /app/app

# Run the application
CMD exec gunicorn --bind :${PORT} --workers 1 --threads 8 app.main:app
