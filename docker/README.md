# Docker Setup for Data Quality Toolkit

## Quick Start

### Build Images

```bash
# Build all images
docker compose build

# Build specific service
docker compose build dqt
docker compose build dqt-cli
```

### Run Commands

```bash
# Process a CSV file
docker compose run --rm dqt export /data/examples/sample.csv

# Use CLI image (lighter weight)
docker compose run --rm dqt-cli export /data/input/myfile.csv

# Interactive CLI
docker compose run --rm dqt-cli --help
```

### Development Mode

```bash
# Start development container
docker compose --profile dev up -d dqt-dev

# Execute commands in dev container
docker compose exec dqt-dev bash
docker compose exec dqt-dev dqt export /data/examples/sample.csv

# Run tests in container
docker compose exec dqt-dev pytest tests/
```

## Services

### `dqt` (Main Service)
- **Image**: `dqt:latest`
- **Purpose**: Production-ready image with optimized layers
- **Size**: ~250MB
- **Use Case**: Production deployments, CI/CD pipelines

### `dqt-cli` (CLI Service)
- **Image**: `dqt-cli:latest`
- **Purpose**: Lightweight Alpine-based CLI
- **Size**: ~150MB
- **Use Case**: Quick CLI operations, minimal footprint

### `dqt-dev` (Development Service)
- **Image**: `dqt-dev:latest`
- **Purpose**: Development with testing tools
- **Profile**: `dev`
- **Use Case**: Local development, debugging

## Volume Mounts

| Host Path | Container Path | Purpose |
|-----------|---------------|---------|
| `./data` | `/data` | Working directory |
| `./dist` | `/data/output` | Output artifacts |
| `./examples` | `/data/examples` | Sample data (read-only) |

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `LOG_LEVEL` | `INFO` | Logging level (DEBUG, INFO, WARNING, ERROR) |
| `LOG_FORMAT` | `json` | Log format (json, text) |
| `MAX_ROWS_IN_MEMORY` | `1000000` | Max rows before sampling |
| `SAMPLE_SIZE` | `10000` | Sample size for profiling |
| `EXPORT_BASE_DIR` | `/data/output` | Output directory |

## Examples

### Process Multiple Files

```bash
# Create a batch processing script
cat > process_batch.sh << 'EOF'
#!/bin/bash
for file in /data/input/*.csv; do
  echo "Processing: $file"
  dqt export "$file" --outdir "/data/output/$(basename $file .csv)"
done
EOF

# Run batch processing
docker compose run --rm -v $(pwd)/process_batch.sh:/process_batch.sh:ro \
  dqt-cli sh /process_batch.sh
```

### Custom Configuration

```bash
# With environment overrides
docker compose run --rm \
  -e LOG_LEVEL=DEBUG \
  -e SAMPLE_SIZE=50000 \
  dqt export /data/input/large_file.csv
```

### Integration with CI/CD

```yaml
# .gitlab-ci.yml example
data-quality:
  image: dqt:latest
  script:
    - dqt export data/input.csv --outdir artifacts/
  artifacts:
    paths:
      - artifacts/
```

## Production Deployment

### Using Docker Swarm

```bash
# Deploy as service
docker service create \
  --name dqt-processor \
  --mount type=bind,source=/data,destination=/data \
  --env LOG_LEVEL=INFO \
  dqt:latest \
  export /data/input.csv
```

### Using Kubernetes

```yaml
# dqt-job.yaml
apiVersion: batch/v1
kind: Job
metadata:
  name: dqt-process
spec:
  template:
    spec:
      containers:
      - name: dqt
        image: dqt:latest
        command: ["dqt", "export", "/data/input.csv"]
        volumeMounts:
        - name: data
          mountPath: /data
      volumes:
      - name: data
        persistentVolumeClaim:
          claimName: dqt-data-pvc
      restartPolicy: Never
```

## Troubleshooting

### Check Logs
```bash
docker compose logs dqt
docker compose logs -f dqt-cli
```

### Debug Container
```bash
# Start interactive shell
docker compose run --rm --entrypoint sh dqt-cli

# Check installed packages
docker compose run --rm dqt-cli pip list
```

### Memory Issues
If processing large files, increase Docker memory limits:
```bash
# docker-compose.override.yml
services:
  dqt:
    deploy:
      resources:
        limits:
          memory: 4G
```

## Security Notes

- Images run as non-root user `dqt` (UID 1000)
- No sensitive data in image layers
- Use secrets for API keys (future phases)
- Regular security scanning recommended:
  ```bash
  docker scout cves dqt:latest
  trivy image dqt:latest
  ```

## Performance Tips

1. **Use CLI image for simple operations** (50% smaller)
2. **Mount data volumes** instead of copying files
3. **Set appropriate `SAMPLE_SIZE`** for large datasets
4. **Use `--no-cache` flag** when rebuilding after dependency changes

## Next Steps (Phase 2+)

- [ ] Add API service (Phase 6)
- [ ] Add UI service (Phase 6)
- [ ] Add database service for metadata
- [ ] Add monitoring (Prometheus/Grafana)
- [ ] Add message queue for async processing
```

## 5. docker/.dockerignore

```dockerfile
# docker/.dockerignore
**/__pycache__
**/*.pyc
**/*.pyo
**/*.pyd
*.egg-info
.git
.github
.gitignore
.pytest_cache
.mypy_cache
.ruff_cache
.coverage
.env
.venv
venv/
env/
*.log
tests/
docs/
examples/*.csv
dist/
htmlcov/
.DS_Store
Thumbs.db
*.swp
*.swo
*~
README.md
CHANGELOG.md
Makefile
docker-compose*.yml
Dockerfile*
.dockerignore
```

## 6. Helper Scripts

### docker/build.sh
```bash
#!/bin/bash
# docker/build.sh - Build all Docker images

set -e

echo "🔨 Building Docker images for Data Quality Toolkit..."

# Build main image
echo "Building main image..."
docker build -f docker/Dockerfile -t dqt:latest -t dqt:0.1.0 ..

# Build CLI image
echo "Building CLI image..."
docker build -f docker/Dockerfile.cli -t dqt-cli:latest -t dqt-cli:0.1.0 ..

# Build dev image
echo "Building dev image..."
docker build -f docker/Dockerfile --target builder -t dqt-dev:latest ..

echo "✅ Docker images built successfully!"
docker images | grep dqt
```

### docker/run.sh
```bash
#!/bin/bash
# docker/run.sh - Quick run wrapper

set -e

# Default to CLI image for quick operations
IMAGE=${DQT_IMAGE:-dqt-cli:latest}
DATA_DIR=${DATA_DIR:-$(pwd)/data}
OUTPUT_DIR=${OUTPUT_DIR:-$(pwd)/dist}

# Ensure directories exist
mkdir -p "$DATA_DIR" "$OUTPUT_DIR"

# Run DQT with proper mounts
docker run --rm -it \
  -v "$DATA_DIR:/data" \
  -v "$OUTPUT_DIR:/data/output" \
  -e LOG_LEVEL=${LOG_LEVEL:-INFO} \
  -e LOG_FORMAT=${LOG_FORMAT:-text} \
  "$IMAGE" "$@"

# Common one-liners
# Build (from repo root)
docker compose build

# Rebuild from scratch
docker compose build --no-cache

# Run export on a local file (mounted by compose)
docker compose run --rm dqt export /data/examples/sample.csv

# Shell into a dev container (profile)
docker compose --profile dev up -d dqt-dev
docker compose exec dqt-dev bash

# Tear down + remove volumes if mounts get weird
docker compose down -v
docker system prune -f
