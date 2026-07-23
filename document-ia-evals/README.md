# Streamlit Application

A Streamlit application to run Evals for Document IA.

## 📋 Prerequisites

- Python 3.12 or higher
- UV (for dependency management)

## 🛠️ Installation

### Step 1: Clone or Setup

### Step 2: Activate Conda Environment (if using conda)

```bash
conda activate document-ia-evals
```

### Step 3: Install Dependencies

```bash
# Install all dependencies using UV
uv sync
```

## 🎯 Usage

### Running the Application

```bash
# Run with UV
uv run streamlit run src/document_ia_evals/app.py

# Or activate the UV virtual environment first
source .venv/bin/activate
streamlit run src/document_ia_evals/app.py
```

The application will open in your default browser at `http://localhost:8501`
