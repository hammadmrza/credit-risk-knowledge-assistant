# Lean container for the Credit Risk Knowledge Assistant chatbot.
#   docker build -t knowledge-assistant .
#   docker run -p 8501:8501 -e ANTHROPIC_API_KEY=sk-ant-... knowledge-assistant
FROM python:3.11-slim

WORKDIR /app

# Install dependencies first for better layer caching.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8501
# The app auto-loads the seed documents in knowledge/ on first run.
ENTRYPOINT ["streamlit", "run", "src/app/chatbot.py", \
            "--server.port=8501", "--server.address=0.0.0.0"]
