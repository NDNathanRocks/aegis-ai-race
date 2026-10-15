import { Suspense } from "react";
import { RaceArena } from "@/components/RaceArena";

export default function Home() {
  // useSearchParams (for ?embed=true) requires a Suspense boundary.
  return (
    <Suspense fallback={<div className="p-6 text-sm text-mute">Loading arena…</div>}>
      <RaceArena />
    </Suspense>
  );
}
