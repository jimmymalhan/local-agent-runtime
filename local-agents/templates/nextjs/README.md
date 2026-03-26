# {{name}}

Next.js 14 application with TypeScript, Tailwind CSS, and Shadcn UI.

## Quick start

```bash
npm install
npm run dev
```

Open [http://localhost:3000](http://localhost:3000).

## Scripts

| Command | Description |
|---|---|
| `npm run dev` | Start dev server with hot reload |
| `npm run build` | Production build |
| `npm start` | Start production server |
| `npm test` | Run Vitest tests |
| `npm run lint` | ESLint check |

## Project structure

```
src/
  app/              # Next.js App Router pages and API routes
  components/ui/    # Reusable UI components (Shadcn pattern)
  lib/              # Utilities (cn, etc.)
tests/              # Vitest + Testing Library tests
```

## Docker

```bash
docker build -t {{name}} .
docker run -p 3000:3000 {{name}}
```
