Next.js frontend for the AI-Assisted Assignment Evaluation Platform (see
the top-level `README.md` for the whole system). Four routes, one per
role/screen:

- `/login` -- single login page, redirects to the right dashboard by role
- `/admin` -- three tabs (Subjects, Instructors, Students): create and edit them; subjects and instructors are linked from either side
- `/instructor` -- the instructor's subjects as boxes
- `/instructor/subjects/<id>` -- one subject, two tabs: Assignments (create, edit, delete, Open; student access) and Rubrics
- `/instructor/subjects/<id>/assignments/<assignment id>` -- one assignment: Submissions & grading, Similarity, Batch evaluate
- `/instructor/assignments/new` and `/instructor/assignments/<id>` -- create and edit an assignment; both go back to the subject page
- `/student` -- every subject as a box; a joined one opens, any other is locked until the student joins it with its password
- `/student/subjects/<id>` -- one joined subject: its assignments (upload code/report/video, or do a code challenge)

Stack: Next.js 16 (App Router, Turbopack), React 19, TypeScript, Tailwind
CSS v4. All API access goes through `src/lib/api.ts` (`apiFetch`), which
attaches the bearer token from `localStorage` and redirects to `/login`
on an expired session.

## Run it

```bash
npm install
npm run dev
```

Open `http://localhost:3000/login`. The backend must already be running
(see the top-level README) -- by default the app talks to it at
`http://localhost:8000`; change `NEXT_PUBLIC_API_BASE` in `.env.local` if
you run the backend somewhere else.

For a production build:

```bash
npm run build
npm start
```

## Notes

- Use `http://localhost:3000`, not `http://127.0.0.1:3000`, when testing
  in a browser -- Next's dev server only allows its HMR/dev assets from
  `localhost` by default, and loading via `127.0.0.1` silently breaks
  client-side interactivity (forms fall back to a native, non-JS submit).
  This only affects local dev; it doesn't matter for a production build.
- `eslint.config.mjs` turns off `react-hooks/set-state-in-effect` for
  this project: every page here is a client-rendered dashboard whose
  data comes from a bearer-token-authenticated API, so "fetch on mount,
  setState with the result" `useEffect`s are the correct pattern, not a
  bug the rule should flag.


Role	      Email	                  Password
Admin	      admin@school.local	    Admin@123
Instructor	instructor@school.local	Instructor@123
Student 1	  student1@school.local	  Student1@123
Student 2	  student2@school.local	  Student2@123
Student 3	  student3@school.local	  Student3@123