# Clean
Remove-Item -Recurse -Force dist, build, *.egg-info

# Install tools
pip install build twine

# Build distribution
python -m build

# Validate
twine check dist/*

# Upload to TestPyPI (safe sandbox)
twine upload --repository testpypi dist/*
