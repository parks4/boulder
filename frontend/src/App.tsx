import { Toaster } from "sonner";
import { AppShell } from "@/components/layout/AppShell";

export default function App() {
  return (
    <>
      <AppShell />
      <Toaster position="bottom-right" richColors />
    </>
  );
}
