# Local Development Guide (Poetry)

This guide provides step-by-step instructions for setting up a local development environment using Poetry. Following these steps will allow you to run unit tests and validate your changes before committing them.

## 1. Prerequisites

Before you begin, ensure you have the following tools installed and configured on your local machine:

- **Poetry**: The dependency management and packaging tool for Python.
- **gcloud CLI**: The Google Cloud command-line tool.
- **Terraform**: The infrastructure as code tool.
- **Python**: Version 3.10 or later.
- **Docker**: For building container images (optional for local testing).

You should also have access to a Google Cloud project for development and testing, and your `gcloud` CLI should be authenticated (`gcloud auth login`).

## 2. Configuration

1.  **Create `saas.env` file**:
    If you don't have a `saas.env` file in the root of the repository, create one by copying the example file:
    ```bash
    cp saas.env.example saas.env
    ```

2.  **Edit `saas.env`**:
    Open `saas.env` and fill in the values required for your local setup, primarily:
    - `TOOL_PROJECT_ID`: Your Google Cloud project ID for development.
    - `REGION`: The GCP region for your resources.
    - `BQ_DATASET_ID`: A BigQuery dataset ID for testing (e.g., `iam_access_mgmt_dev`).

## 3. Environment Setup & Testing

Poetry simplifies environment setup and command execution.

1.  **Navigate to the `cloud-run` directory**:
    The Python project is defined in this directory.
    ```bash
    cd cloud-run
    ```

2.  **Install dependencies**:
    This command will create a new virtual environment in the directory and install all application and development dependencies specified in `pyproject.toml`.
    ```bash
    poetry install
    ```

3.  **Run Unit Tests**:
    To run the test suite, use `poetry run`, which executes commands within the project's virtual environment.
    ```bash
    poetry run pytest
    ```
    This command will discover and run all tests in the `app/tests/` directory.

## 4. Running the Application Locally (for basic checks)

You can run the Flask application locally for very basic checks.

**Important Note**: Most endpoints require real Google Cloud authentication and permissions. Running locally is **not a substitute for deploying to a dev environment** for end-to-end testing.

1.  **Navigate to the `cloud-run` directory** (if you aren't already there).

2.  **Set Environment Variables**:
    The application relies on environment variables from `saas.env`. First, ensure the `.env` file is up-to-date by running the sync script from the **repository root**.
    ```bash
    # From the repository root
    bash scripts/sync-config.sh
    ```
    Poetry can automatically load variables from a `.env` file if it exists in the same directory as `pyproject.toml`. The `sync-config.sh` script already creates `cloud-run/.env`, so no manual `export` is needed.

3.  **Run the Flask App**:
    Use `poetry run` to execute Flask within the managed environment.
    ```bash
    # From the ./cloud-run directory
    poetry run flask --app app/main run
    ```

4.  **Test the health check**:
    In a new terminal, you can now access the health check endpoint:
    ```bash
    curl http://127.0.0.1:5000/healthz
    ```
    You should see a `{"ok":true}` response.
