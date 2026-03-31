"use client";

/**
 * Upload Page  (/)
 *
 * Lets the user pick an audio file (WAV or MP3), enter loop metadata, and
 * upload the file to FastAPI via POST /api/v1/loops/with-file.
 *
 * On success the returned loop ID is displayed so the user can navigate to
 * the Generate Arrangement page (/generate).
 *
 * Request path:
 *   browser → POST /api/v1/loops/with-file (Next.js proxy)
 *          → FastAPI POST /api/v1/loops/with-file   ✅
 */

import { useRef, useState } from "react";
import { uploadLoop, type LoopResponse } from "@/api/client";

const ACCEPTED_TYPES = ["audio/wav", "audio/mpeg", "audio/mp3", "audio/x-wav"];
const MAX_SIZE_MB = 50;

export default function UploadPage() {
  const fileInputRef = useRef<HTMLInputElement>(null);

  const [file, setFile] = useState<File | null>(null);
  const [name, setName] = useState("");
  const [genre, setGenre] = useState("");
  const [tempo, setTempo] = useState("");

  const [isUploading, setIsUploading] = useState(false);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [result, setResult] = useState<LoopResponse | null>(null);

  // -------------------------------------------------------------------------
  // File selection validation
  // -------------------------------------------------------------------------

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const selected = e.target.files?.[0] ?? null;
    setFile(null);
    setUploadError(null);

    if (!selected) return;

    if (!ACCEPTED_TYPES.includes(selected.type)) {
      setUploadError("Only WAV and MP3 files are supported.");
      return;
    }

    if (selected.size > MAX_SIZE_MB * 1024 * 1024) {
      setUploadError(`File must be ${MAX_SIZE_MB} MB or smaller.`);
      return;
    }

    setFile(selected);
    // Pre-fill the name field from the filename (without extension)
    if (!name) {
      setName(selected.name.replace(/\.[^.]+$/, ""));
    }
  };

  // -------------------------------------------------------------------------
  // Upload handler
  // -------------------------------------------------------------------------

  const handleUpload = async () => {
    if (!file) {
      setUploadError("Please select an audio file.");
      return;
    }
    if (!name.trim()) {
      setUploadError("Please enter a loop name.");
      return;
    }

    setIsUploading(true);
    setUploadError(null);
    setResult(null);

    try {
      const loop = await uploadLoop(file, {
        name: name.trim(),
        genre: genre.trim() || undefined,
        tempo: tempo ? parseFloat(tempo) : undefined,
      });
      setResult(loop);
    } catch (err) {
      setUploadError(
        err instanceof Error ? err.message : "An unexpected error occurred."
      );
    } finally {
      setIsUploading(false);
    }
  };

  // -------------------------------------------------------------------------
  // Render
  // -------------------------------------------------------------------------

  return (
    <main className="mx-auto max-w-xl p-8 space-y-6">
      <h1 className="text-3xl font-bold">Upload Loop</h1>

      {/* File picker */}
      <div className="space-y-1">
        <label className="block text-sm font-medium" htmlFor="file">
          Audio file (WAV or MP3, max {MAX_SIZE_MB} MB)
        </label>
        <input
          id="file"
          type="file"
          accept=".wav,.mp3,audio/wav,audio/mpeg"
          ref={fileInputRef}
          onChange={handleFileChange}
          className="block w-full text-sm border rounded px-3 py-2"
        />
        {file && (
          <p className="text-xs text-gray-500">
            {file.name} ({(file.size / 1024 / 1024).toFixed(2)} MB)
          </p>
        )}
      </div>

      {/* Metadata */}
      <div className="space-y-3">
        <div>
          <label className="block text-sm font-medium mb-1" htmlFor="name">
            Loop name <span className="text-red-500">*</span>
          </label>
          <input
            id="name"
            type="text"
            className="w-full border rounded px-3 py-2"
            value={name}
            onChange={(e) => setName(e.target.value)}
          />
        </div>

        <div>
          <label className="block text-sm font-medium mb-1" htmlFor="genre">
            Genre (optional)
          </label>
          <input
            id="genre"
            type="text"
            placeholder="e.g. Trap, R&B, Pop"
            className="w-full border rounded px-3 py-2"
            value={genre}
            onChange={(e) => setGenre(e.target.value)}
          />
        </div>

        <div>
          <label className="block text-sm font-medium mb-1" htmlFor="tempo">
            Tempo / BPM (optional)
          </label>
          <input
            id="tempo"
            type="number"
            min={40}
            max={300}
            placeholder="e.g. 140"
            className="w-full border rounded px-3 py-2"
            value={tempo}
            onChange={(e) => setTempo(e.target.value)}
          />
        </div>
      </div>

      {/* Upload button */}
      <button
        onClick={handleUpload}
        disabled={isUploading}
        className="w-full bg-blue-600 text-white py-2 rounded disabled:opacity-50"
      >
        {isUploading ? "Uploading…" : "Upload Loop"}
      </button>

      {/* Error */}
      {uploadError && (
        <p className="text-red-600 text-sm">{uploadError}</p>
      )}

      {/* Success */}
      {result && (
        <section className="border rounded p-4 space-y-2 bg-green-50">
          <h2 className="font-semibold text-green-800">Upload successful!</h2>
          <p className="text-sm">
            <span className="font-medium">Loop ID:</span>{" "}
            <code className="font-mono">{result.id}</code>
          </p>
          {result.bpm !== null && result.bpm !== undefined && (
            <p className="text-sm">
              <span className="font-medium">BPM (detected):</span> {result.bpm}
            </p>
          )}
          {result.musical_key && (
            <p className="text-sm">
              <span className="font-medium">Key (detected):</span>{" "}
              {result.musical_key}
            </p>
          )}
          <a
            href={`/generate?loopId=${result.id}`}
            className="inline-block mt-2 bg-green-600 text-white px-4 py-2 rounded text-sm"
          >
            Generate Arrangement →
          </a>
        </section>
      )}
    </main>
  );
}
