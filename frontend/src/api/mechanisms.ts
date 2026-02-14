import { apiFetch } from "./client";

interface Mechanism {
  label: string;
  value: string;
}

export function fetchMechanisms() {
  return apiFetch<Mechanism[]>("/mechanisms");
}
