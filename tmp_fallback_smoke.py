import struct
import requests

upload_url = "https://looparchitect-frontend.vercel.app/api/v1/loops/upload"
get_base = "https://looparchitect-frontend.vercel.app/api/v1/loops"

sample_rate = 22050
num_samples = 2205
pcm = b"".join(struct.pack("<h", 0) for _ in range(num_samples))
header = struct.pack(
    "<4sI4s4sIHHIIHH4sI",
    b"RIFF",
    36 + len(pcm),
    b"WAVE",
    b"fmt ",
    16,
    1,
    1,
    sample_rate,
    sample_rate * 2,
    2,
    16,
    b"data",
    len(pcm),
)
wav = header + pcm

upload_response = requests.post(
    upload_url,
    files={"file": ("probe.wav", wav, "audio/wav")},
    timeout=90,
)
print("UPLOAD_STATUS", upload_response.status_code)
print(upload_response.text[:400])

if upload_response.ok:
    payload = upload_response.json()
    loop_id = payload.get("loop_id")
    if loop_id:
        details_response = requests.get(f"{get_base}/{loop_id}", timeout=90)
        print("DETAIL_STATUS", details_response.status_code)
        print(details_response.text[:400])
