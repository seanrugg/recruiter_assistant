import os
import tempfile

# Every test runs against a throwaway data folder, never a real family's.
os.environ["RECRUITING_DESK_HOME"] = tempfile.mkdtemp(prefix="recruiting-desk-test-")
