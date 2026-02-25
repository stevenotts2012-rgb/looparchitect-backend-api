"""
Simple verification that all implementations are in place.
This script checks that key files exist and contain expected code.
"""

import os
import sys
from pathlib import Path


def check_file_exists(filepath, description):
    """Check if a file exists."""
    if os.path.exists(filepath):
        print(f"✅ {description}")
        return True
    else:
        print(f"❌ {description}")
        return False


def check_file_contains(filepath, text, description):
    """Check if a file contains specific text."""
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()
            if text in content:
                print(f"✅ {description}")
                return True
            else:
                print(f"❌ {description} - text not found")
                return False
    except Exception as e:
        print(f"❌ {description} - error: {e}")
        return False


def main():
    """Run all verifications."""
    base_path = Path(__file__).parent
    checks_passed = 0
    checks_total = 0

    print("\n" + "="*60)
    print("IMPLEMENTATION VERIFICATION")
    print("="*60 + "\n")

    # ── Check Loop Model ──
    print("Loop Model:")
    checks_total += 1
    if check_file_contains(
        base_path / "app/models/loop.py",
        "bars = Column(Integer, nullable=True)",
        "  Loop model has bars column"
    ):
        checks_passed += 1

    # ── Check Loop Schemas ──
    print("\nLoop Schemas:")
    checks_total += 1
    if check_file_contains(
        base_path / "app/schemas/loop.py",
        "bars: Optional[int] = None",
        "  LoopCreate schema has bars field"
    ):
        checks_passed += 1

    checks_total += 1
    if check_file_contains(
        base_path / "app/schemas/loop.py",
        "bars: Optional[int]",
        "  LoopResponse schema has bars field"
    ):
        checks_passed += 1

    # ── Check CRUD Endpoints ──
    print("\nCRUD Endpoints (app/routes/loops.py):")
    checks_total += 1
    if check_file_contains(
        base_path / "app/routes/loops.py",
        '@router.post("/loops", response_model=LoopResponse, status_code=201)',
        "  POST /loops endpoint exists"
    ):
        checks_passed += 1

    checks_total += 1
    if check_file_contains(
        base_path / "app/routes/loops.py",
        '@router.get("/loops", response_model=List[LoopResponse])',
        "  GET /loops endpoint exists"
    ):
        checks_passed += 1

    checks_total += 1
    if check_file_contains(
        base_path / "app/routes/loops.py",
        '@router.get("/loops/{loop_id}", response_model=LoopResponse)',
        "  GET /loops/{id} endpoint exists"
    ):
        checks_passed += 1

    checks_total += 1
    if check_file_contains(
        base_path / "app/routes/loops.py",
        '@router.put("/loops/{loop_id}", response_model=LoopResponse, status_code=200)',
        "  PUT /loops/{id} endpoint exists"
    ):
        checks_passed += 1

    checks_total += 1
    if check_file_contains(
        base_path / "app/routes/loops.py",
        '@router.patch("/loops/{loop_id}", response_model=LoopResponse, status_code=200)',
        "  PATCH /loops/{id} endpoint exists"
    ):
        checks_passed += 1

    checks_total += 1
    if check_file_contains(
        base_path / "app/routes/loops.py",
        '@router.delete("/loops/{loop_id}", status_code=200)',
        "  DELETE /loops/{id} endpoint exists"
    ):
        checks_passed += 1

    checks_total += 1
    if check_file_contains(
        base_path / "app/routes/loops.py",
        '@router.post("/loops/with-file", response_model=LoopResponse, status_code=201)',
        "  POST /loops/with-file endpoint exists"
    ):
        checks_passed += 1

    # ── Check Render Endpoint ──
    print("\nRender Pipeline:")
    checks_total += 1
    if check_file_contains(
        base_path / "app/routes/render.py",
        '@router.post("/render/{loop_id}", response_model=RenderResponse)',
        "  POST /render/{loop_id} endpoint exists"
    ):
        checks_passed += 1

    # ── Check Test Files ──
    print("\nTest Files:")
    checks_total += 1
    if check_file_exists(
        base_path / "tests/routes/test_loops_crud.py",
        "  test_loops_crud.py exists"
    ):
        checks_passed += 1

    checks_total += 1
    if check_file_contains(
        base_path / "tests/routes/test_loops_crud.py",
        "class TestLoopCreate",
        "  CRUD tests include TestLoopCreate"
    ):
        checks_passed += 1

    checks_total += 1
    if check_file_contains(
        base_path / "tests/routes/test_loops_crud.py",
        "class TestLoopList",
        "  CRUD tests include TestLoopList"
    ):
        checks_passed += 1

    checks_total += 1
    if check_file_contains(
        base_path / "tests/routes/test_loops_crud.py",
        "def test_create_loop_with_optional_bars",
        "  CRUD tests include bars field test"
    ):
        checks_passed += 1

    checks_total += 1
    if check_file_exists(
        base_path / "tests/routes/test_loops_s3_integration.py",
        "  test_loops_s3_integration.py exists"
    ):
        checks_passed += 1

    checks_total += 1
    if check_file_contains(
        base_path / "tests/routes/test_loops_s3_integration.py",
        "class TestS3FileUpload",
        "  S3 integration tests exist"
    ):
        checks_passed += 1

    # ── Check Migrations ──
    print("\nDatabase Migrations:")
    checks_total += 1
    if check_file_exists(
        base_path / "migrations/versions/006_add_bars_column.py",
        "  Migration 006_add_bars_column.py exists"
    ):
        checks_passed += 1

    checks_total += 1
    if check_file_contains(
        base_path / "migrations/versions/006_add_bars_column.py",
        "op.add_column('loops', sa.Column('bars', sa.Integer(), nullable=True))",
        "  Migration adds bars column"
    ):
        checks_passed += 1

    # ── Check Documentation ──
    print("\nDocumentation:")
    checks_total += 1
    if check_file_exists(
        base_path / "README_SETUP.md",
        "  README_SETUP.md exists"
    ):
        checks_passed += 1

    checks_total += 1
    if check_file_contains(
        base_path / "README_SETUP.md",
        "AWS_S3_BUCKET=your-bucket-name",
        "  README includes S3 env vars"
    ):
        checks_passed += 1

    checks_total += 1
    if check_file_exists(
        base_path / "IMPLEMENTATION_COMPLETE.md",
        "  IMPLEMENTATION_COMPLETE.md exists"
    ):
        checks_passed += 1

    checks_total += 1
    if check_file_contains(
        base_path / "API_REFERENCE.md",
        "## Loop CRUD API",
        "  API_REFERENCE.md includes Loop CRUD section"
    ):
        checks_passed += 1

    checks_total += 1
    if check_file_contains(
        base_path / "API_REFERENCE.md",
        "POST /api/v1/loops",
        "  API_REFERENCE documents loop endpoints"
    ):
        checks_passed += 1

    # ── Summary ──
    print("\n" + "="*60)
    print(f"VERIFICATION COMPLETE: {checks_passed}/{checks_total} checks passed")
    print("="*60)

    if checks_passed == checks_total:
        print("\n✅ All implementations verified successfully!")
        return 0
    else:
        print(f"\n⚠️  {checks_total - checks_passed} checks failed")
        return 1


if __name__ == "__main__":
    sys.exit(main())
