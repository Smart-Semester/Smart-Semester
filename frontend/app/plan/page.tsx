"use client";

import { useState } from "react";
import { X } from "lucide-react";

type PlannedCourse = {
  id: string;
  code: string;
};

export default function PlanPage() {
  const [courseInput, setCourseInput] = useState("");
  const [courses, setCourses] = useState<PlannedCourse[]>([]);

  function handleAdd() {
    if (!courseInput.trim()) return;
    setCourses([...courses, { id: crypto.randomUUID(), code: courseInput.trim() }]);
    setCourseInput("");
  }

  function handleRemove(id: string) {
    setCourses(courses.filter((c) => c.id !== id));
  }

  return (
    <main className="flex flex-col items-center px-9 py-36 text-center">
      <h1 className="text-7xl font-serif">Plan for Next Semester</h1>

      <p className="mt-6 text-lg text-green-800 font-serif">
        get summaries and resources for all of your courses, before you register
      </p>

      <div className="mt-10 flex w-full max-w-2xl items-center gap-3 rounded-full border px-4 py-2">
        <input
          type="text"
          value={courseInput}
          onChange={(e) => setCourseInput(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && handleAdd()}
          placeholder="e.g. CS 3358, MATH 2471"
          className="flex-1 bg-transparent px-2 py-2 outline-none"
        />
        <button
          onClick={handleAdd}
          className="rounded-full bg-green-900 px-6 py-2 text-white hover:bg-green-800"
        >
          Add
        </button>
      </div>

      {courses.length > 0 && (
        <div className="mt-10 w-full max-w-2xl divide-y text-left">
          {courses.map((course) => (
            <div key={course.id} className="flex items-start gap-3 py-4">
              <button
                onClick={() => handleRemove(course.id)}
                aria-label="Remove course"
                className="mt-1 text-green-800"
              >
                <X size={18} />
              </button>
              <div>
                <p className="font-semibold">{course.code}</p>
                <p className="text-sm text-gray-600">
                  Course Summary Body text for whatever you&apos;d like to say. Add
                  main takeaway points, quotes, anecdotes, or even a very very
                  short story.
                </p>
              </div>
            </div>
          ))}
        </div>
      )}

      {courses.length > 0 && (
        <button className="mt-10 w-full max-w-2xl rounded-md bg-green-900 py-3 text-white hover:bg-green-800">
          Submit
        </button>
      )}
    </main>
  );
}
