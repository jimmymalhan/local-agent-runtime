import { Button } from "@/components/ui/button";

export default function Home() {
  return (
    <main className="flex min-h-screen flex-col items-center justify-center p-24 gap-8">
      <div className="text-center">
        <h1 className="text-4xl font-bold tracking-tight mb-4">{{name}}</h1>
        <p className="text-muted-foreground text-lg mb-8">
          Your Next.js 14 application is ready.
        </p>
        <div className="flex gap-4 justify-center">
          <Button asChild>
            <a href="/api/hello">Try the API</a>
          </Button>
          <Button variant="outline" asChild>
            <a
              href="https://nextjs.org/docs"
              target="_blank"
              rel="noopener noreferrer"
            >
              Documentation
            </a>
          </Button>
        </div>
      </div>
    </main>
  );
}
