# Use the official lightweight Python image
FROM python:3.14-slim

# Allow statements and log messages to immediately appear in the Cloud Run logs
ENV PYTHONUNBUFFERED=True

# Set the working directory
WORKDIR /app

# Copy local code to the container image
COPY . ./
RUN cp -r data.example data

# Install dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Run the web service on container startup using gunicorn.
# Bind to $PORT and set workers (adjust based on your CPU allocation)
CMD exec gunicorn --bind :$PORT --workers 1 --threads 4 --timeout 0 app:app