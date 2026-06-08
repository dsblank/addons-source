import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
# Shared modules live in FastFiltersLib (simulates load_on_reg pre-loading)
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "FastFiltersLib"))
# Shared test base classes
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "FastFiltersLib", "test"))
