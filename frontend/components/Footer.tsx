export default function Footer() {
  return (
    <footer className="border-t py-6 text-center text-sm text-gray-500">
      <a href="/about" className="hover:underline">About</a>
      <span className="mx-2">•</span>
      <a href="/privacy" className="hover:underline">Privacy</a>
      <span className="mx-2">•</span>
      <a href="/contact" className="hover:underline">Contact</a>
    </footer>
  );
}
