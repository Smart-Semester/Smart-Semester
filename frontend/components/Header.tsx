"use client";

import { useState } from "react";
import { Menu, User, X, Home, ArrowRight, Calendar, Phone, Shield } from "lucide-react";

export default function Header() {
  const [menuOpen, setMenuOpen] = useState(false);
  const [accountOpen, setAccountOpen] = useState(false);

  return (
    <header className="relative flex items-center justify-between border-b px-6 py-4">
      <div className="flex items-center gap-4">
        <button onClick={() => setMenuOpen(!menuOpen)} aria-label="Menu">
          <Menu size={24} />
        </button>
        <a href="/" className="font-serif text-2xl">
          <span className="text-green-800">smart</span> semester
        </a>
      </div>

      <button onClick={() => setAccountOpen(!accountOpen)} aria-label="Account">
        <User size={24} />
      </button>

      {menuOpen && (
        <div className="absolute left-6 top-full z-10 mt-2 w-72 rounded-md border bg-white p-4 shadow-lg">
          <div className="mb-3 flex items-center justify-between">
            <div>
              <p className="text-xs text-gray-500">Smart Semester</p>
              <p className="font-semibold">Menu</p>
            </div>
            <button onClick={() => setMenuOpen(false)} aria-label="Close menu">
              <X size={20} className="text-green-800" />
            </button>
          </div>
          <nav className="flex flex-col divide-y">
            <a href="/" className="flex items-center gap-3 py-3">
              <Home size={18} />
              <span>
                <span className="block font-medium">Home</span>
                <span className="block text-sm text-gray-500">Go to the homepage</span>
              </span>
            </a>
            <a href="/plan" className="flex items-center gap-3 py-3">
              <ArrowRight size={18} />
              <span>
                <span className="block font-medium">Next semester</span>
                <span className="block text-sm text-gray-500">Plan for your next semester</span>
              </span>
            </a>
            <a href="/transcript" className="flex items-center gap-3 py-3">
              <Calendar size={18} />
              <span>
                <span className="block font-medium">Update transcript</span>
                <span className="block text-sm text-gray-500">Update your transcript info</span>
              </span>
            </a>
            <a href="/contact" className="flex items-center gap-3 py-3">
              <Phone size={18} />
              <span>
                <span className="block font-medium">Contact</span>
                <span className="block text-sm text-gray-500">Contact us</span>
              </span>
            </a>
            <a href="/privacy" className="flex items-center gap-3 py-3">
              <Shield size={18} />
              <span>
                <span className="block font-medium">Privacy</span>
                <span className="block text-sm text-gray-500">Privacy policy</span>
              </span>
            </a>
          </nav>
        </div>
      )}

      {accountOpen && (
        <div className="absolute right-6 top-full z-10 mt-2 w-64 rounded-md border bg-white p-4 shadow-lg">
          <div className="mb-3 flex items-center justify-between">
            <div>
              <p className="text-xs text-gray-500">Smart Semester</p>
              <p className="font-semibold">Account</p>
            </div>
            <button onClick={() => setAccountOpen(false)} aria-label="Close account menu">
              <X size={20} className="text-green-800" />
            </button>
          </div>
          <a href="/account" className="flex items-center gap-3 py-2">
            <User size={18} />
            <span>
              <span className="block font-medium">View Account</span>
              <span className="block text-sm text-gray-500">View your account details.</span>
            </span>
          </a>
        </div>
      )}
    </header>
  );
}
