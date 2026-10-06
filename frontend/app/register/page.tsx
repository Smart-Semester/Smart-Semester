"use client";

import { useState } from "react";
import { Eye, EyeOff } from "lucide-react";

export default function RegisterPage() {
  const [showPassword, setShowPassword] = useState(false);

  return (
    <main className="flex flex-col items-center px-9 py-24 text-center">
      <h1 className="text-6xl font-serif">Sign up or log in</h1>

      <div className="mt-10 w-full max-w-md rounded-md border p-6 text-left">
        <label className="mb-1 block text-sm">Email</label>
        <input
          type="email"
          placeholder="Email*"
          className="mb-4 w-full rounded-md border px-3 py-2 outline-none focus:border-green-800"
        />

        <label className="mb-1 block text-sm">Password</label>
        <div className="relative mb-6">
          <input
            type={showPassword ? "text" : "password"}
            placeholder="Password*"
            className="w-full rounded-md border px-3 py-2 pr-10 outline-none focus:border-green-800"
          />
          <button
            type="button"
            onClick={() => setShowPassword(!showPassword)}
            className="absolute right-3 top-1/2 -translate-y-1/2 text-gray-500"
            aria-label="Toggle password visibility"
          >
            {showPassword ? <EyeOff size={18} /> : <Eye size={18} />}
          </button>
        </div>

        <button className="w-full rounded-md bg-green-900 py-3 text-white hover:bg-green-800">
          Register
        </button>
      </div>

      <p className="mt-6 text-sm">
        Already have an account?{" "}
        <a href="/login" className="underline">
          Log in
        </a>
      </p>
    </main>
  );
}
