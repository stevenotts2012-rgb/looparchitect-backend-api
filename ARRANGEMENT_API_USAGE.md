"""
API USAGE EXAMPLE: Automatic Beat Arrangement

This document shows how to use the arrangement endpoint.
"""

# ============================================================================
# STEP 1: Upload a loop audio file
# ============================================================================

POST /api/v1/loops/with-file
Content-Type: multipart/form-data

File: your_loop.wav
Fields:
  - name: "My Loop"
  - genre: "Hip Hop"

# Response includes auto-detected BPM and key:
{
  "id": 1,
  "name": "My Loop",
  "genre": "Hip Hop",
  "bpm": 140,
  "musical_key": "D Minor",
  "duration_seconds": 2.5,
  "file_path": "uploads/loop_123abc.wav"
}


# ============================================================================
# STEP 2: Generate arrangement for the loop
# ============================================================================

POST /api/v1/arrange/1
Content-Type: application/json

# Option A: Specify duration in seconds (15-3600)
{
  "duration_seconds": 180
}

# Option B: Specify exact number of bars (4-4096)
{
  "bars": 105
}

# Option C: Use default (180 seconds / 3 minutes)
{}


# ============================================================================
# RESPONSE: Arrangement metadata JSON
# ============================================================================

{
  "loop_id": 1,
  "bpm": 140.0,
  "key": "D Minor",
  "target_duration_seconds": 180,
  "actual_duration_seconds": 180,
  "total_bars": 105,
  "sections": [
    {
      "name": "Intro",
      "bars": 4,
      "start_bar": 0,
      "end_bar": 3
    },
    {
      "name": "Verse",
      "bars": 8,
      "start_bar": 4,
      "end_bar": 11
    },
    {
      "name": "Hook",
      "bars": 8,
      "start_bar": 12,
      "end_bar": 19
    },
    {
      "name": "Verse",
      "bars": 8,
      "start_bar": 20,
      "end_bar": 27
    },
    {
      "name": "Hook",
      "bars": 8,
      "start_bar": 28,
      "end_bar": 35
    },
    {
      "name": "Bridge",
      "bars": 8,
      "start_bar": 36,
      "end_bar": 43
    },
    {
      "name": "Verse",
      "bars": 8,
      "start_bar": 44,
      "end_bar": 51
    },
    {
      "name": "Hook",
      "bars": 8,
      "start_bar": 52,
      "end_bar": 59
    },
    // ... more sections ...
    {
      "name": "Outro",
      "bars": 4,
      "start_bar": 101,
      "end_bar": 104
    }
  ]
}


# ============================================================================
# SECTION TYPES EXPLAINED
# ============================================================================

1. Intro (4 bars)
   - Sets up the groove
   - Establishes the beat
   
2. Verse (8 bars)
   - Main melodic content
   - Drives the track forward
   
3. Hook (8 bars)
   - Catchy, memorable section
   - Most energetic part
   - Formerly called "Chorus"
   
4. Bridge (8 bars)
   - Contrasting section
   - Adds variety
   - Appears every 2 Verse-Hook cycles
   - Breaks up repetition
   
5. Outro (4 bars)
   - Ending section
   - Brings the beat to a close


# ============================================================================
# ALTERNATIVE ENDPOINTS (URL-based)
# ============================================================================

# By duration (seconds in URL)
POST /api/v1/arrange/1/duration/180

# By bars (bars in URL)
POST /api/v1/arrange/1/bars/105


# ============================================================================
# FLEXIBLE DURATION SUPPORT
# ============================================================================

# Short beat (15 seconds minimum)
POST /api/v1/arrange/1
{"duration_seconds": 15}
# Result: ~8 bars, 4 sections (Intro → Verse → partial → Outro)

# Standard beat (3 minutes default)
POST /api/v1/arrange/1
{}
# Result: ~105 bars @ 140 BPM, 15 sections

# Extended beat (10 minutes)
POST /api/v1/arrange/1
{"duration_seconds": 600}
# Result: ~350 bars @ 140 BPM, 45 sections

# Maximum beat (60 minutes)
POST /api/v1/arrange/1
{"duration_seconds": 3600}
# Result: ~2100 bars @ 140 BPM, 260+ sections


# ============================================================================
# ERROR HANDLING
# ============================================================================

# Loop not found
POST /api/v1/arrange/999
Response: 404 Not Found
{"detail": "Loop 999 not found"}

# Invalid duration (too short)
POST /api/v1/arrange/1
{"duration_seconds": 5}
Response: 422 Unprocessable Entity
{"detail": "duration_seconds must be between 15 and 3600"}

# Invalid duration (too long)
POST /api/v1/arrange/1
{"duration_seconds": 5000}
Response: 422 Unprocessable Entity
{"detail": "duration_seconds must be between 15 and 3600"}


# ============================================================================
# INTEGRATION WITH RENDER PIPELINE (Future Phase)
# ============================================================================

# After getting arrangement metadata, you can use it to generate audio:
# 1. Get arrangement JSON
# 2. For each section, apply effects and processing
# 3. Render final audio with proper transitions
# 4. Save to R2 storage

# This arrangement metadata provides the structure needed for
# intelligent audio rendering with proper intro/verse/hook/bridge/outro
# sections that sound musically coherent.
