import { useCounterStore } from "./store/counter";
import { Button } from "./components/Button";

export default function App() {
  const { count, increment, decrement, reset } = useCounterStore();

  return (
    <div className="min-h-screen flex flex-col items-center justify-center gap-8 p-8">
      <h1 className="text-4xl font-bold">{{name}}</h1>

      <div className="flex flex-col items-center gap-4">
        <p className="text-6xl font-mono font-bold">{count}</p>
        <div className="flex gap-2">
          <Button onClick={decrement} variant="outline">-</Button>
          <Button onClick={reset} variant="ghost">Reset</Button>
          <Button onClick={increment}>+</Button>
        </div>
      </div>

      <p className="text-sm text-gray-500">
        Built with React + Vite + TypeScript + Zustand
      </p>
    </div>
  );
}
