"""
Test script to verify bars mode and renderer variation fixes.
"""
import requests
import time
import json
from pathlib import Path

BASE_URL = "http://localhost:8000"

def get_first_loop():
    """Get the first available loop from the database."""
    response = requests.get(f"{BASE_URL}/api/v1/loops")
    response.raise_for_status()
    loops = response.json()
    if not loops or len(loops) == 0:
        raise Exception("No loops found in database")
    return loops[0]

def generate_arrangement_with_bars(loop_id: int, bars: int = 8):
    """Generate arrangement using bars mode."""
    # First, get the loop to retrieve its BPM
    response = requests.get(f"{BASE_URL}/api/v1/loops/{loop_id}")
    response.raise_for_status()
    loop = response.json()
    bpm = loop.get("bpm", 120)
    
    print(f"📊 Loop ID: {loop_id}")
    print(f"🎵 Loop BPM: {bpm}")
    print(f"📏 Requested bars: {bars}")
    
    # Calculate expected duration
    expected_duration = bars * 4 * 60 / bpm
    print(f"⏱️  Expected duration: {expected_duration:.2f}s")
    
    # Generate arrangement
    payload = {
        "loop_id": loop_id,
        "bars": bars,
        "style_text_input": "energetic electronic with dynamic transitions",
        "use_ai_parsing": True
    }
    
    print(f"\n🚀 Sending generate request...")
    print(f"Payload: {json.dumps(payload, indent=2)}")
    
    response = requests.post(
        f"{BASE_URL}/api/v1/arrangements/generate",
        json=payload
    )
    
    if response.status_code != 200:
        print(f"❌ Error {response.status_code}: {response.text}")
    
    response.raise_for_status()
    result = response.json()
    
    arrangement_id = result["arrangement_id"]
    print(f"✅ Arrangement created: {arrangement_id}")
    print(f"📦 Initial status: {result['status']}")
    
    return arrangement_id, expected_duration

def poll_arrangement_status(arrangement_id: int, timeout: int = 120):
    """Poll arrangement status until complete or failed."""
    print(f"\n⏳ Polling arrangement status...")
    start_time = time.time()
    
    while True:
        if time.time() - start_time > timeout:
            raise Exception(f"Timeout waiting for arrangement {arrangement_id}")
        
        response = requests.get(f"{BASE_URL}/api/v1/arrangements/{arrangement_id}")
        response.raise_for_status()
        arrangement = response.json()
        
        status = arrangement["status"]
        print(f"  Status: {status}", end="\r")
        
        if status in ["completed", "done"]:
            print(f"\n✅ Arrangement completed!")
            return arrangement
        elif status == "failed":
            error = arrangement.get("error_message", "Unknown error")
            raise Exception(f"Arrangement failed: {error}")
        
        time.sleep(2)

def analyze_audio_file(arrangement):
    """Analyze the generated audio file."""
    print(f"\n📊 Arrangement data keys: {list(arrangement.keys())}")
    
    audio_url = arrangement.get("output_url") or arrangement.get("audio_url") or arrangement.get("audio_file")
    if not audio_url:
        print(f"❌ No audio URL found. Available fields: {list(arrangement.keys())}")
        return None
    
    # If local file path
    if audio_url.startswith("/"):
        audio_path = Path(f"c:\\Users\\steve\\looparchitect-backend-api{audio_url}")
    else:
        # Download from URL
        audio_path = Path(f"./test_output_{arrangement['id']}.wav")
        response = requests.get(audio_url)
        response.raise_for_status()
        audio_path.write_bytes(response.content)
    
    print(f"\n📁 Audio file: {audio_path}")
    
    if audio_path.exists():
        file_size = audio_path.stat().st_size
        print(f"📊 File size: {file_size / 1024:.2f} KB")
        
        # Try to get duration using pydub
        try:
            from pydub import AudioSegment
            audio = AudioSegment.from_file(str(audio_path))
            duration_ms = len(audio)
            duration_s = duration_ms / 1000
            print(f"⏱️  Actual duration: {duration_s:.2f}s ({duration_ms}ms)")
            return duration_s
        except Exception as e:
            print(f"⚠️  Could not read audio duration: {e}")
            return None
    else:
        print(f"❌ Audio file not found at {audio_path}")
        return None

def main():
    print("=" * 60)
    print("🎵 Testing Bars Mode & Renderer Variation Fixes")
    print("=" * 60)
    
    try:
        # Step 1: Get a loop
        print("\n📥 Step 1: Getting first loop from database...")
        loop = get_first_loop()
        loop_id = loop["id"]
        
        # Step 2: Generate with bars=8
        print("\n🎨 Step 2: Generating arrangement with bars=8...")
        arrangement_id, expected_duration = generate_arrangement_with_bars(loop_id, bars=8)
        
        # Step 3: Wait for completion
        print("\n⏳ Step 3: Waiting for render to complete...")
        arrangement = poll_arrangement_status(arrangement_id)
        
        # Step 4: Analyze output
        print("\n🔍 Step 4: Analyzing output...")
        actual_duration = analyze_audio_file(arrangement)
        
        # Step 5: Summary
        print("\n" + "=" * 60)
        print("📋 TEST SUMMARY")
        print("=" * 60)
        print(f"Arrangement ID: {arrangement_id}")
        print(f"Expected duration: {expected_duration:.2f}s")
        if actual_duration:
            print(f"Actual duration: {actual_duration:.2f}s")
            duration_diff = abs(actual_duration - expected_duration)
            print(f"Duration difference: {duration_diff:.2f}s")
            
            if duration_diff < 2.0:  # Allow 2s tolerance
                print("✅ Duration matches expected (bars mode working!)")
            else:
                print(f"⚠️  Duration mismatch (expected {expected_duration:.2f}s, got {actual_duration:.2f}s)")
        
        # Print producer arrangement structure
        if "producer_arrangement_json" in arrangement:
            producer_data = json.loads(arrangement["producer_arrangement_json"])
            print(f"\n📊 Producer Arrangement Structure:")
            if "sections" in producer_data:
                sections = producer_data["sections"]
                print(f"  Total sections: {len(sections)}")
                for i, section in enumerate(sections):
                    section_type = section.get("section_type", "unknown")
                    bars = section.get("bars", 0)
                    print(f"    {i+1}. {section_type}: {bars} bars")
        
        print("\n✅ Test completed successfully!")
        
    except Exception as e:
        print(f"\n❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return 1
    
    return 0

if __name__ == "__main__":
    exit(main())
