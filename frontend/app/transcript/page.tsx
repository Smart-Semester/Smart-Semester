"use client";

import { useState } from "react";
import { Info, X } from "lucide-react";

export default function TranscriptPage() {
  const [showInfo, setShowInfo] = useState(false);
  const [transcriptText, setTranscriptText] = useState("");

  return (
    <main className="flex flex-col items-center px-9 py-36 text-center">
      <h1 className="text-7xl font-serif">Input your transcript</h1>

      <div className="relative mt-6">
        <button
          onClick={() => setShowInfo(!showInfo)}
          className="flex items-center gap-2 text-lg text-green-800 font-serif"
        >
          <Info size={18} />
          how do i input my transcript into my smart semester profile?
        </button>

        {showInfo && (
          <div className="absolute left-1/2 top-full z-10 mt-2 w-80 -translate-x-1/2 rounded-md border bg-white p-5 text-left shadow-lg">
            <div className="mb-2 flex items-center justify-between">
              <div className="flex items-center gap-2 font-semibold text-green-800">
                <Info size={18} />
                Transcript Input
              </div>
              <button onClick={() => setShowInfo(false)} aria-label="Close">
                <X size={18} />
              </button>
            </div>
            <p className="mb-4 text-sm text-gray-600">
              Open your TXST Degree audit → Click the three dots next to the
              printer → &apos;View Course History&apos; → Copy it → Paste it in
            </p>
            <button
              onClick={() => setShowInfo(false)}
              className="rounded-md bg-green-900 px-4 py-2 text-sm text-white hover:bg-green-800"
            >
              Return
            </button>
          </div>
        )}
      </div>

      <div className="mt-10 flex w-full max-w-2xl items-center gap-3 rounded-full border px-4 py-2">
        <input
          type="text"
          value={transcriptText}
          onChange={(e) => setTranscriptText(e.target.value)}
          placeholder="Enter formatted transcript info"
          className="flex-1 bg-transparent px-2 py-2 outline-none"
        />
        <button className="rounded-full bg-green-900 px-6 py-2 text-white hover:bg-green-800">
          Enter
        </button>
      </div>
    </main>
  );
}
