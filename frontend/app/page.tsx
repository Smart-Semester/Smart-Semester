export default function Home() {
  return (
    <main className="flex flex-col items-center px-9 py-36 text-center">
      <h1 className="max-w-5xl text-7xl font-serif">
        What is <span className="text-green-800">smart</span> semester?
      </h1>

      <p className="mt-6 text-lg text-green-800 font-serif">
        get summaries and resources for all of your courses, before you register
      </p>

      <p className="mt-6 max-w-5xl text-2xl text-black">
        Give smart semester the classes you&apos;re planning for your next semester
        and smart semester will check the prereqs, and provide curated
        information and resources for each course.
      </p>

      <div className="mt-10 flex gap-12">
        <a
          href="/plan"
          className="w-64 rounded-md bg-green-900 py-3 text-center text-white hover:bg-green-800"
        >
          Plan now
        </a>
        <a
          href="/login"
          className="w-64 rounded-md bg-green-900 py-3 text-center text-white hover:bg-green-800"
        >
          Register / Login
        </a>
      </div>
    </main>
  );
}
