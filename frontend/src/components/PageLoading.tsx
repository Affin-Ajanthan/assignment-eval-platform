/** Shown while a page checks the login and loads, instead of a blank page. */
export default function PageLoading({ text = "Loading..." }: { text?: string }) {
  return (
    <div role="status" className="flex min-h-[50vh] flex-col items-center justify-center gap-3 text-sm text-gray-600">
      <span
        aria-hidden="true"
        className="h-8 w-8 animate-spin rounded-full border-4 border-gray-200 border-t-blue-600"
      />
      {text}
    </div>
  );
}
