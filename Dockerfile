# Dockerfile for Streamlit deployment of Swift Alliance app
FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libxml2-dev libxslt1-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY . /app

RUN pip install --upgrade pip
RUN pip install -r requirements.txt

EXPOSE 8501
RUN mkdir -p /app/assets /app/schemas

ENV STREAMLIT_SERVER_HEADLESS=true
ENV STREAMLIT_SERVER_ENABLE_CORS=false
ENV STREAMLIT_SERVER_PORT=8501

CMD ["streamlit", "run", "swift_alliance_streamlit.py", "--server.port=8501", "--server.address=0.0.0.0"]