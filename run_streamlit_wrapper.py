"""
Wrapper to ensure project root on sys.path and import the streamlit app.
"""
import os
import sys
import traceback

BASE_DIR = os.path.dirname(__file__) or os.getcwd()
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

print("Base dir added to sys.path:", BASE_DIR)
print("sys.path[0:5]:", sys.path[:5])
print("Files in base dir:", os.listdir(BASE_DIR))

try:
    import swift_alliance_streamlit  # noqa: F401
except Exception:
    print("Failed to import swift_alliance_streamlit. Full traceback follows:")
    traceback.print_exc()
    raise