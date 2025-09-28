# Multi-stage build for better caching
# Stage 1: Dependencies (cached separately)
FROM ubuntu:22.04 AS deps

ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1

# Install system dependencies including debugging tools
# This layer rarely changes, so it will be cached
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

# Install UV - this layer rarely changes
RUN pip3 install uv

# Set working directory
WORKDIR /app

# Copy UV configuration files first (these change less frequently)
# This layer will be cached unless pyproject.toml or uv.lock changes
COPY pyproject.toml uv.lock ./

# Install dependencies using UV with better caching
# Use --frozen to ensure exact versions from lock file
RUN uv sync --frozen

# Stage 2: Final image
FROM ubuntu:22.04

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

# Copy dependencies from deps stage
COPY --from=deps /app/.venv /app/.venv
COPY --from=deps /app/pyproject.toml /app/uv.lock ./

# Create a non-root user for security
RUN useradd -m -u 1000 appuser && chown -R appuser:appuser /app

# Copy the entire locust directory AFTER user creation to ensure fresh copy
# This ensures source code changes always trigger a rebuild of this layer
COPY --chown=appuser:appuser locust/ ./locust/ 

USER appuser

EXPOSE 8089

# Change to locust directory and set the default command to run locust
WORKDIR /app/locust
ENV PYTHONPATH=/app/locust
CMD ["uv", "run", "locust", "-f", "./scripts/end_to_end_sequential.py", "--host=http://globeco-portfolio-management-portal:3000"] 