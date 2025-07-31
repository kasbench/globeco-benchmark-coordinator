# Use Ubuntu as base image for debugging capabilities (curl, ping, telnet)
FROM ubuntu:22.04

# Set environment variables
ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1

# Install system dependencies including debugging tools
RUN apt-get update && apt-get install -y \
    software-properties-common \
    && add-apt-repository ppa:deadsnakes/ppa \
    && apt-get update \
    && apt-get install -y \
    python3.13 \
    python3.13-venv \
    python3-pip \
    curl \
    iputils-ping \
    telnet \
    wget \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Install UV
RUN pip3 install uv

# Set working directory
WORKDIR /app

# Copy UV configuration files
COPY pyproject.toml uv.lock ./

# Copy the entire locust directory
COPY locust/ ./locust/ 

# Install dependencies using UV
RUN uv sync --frozen

# Create a non-root user for security
RUN useradd -m -u 1000 appuser && chown -R appuser:appuser /app
USER appuser

EXPOSE 8089

# Change to locust directory and set the default command to run locust
WORKDIR /app/locust
ENV PYTHONPATH=/app/locust
CMD ["uv", "run", "locust", "-f", "scripts"] 