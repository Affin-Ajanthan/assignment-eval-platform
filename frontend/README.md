Next.js frontend for the AI-Assisted Assignment Evaluation Platform (see
the top-level `README.md` for the whole system). Four routes, one per
role/screen:

- `/login` -- single login page, redirects to the right dashboard by role
- `/admin` -- create subjects, instructors, students; assign subjects
- `/instructor` -- rubrics, similarity check, auto-evaluate, manual grading
- `/student` -- upload code/report/video for an enrolled subject

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
