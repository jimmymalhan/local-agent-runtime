# {{name}}

React SPA with Vite, TypeScript, Tailwind CSS, and Zustand state management.

## Quick start

```bash
npm install
npm run dev
```

Open [http://localhost:5173](http://localhost:5173).

## Scripts

| Command | Description |
|---|---|
| `npm run dev` | Start dev server |
| `npm run build` | Production build |
| `npm test` | Run Vitest tests |
| `npm run lint` | ESLint check |

## Project structure

```
src/
  App.tsx           # Root component
  components/       # Reusable UI components
  store/            # Zustand state stores
  lib/utils.ts      # Utility functions
  types/            # TypeScript types
tests/              # Vitest + Testing Library
```

## Docker

```bash
docker build -t {{name}} .
docker run -p 80:80 {{name}}
```
