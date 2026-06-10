"""Streamlit-free service wrappers for the dashboard UI.

Each function wraps a toolkit API call and returns an ``(result, err)`` tuple
so page modules can stay free of bare try/except blocks. No module here may
import streamlit.
"""

from . import assessment as assessment
from . import diagnostics as diagnostics
from . import export as export
from . import kpi as kpi
from . import pipeline as pipeline
