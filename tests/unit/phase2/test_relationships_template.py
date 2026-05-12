"""Phase 2: Relationships template tests."""

import json

from data_quality_toolkit.exporters.bi.powerbi_zero_config.generator import render_template


def test_relationships_rendering(tmp_path):
    """Test relationships.json template rendering."""
    # Create test template
    template_file = tmp_path / "relationships.json.j2"
    template_file.write_text("""
{
  "tables": {
    "dim_dataset": { "primary_key": ["dataset_id"] }
  },
  "relationships": []
}
""")

    # Render
    content = render_template(template_file, {})
    data = json.loads(content)

    assert "tables" in data
    assert "dim_dataset" in data["tables"]
    assert data["tables"]["dim_dataset"]["primary_key"] == ["dataset_id"]
    assert "dim_dataset" in data["tables"]
    assert data["tables"]["dim_dataset"]["primary_key"] == ["dataset_id"]
