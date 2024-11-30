# Use an official Python runtime as a parent image
FROM python:3.9-slim

# Install required system packages
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    arp-scan \
    iputils-ping \
    netcat-openbsd \
    && rm -rf /var/lib/apt/lists/* \
    && apt-get clean

# Set the working directory in the container
WORKDIR /app

# Copy the current directory contents into the container at /app
COPY . /app

# Install any needed packages specified in requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Make port 4000 available to the world outside this container
EXPOSE 4000

# Volume for persistent data
VOLUME /app/data

# Run the application with Gunicorn
CMD ["gunicorn", "-k", "eventlet", "-w", "1", "-b", "0.0.0.0:4000", "movie_selector:app"]
