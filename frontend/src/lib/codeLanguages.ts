// Languages students can submit code in. Must match CODE_LANGUAGES in
// app/code_languages.py, which refuses any other code file at upload.
export type CodeLanguageId = "python" | "java" | "javascript" | "c" | "cpp" | "csharp" | "go" | "ruby" | "php";

export const CODE_LANGUAGES: { id: CodeLanguageId; name: string; extensions: string[] }[] = [
  { id: "python", name: "Python", extensions: [".py", ".ipynb"] },
  { id: "java", name: "Java", extensions: [".java"] },
  { id: "javascript", name: "JavaScript", extensions: [".js"] },
  { id: "c", name: "C", extensions: [".c", ".h"] },
  { id: "cpp", name: "C++", extensions: [".cpp", ".cc", ".cxx", ".h", ".hpp", ".hh", ".hxx"] },
  { id: "csharp", name: "C#", extensions: [".cs"] },
  { id: "go", name: "Go", extensions: [".go"] },
  { id: "ruby", name: "Ruby", extensions: [".rb"] },
  { id: "php", name: "PHP", extensions: [".php"] },
];

/** The languages an assignment accepts: its chosen ones, or every language when none were chosen. */
export function languagesFor(chosen: CodeLanguageId[] | undefined) {
  return chosen && chosen.length ? CODE_LANGUAGES.filter((l) => chosen.includes(l.id)) : CODE_LANGUAGES;
}

export const languageNames = (chosen: CodeLanguageId[]) => languagesFor(chosen).map((l) => l.name).join(", ");
